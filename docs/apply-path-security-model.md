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
-- privileges and the package (definer's rights).
CREATE USER dba_actions_owner IDENTIFIED BY "..." ACCOUNT LOCK;
GRANT CREATE SESSION TO dba_actions_owner;   -- needed to compile; keep locked
GRANT ALTER TABLESPACE TO dba_actions_owner; -- the ONE privilege this action needs

-- Allowlist lives in a table the owner controls, not in code.
CREATE TABLE dba_actions_owner.tablespace_allowlist (
  tablespace_name VARCHAR2(30) PRIMARY KEY
);

CREATE OR REPLACE PACKAGE dba_actions_owner.dba_actions AS
  PROCEDURE add_datafile(p_tablespace IN VARCHAR2, p_size_gb IN PLS_INTEGER);
END dba_actions;
/
CREATE OR REPLACE PACKAGE BODY dba_actions_owner.dba_actions AS
  PROCEDURE add_datafile(p_tablespace IN VARCHAR2, p_size_gb IN PLS_INTEGER) IS
    l_ts dba_tablespaces.tablespace_name%TYPE;
  BEGIN
    -- Caps and validation INSIDE the engine:
    IF p_size_gb NOT BETWEEN 1 AND 32 THEN
      RAISE_APPLICATION_ERROR(-20001, 'size_gb out of policy (1..32)');
    END IF;
    SELECT t.tablespace_name INTO l_ts        -- must exist AND be allowlisted
      FROM dba_tablespaces t
      JOIN dba_actions_owner.tablespace_allowlist a
        ON a.tablespace_name = t.tablespace_name
     WHERE t.tablespace_name = UPPER(p_tablespace);
    -- DBMS_ASSERT guards injection through the identifier:
    EXECUTE IMMEDIATE 'ALTER TABLESPACE '
      || DBMS_ASSERT.SIMPLE_SQL_NAME(l_ts)
      || ' ADD DATAFILE SIZE ' || p_size_gb
      || 'G AUTOEXTEND ON NEXT 1G MAXSIZE 32G';
    -- (audit insert here — see spec §7 layer 3)
  END add_datafile;
END dba_actions;
/

-- The apply account: EXECUTE on the package and NOTHING else.
CREATE USER dba_agent_apply IDENTIFIED BY "..."
  PROFILE dba_agent_profile;               -- SESSIONS_PER_USER 1, connect limits
GRANT CREATE SESSION TO dba_agent_apply;
GRANT EXECUTE ON dba_actions_owner.dba_actions TO dba_agent_apply;
-- No ALTER TABLESPACE. No DBA. No SELECT on anything.

-- Engine-enforced audit on everything this account does (included in SE):
CREATE AUDIT POLICY dba_agent_apply_pol ACTIONS ALL;
AUDIT POLICY dba_agent_apply_pol BY dba_agent_apply;
```

Definer's rights means the package runs with `dba_actions_owner`'s
privileges; the caller never holds them. The owner account stays
`ACCOUNT LOCK`ed — it is a privilege container, not a login.

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
  against attacker-controlled schemas. Every action function must set
  `SET search_path = pg_catalog, pg_temp` in its definition (this is
  the official guidance in the CREATE FUNCTION docs).

```sql
-- Privilege container (NOLOGIN — the PG analogue of ACCOUNT LOCK):
CREATE ROLE dba_actions_owner NOLOGIN;
-- Give it exactly what the action needs. For ANALYZE that means
-- maintenance rights on the target tables: on PG 17+ grant MAINTAIN
-- (or pg_maintain); on <=16, make it the table owner via role grant.
GRANT pg_maintain TO dba_actions_owner;          -- PG 17+

CREATE SCHEMA dba_actions AUTHORIZATION dba_actions_owner;

CREATE TABLE dba_actions.table_allowlist (
  schema_name text NOT NULL,
  table_name  text NOT NULL,
  PRIMARY KEY (schema_name, table_name)
);

CREATE OR REPLACE FUNCTION dba_actions.analyze_table(p_schema text, p_table text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp        -- footgun 2 handled
AS $$
BEGIN
  -- Must exist AND be allowlisted — validated INSIDE the engine:
  PERFORM 1 FROM dba_actions.table_allowlist a
   WHERE a.schema_name = p_schema AND a.table_name = p_table;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'table %.% not in action allowlist', p_schema, p_table;
  END IF;
  PERFORM p_schema::text FROM pg_catalog.pg_tables
   WHERE schemaname = p_schema AND tablename = p_table;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'table %.% does not exist', p_schema, p_table;
  END IF;
  -- %I quotes identifiers — no string-splicing injection surface:
  EXECUTE format('ANALYZE %I.%I', p_schema, p_table);
  -- (audit insert here — see spec §7 layer 3)
END $$;
ALTER FUNCTION dba_actions.analyze_table(text, text) OWNER TO dba_actions_owner;

REVOKE ALL ON FUNCTION dba_actions.analyze_table(text, text) FROM PUBLIC;  -- footgun 1

-- The apply account: EXECUTE on action functions and NOTHING else.
CREATE ROLE dba_agent_apply LOGIN PASSWORD '...'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  CONNECTION LIMIT 1;
ALTER ROLE dba_agent_apply SET statement_timeout = '5min';
ALTER ROLE dba_agent_apply SET lock_timeout = '10s';
ALTER ROLE dba_agent_apply SET log_statement = 'all';   -- engine-enforced audit
GRANT USAGE ON SCHEMA dba_actions TO dba_agent_apply;
GRANT EXECUTE ON FUNCTION dba_actions.analyze_table(text, text) TO dba_agent_apply;
```

Plus `pg_hba.conf`: the `dba_agent_apply` role only accepts connections
from the CI-runner segment, TLS required.

### Postgres caveat — what can't be wrapped in a function

A few maintenance commands refuse to run inside a function/transaction
context: **`VACUUM`** and **`CREATE INDEX CONCURRENTLY`** are the ones
that matter. For those action types the fallback is direct-but-scoped
grants on the apply account itself — Postgres scopes these well:

- PG 17+: the `MAINTAIN` privilege / `pg_maintain` role covers VACUUM,
  ANALYZE, REINDEX, CLUSTER, REFRESH MATERIALIZED VIEW — grant that
  (per table if desired) instead of ownership.
- `CREATE INDEX CONCURRENTLY`: needs CREATE on the schema + the
  applier's layer-2 gates carry more of the weight; the statement-type
  check pins the action to exactly `CREATE INDEX CONCURRENTLY`.

This is a per-action decision recorded in the catalogue entry
(`enforcement: procedure | scoped-grant`), so the exceptions are
explicit and reviewed, not accidental.

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
- [ ] **Negative test battery run against the live account** and
      output attached to the go-live MR:
      `DROP TABLE` → refused by engine; direct `ALTER TABLESPACE` /
      `ANALYZE` (not via procedure) → refused; procedure call with
      out-of-cap size → refused; procedure call with non-allowlisted
      identifier → refused; connection from a non-runner host →
      refused; second concurrent session → refused.
- [ ] Applier negative tests green in CI: tampered `rendered_sql`
      refused; unknown target refused; expired action refused;
      precondition-not-met refused.
- [ ] Credentials stored as protected+masked GitLab variables scoped to
      the environment; **verified absent** in a non-protected-branch
      pipeline (run one and grep the env).
- [ ] Engine audit enabled and verified capturing (Oracle unified audit
      policy on the account; PG `log_statement` on the role) — run one
      procedure call, find it in the audit trail.
- [ ] `dba_agent_audit` table present; a staging apply shows
      write-ahead + result rows.
- [ ] Runner tag routing confirmed: the apply job for this endpoint
      lands on a runner that can reach it, and `resource_group`
      serialization verified with two queued jobs.
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
