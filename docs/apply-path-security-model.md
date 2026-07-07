# Apply-path security model — blast-radius containment

> **Why this document exists.** The POC runs entirely in containers, so
> none of this bites until we wire into production — which is exactly
> when it must not have been forgotten. This is the durable record of
> the write-path security model (spec §5.1/§5.6), with worked examples
> for Oracle and Postgres and the go-live checklist. Nothing connects
> to a production database until every box in §6 is ticked.

## 1. The one-sentence model

The only SQL that can ever execute against a target database is a
**DBA-reviewed catalogue template filled with schema-validated
parameters**, run by an account that — in the production target state —
**cannot execute anything else even if fully compromised**, because the
database engine itself only grants it EXECUTE on a finite set of
argument-capped procedures.

## 2. What actually runs (and what never does)

A runbook-action file contains a `rendered_sql` field. **It is for the
human reviewer's eyes only and is never executed.** At apply time the
applier re-renders the SQL from the catalogue template + the validated
parameters and refuses to run unless its rendering matches the file
byte-for-byte.

Consequences:

- LLM-mangled SQL cannot reach a database — the LLM only ever supplies
  *parameters* to a reviewed template.
- An action file hand-edited after review cannot reach a database — the
  re-render check fails.
- The review surface (template in git) and the execution surface
  (template re-rendered by the applier; procedures in the DB) are the
  same artifact, so review is never of something other than what runs.

## 3. The four layers, outermost to innermost

Design goal: "the wrong SQL goes through" must be *structurally
impossible*, not unlikely — and a leaked credential must be nearly
useless.

1. **Credential exposure.** Apply credentials are GitLab
   protected+masked CI variables → they exist **only on
   protected-branch pipelines**. A pipeline from an unmerged branch has
   no production credential at all. Separate credentials per
   environment; prod creds never appear in pre-merge (MR) pipelines.
2. **Applier gates.** Template-only execution (§2); one statement per
   action; statement-type check (an `add_datafile` action whose SQL
   doesn't parse as `ALTER TABLESPACE` is refused); deny-list backstop
   (`DROP`, `TRUNCATE`, `GRANT`, `CREATE USER`, anonymous PL/SQL / DO
   blocks) even though the template model already makes these
   unreachable.
3. **DB-enforced procedures — the layer that holds when 1 and 2 fail.**
   The apply account has **no direct DDL privileges**. Each catalogue
   action is deployed *into the database* as a procedure in a locked
   admin schema that validates its own arguments inside the engine and
   only then acts. The apply account gets `EXECUTE` on those procedures
   and nothing else. Never `DBA`, never `SYSDBA`, never superuser.
   `DROP TABLE` from that account is refused by Oracle/Postgres
   themselves, not by our code.
4. **Role hardening.** Connection limit 1; statement/lock timeouts
   bound to the role (PG) or profile limits (Oracle); network access
   restricted to the CI-runner segment (pg_hba / listener ACLs or
   firewall). A stolen password that can't connect from anywhere else,
   can't hold locks long, and can only call capped procedures is a
   contained incident.

**Residual risk, stated honestly:** with all four layers on, what
remains is *right action, wrong parameters* (adding 8G to the wrong
tablespace). Bounded by: parameter caps in the procedure, apply-time
precondition re-check ("is USER_INDEX_04 actually still >85% full?"),
two human gates (DBA merge + manual apply click), and the layered audit
trail for fast detection.

**Pragmatic staging:** v2.0 may ship with narrow per-action grants
(e.g. `ALTER TABLESPACE` only) + layers 1/2/4 to keep the first cut
small. **Layer 3 (procedure enforcement) is the bar for production** —
it is a go-live checklist item, not an optimisation.

## 4. Worked example — Oracle (Standard Edition)

Illustrative sketch; real provisioning SQL ships under `provisioning/`
with the apply-path task and is reviewed like any change.

```sql
-- Locked owner schema: nobody logs in as it; it exists to own the
-- privileges and the package (definer's rights). NO CREATE SESSION —
-- the deploying DBA compiles the package; the owner never authenticates
-- (else an ACCOUNT UNLOCK mistake yields a login that holds ALTER
-- TABLESPACE directly). [threat model M5]
CREATE USER dba_actions_owner IDENTIFIED BY "..." ACCOUNT LOCK;
GRANT ALTER TABLESPACE TO dba_actions_owner; -- the ONE privilege this action needs
-- Roles are DISABLED inside definer's-rights PL/SQL, so the body cannot
-- rely on SELECT_CATALOG_ROLE to read the dictionary. Grant the exact
-- object it needs as a DIRECT grant. Do NOT reach for SELECT ANY
-- DICTIONARY — that would expose SYS.USER$ password hashes on an account
-- that also holds ALTER TABLESPACE. [threat model H7/C3]
GRANT SELECT ON SYS.DBA_TABLESPACES TO dba_actions_owner;
GRANT SELECT ON SYS.DBA_DATA_FILES TO dba_actions_owner;  -- for the aggregate cap

-- Allowlist lives in a table the owner controls, not in code. Its
-- CONTENTS are provisioned from git and audited — adding a row is a
-- reviewed change, not ad-hoc DML. [threat model M4]
CREATE TABLE dba_actions_owner.tablespace_allowlist (
  tablespace_name VARCHAR2(30) PRIMARY KEY,
  max_files       NUMBER NOT NULL,   -- aggregate caps, enforced in-proc
  max_total_gb    NUMBER NOT NULL
);

CREATE OR REPLACE PACKAGE dba_actions_owner.dba_actions AS
  PROCEDURE add_datafile(p_tablespace IN VARCHAR2, p_size_gb IN PLS_INTEGER);
END dba_actions;
/
CREATE OR REPLACE PACKAGE BODY dba_actions_owner.dba_actions AS
  PROCEDURE add_datafile(p_tablespace IN VARCHAR2, p_size_gb IN PLS_INTEGER) IS
    l_ts         dba_tablespaces.tablespace_name%TYPE;
    l_max_files  NUMBER;
    l_max_gb     NUMBER;
    l_cur_files  NUMBER;
    l_cur_gb     NUMBER;
  BEGIN
    -- Per-call cap:
    IF p_size_gb NOT BETWEEN 1 AND 32 THEN
      RAISE_APPLICATION_ERROR(-20001, 'size_gb out of policy (1..32)');
    END IF;
    -- Must exist AND be allowlisted; fetch the aggregate caps:
    SELECT t.tablespace_name, a.max_files, a.max_total_gb
      INTO l_ts, l_max_files, l_max_gb
      FROM dba_tablespaces t
      JOIN dba_actions_owner.tablespace_allowlist a
        ON a.tablespace_name = t.tablespace_name
     WHERE t.tablespace_name = UPPER(p_tablespace);
    -- AGGREGATE cap: per-call limits do NOT bound cumulative growth, so
    -- a loop of valid calls could fill a shared mount. Enforce total
    -- footprint and file count here. [threat model H6]
    SELECT COUNT(*), NVL(SUM(bytes),0)/1024/1024/1024
      INTO l_cur_files, l_cur_gb
      FROM dba_data_files WHERE tablespace_name = l_ts;
    IF l_cur_files + 1 > l_max_files
       OR l_cur_gb + p_size_gb > l_max_gb THEN
      RAISE_APPLICATION_ERROR(-20002, 'tablespace aggregate cap exceeded');
    END IF;
    -- l_ts comes from the data dictionary (already a real, allowlisted
    -- name); DBMS_ASSERT is belt-and-suspenders. p_size_gb is a
    -- range-checked integer, safe to concatenate.
    EXECUTE IMMEDIATE 'ALTER TABLESPACE '
      || DBMS_ASSERT.ENQUOTE_NAME(DBMS_ASSERT.SIMPLE_SQL_NAME(l_ts))
      || ' ADD DATAFILE SIZE ' || p_size_gb
      || 'G AUTOEXTEND ON NEXT 1G MAXSIZE 32G';
    -- Audit is written HERE, inside the definer's package, into an
    -- owner-owned table the apply account cannot touch — so the applier
    -- cannot tamper with its own trail. [threat model M1]
    INSERT INTO dba_actions_owner.dba_agent_audit(...) VALUES (...);
  END add_datafile;
END dba_actions;
/

-- The apply account: EXECUTE on the package and NOTHING else.
CREATE USER dba_agent_apply IDENTIFIED BY "..."
  PROFILE dba_agent_profile;   -- SESSIONS_PER_USER 1, CPU_PER_CALL, connect limits
GRANT CREATE SESSION TO dba_agent_apply;
GRANT EXECUTE ON dba_actions_owner.dba_actions TO dba_agent_apply;
-- No ALTER TABLESPACE. No DBA. No SELECT on anything. No DML on the audit table.

-- Engine-enforced audit. Note: the ALTER TABLESPACE executes as the
-- DEFINER (dba_actions_owner), so a policy keyed BY dba_agent_apply
-- captures the package EXECUTE but may NOT attribute the DDL. Audit the
-- action itself too, and assert in the go-live test that the DDL is
-- captured, not just the EXECUTE. [threat model M2]
CREATE AUDIT POLICY dba_agent_apply_pol ACTIONS ALL;
AUDIT POLICY dba_agent_apply_pol BY dba_agent_apply;
CREATE AUDIT POLICY dba_actions_ddl_pol ACTIONS ALTER TABLESPACE;
AUDIT POLICY dba_actions_ddl_pol BY dba_actions_owner;
```

Definer's rights means the package runs with `dba_actions_owner`'s
privileges; the caller never holds them. The owner account stays
`ACCOUNT LOCK`ed with no `CREATE SESSION` — it is a privilege container,
not a login. **Reminder (threat model T3/F-DB10):** this contains the
apply account, not a rogue DBA — on Standard Edition there is no Database
Vault to protect the owner schema from `DBA`-privileged users.

## 5. Worked example — Postgres

Same shape (`SECURITY DEFINER` = Postgres's definer's rights), but
**Postgres has two famous footguns Oracle doesn't**, and both are
mandatory to handle:

- **Footgun 1 — PUBLIC execute.** Postgres grants EXECUTE on new
  functions to `PUBLIC` by default. Every action function must
  `REVOKE ... FROM PUBLIC` or the "only the apply account can call it"
  property silently doesn't hold.
- **Footgun 2 — search_path hijacking.** A SECURITY DEFINER function
  that doesn't pin `search_path` can be tricked into resolving names
  against attacker-controlled schemas. Every action function pins
  `SET search_path = ''` and fully schema-qualifies every reference —
  tighter than the docs' `pg_catalog, pg_temp` example, and it removes
  `pg_temp` as a shadowing avenue entirely. [threat model F14d]

```sql
-- Privilege container (NOLOGIN — the PG analogue of ACCOUNT LOCK):
CREATE ROLE dba_actions_owner NOLOGIN;
-- Give it exactly what the action needs, PER TABLE — never the
-- pg_maintain ROLE, which grants MAINTAIN on every table in the DB
-- (VACUUM FULL / CLUSTER / LOCK on anything = rewrite+lock DoS).
-- [threat model H8]
GRANT MAINTAIN ON TABLE app.orders TO dba_actions_owner;   -- PG 17+, per table

CREATE SCHEMA dba_actions AUTHORIZATION dba_actions_owner;

-- Allowlist CONTENTS provisioned from git and audited. [threat model M4]
CREATE TABLE dba_actions.table_allowlist (
  schema_name text NOT NULL,
  table_name  text NOT NULL,
  PRIMARY KEY (schema_name, table_name)
);

-- Owner-owned, append-only audit: the apply account has no DML on it,
-- so the applier cannot rewrite its own trail. [threat model M1]
CREATE TABLE dba_actions.audit (
  id bigint GENERATED ALWAYS AS IDENTITY, at timestamptz DEFAULT now(),
  action text, args jsonb, phase text            -- 'begin' / 'end' rows
);

CREATE OR REPLACE FUNCTION dba_actions.analyze_table(p_schema text, p_table text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''                          -- footgun 2, tightest form
AS $$
BEGIN
  -- Lock bound set HERE (runs as owner; the caller cannot SET it away,
  -- unlike a role-level default GUC). [threat model H9]
  SET LOCAL lock_timeout = '10s';
  PERFORM 1 FROM dba_actions.table_allowlist a
   WHERE a.schema_name = p_schema AND a.table_name = p_table;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'table %.% not in action allowlist', p_schema, p_table;
  END IF;
  PERFORM 1 FROM pg_catalog.pg_tables
   WHERE schemaname = p_schema AND tablename = p_table;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'table %.% does not exist', p_schema, p_table;
  END IF;
  INSERT INTO dba_actions.audit(action, args, phase)
    VALUES ('analyze_table', jsonb_build_object('s',p_schema,'t',p_table), 'begin');
  EXECUTE format('ANALYZE %I.%I', p_schema, p_table);  -- %I quotes identifiers
  INSERT INTO dba_actions.audit(action, args, phase)
    VALUES ('analyze_table', jsonb_build_object('s',p_schema,'t',p_table), 'end');
END $$;
ALTER FUNCTION dba_actions.analyze_table(text, text) OWNER TO dba_actions_owner;

REVOKE ALL ON FUNCTION dba_actions.analyze_table(text, text) FROM PUBLIC;  -- footgun 1

-- The apply account: EXECUTE on action functions and NOTHING else.
CREATE ROLE dba_agent_apply LOGIN PASSWORD '...'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  CONNECTION LIMIT 1;
-- These are DEFAULTS a compromised session can override (SET x = 0);
-- they are hygiene, NOT a hard control. The real lock bound is the
-- SET LOCAL inside the function above. [threat model H9]
ALTER ROLE dba_agent_apply SET statement_timeout = '5min';
ALTER ROLE dba_agent_apply SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE dba_agent_apply SET log_statement = 'all';   -- engine-enforced audit
GRANT USAGE ON SCHEMA dba_actions TO dba_agent_apply;
GRANT EXECUTE ON FUNCTION dba_actions.analyze_table(text, text) TO dba_agent_apply;
-- No DML on dba_actions.audit. No table privileges.
```

Plus `pg_hba.conf`: the `dba_agent_apply` role only accepts connections
from the CI-runner segment, TLS required.

### Postgres caveat — what can't be wrapped in a function

A few maintenance commands refuse to run inside a function/transaction
context: **`VACUUM`** and **`CREATE INDEX CONCURRENTLY`**. For those the
fallback is direct-but-scoped grants on the apply account — **and this
path has NO Layer-3 (procedure) protection**: containment reverts to the
bypassable app-layer statement-type parser, which a compromised applier
holding the credential simply skips. Treat `enforcement: scoped-grant`
as a materially weaker tier. [threat model H8]

- PG 17+: grant **per-table** `MAINTAIN ON <table>` — **never the
  `pg_maintain` role**, which is all-tables and permits VACUUM
  FULL/CLUSTER/LOCK/REFRESH across the whole DB.
- **Forbid `VACUUM FULL` and `CLUSTER` action types entirely** (ACCESS
  EXCLUSIVE + full rewrite = availability DoS); allow only plain
  `VACUUM`/`ANALYZE`.
- `CREATE INDEX CONCURRENTLY`: scope `CREATE` to a **dedicated
  throwaway schema**, not an app schema; the statement-type check pins
  the action to exactly `CREATE INDEX CONCURRENTLY`.

This is a per-action decision recorded in the catalogue entry
(`enforcement: procedure | scoped-grant`). `scoped-grant` actions are
gated to a smaller, more-trusted set and — per the go-live checklist —
**must not be enabled for a prod target while relying on Layer 2 alone**.

## 6. Production wiring checklist

To be completed **per target database**, in order, before the first
real apply. The negative tests are the point — go-live is proven by
what the account *cannot* do.

- [ ] Two accounts created from `provisioning/` SQL: `dba_agent_ro`
      (read-only grants per spec §6), `dba_agent_apply` (hardened as
      above; correct profile/role settings verified with a query, not
      assumed).
- [ ] Action procedures deployed (`dba_actions` package / schema) with
      allowlist tables populated; owner account locked / NOLOGIN.
- [ ] **DB negative test battery run against the live account** and
      output attached to the go-live MR:
      `DROP TABLE` → refused by engine; direct `ALTER TABLESPACE` /
      `ANALYZE` (not via procedure) → refused; procedure call with
      out-of-cap size → refused; procedure call with **aggregate cap
      exceeded** (loop to max files/GB) → refused [H6]; procedure call
      with non-allowlisted identifier → refused; Oracle owner cannot
      authenticate and cannot `SELECT` from `SYS.USER$` [H7/M5]; RO
      account `SELECT` on `SYS.USER$` / `pg_authid` → refused [C3];
      connection from a non-runner host → refused; second concurrent
      session → refused; apply account has no DML on the audit table
      [M1].
- [ ] Applier negative tests green in CI: tampered `rendered_sql`
      refused; unknown target refused; expired action refused;
      precondition-not-met refused; **action target ≠ alert-source host
      → refused** [C4]; MR diff touching anything outside
      `actions/pending/` → pipeline fails [H1].
- [ ] **CI / network negative tests** (these were missing; they catch
      the most severe findings):
      non-DBA runs the manual apply job → refused [C1]; push to `main`
      by non-DBA → refused, and protected-tag create by non-DBA →
      refused [C1]; unmerged-branch / MR pipeline has **no** prod
      credential in its env (grep) [C1]; this apply job's env contains
      **only its own** target's credential, not other DBs' [H2]; the
      apply runner cannot reach any host but its target (port-scan test)
      and runs protected-ref pipelines only [C2]; the agent's GitLab
      token cannot run a manual job or download protected artifacts
      [H3]; `CI_JOB_TOKEN` allowlist minimal [M6].
- [ ] MR re-approval enforced on new commits (Premium approval rule) OR
      the applier pins and verifies the DBA-approved commit SHA [C1].
- [ ] Layer-3 procedure exists for every action type enabled on this
      prod target; go-live **refused** if any is `enforcement:
      scoped-grant` [H4/H8].
- [ ] Engine audit verified capturing the **DDL itself** (not just the
      package EXECUTE — Oracle definer-executed DDL needs its own policy)
      [M2]; audit table is append-only for the apply account [M1].
- [ ] Runner: ephemeral executor, digest-pinned applier image from an
      internal registry; applier never logs DSN/connection errors [M6].
- [ ] RO credential hardened like the apply account (connection limit,
      timeouts, pg_hba/listener scoping) and its real reach documented
      [H5/M3]; data-classification decision recorded for what DB content
      may leave to the Anthropic API [M10].
- [ ] Runner tag routing + `resource_group` serialization verified with
      two queued jobs.
- [ ] First real action executed on **staging**, end-to-end from alert
      → MR → merge → manual apply → audit → Slack, before prod is
      enabled for that action type.

## 7. Where this is enforced in the codebase

- Spec: `dba-agent-spec.md` §5.1 (template-only execution), §5.6
  (layers), §7 (audit).
- Task: `tasks/apply/runbook-apply-path.md` — deliverables include the
  procedures, the hardening SQL, and the negative test battery.
- The compose stack rehearses all of §6 against `gvenzl/oracle-free`
  and `postgres:16` before any of it is attempted for real.
