-- Near-full tablespace scenario for tasks/playbooks/playbook-tablespace-usage.md
-- (the original motivating case: "USER_INDEX_04 near full").
--
-- Runs as SYS against the FREE root container (that's how
-- /container-entrypoint-initdb.d/*.sql scripts are executed by the
-- gvenzl/oracle-free image). The ALTER SESSION SET CONTAINER line
-- switches into the FREEPDB1 pluggable database, where the seed schema
-- lives. If this file is instead run via `make seed` connected directly
-- to FREEPDB1 (sqlplus .../FREEPDB1), the ALTER SESSION is a no-op
-- (setting the current container to itself), so the same file works
-- both as a first-boot init script and as a re-seed script.
--
-- License-clean: plain DDL/DML against dba_data_files / dba_free_space,
-- no AWR/ASH/dba_hist_* (Diagnostics Pack is EE-only -- see README.md
-- and docs/dba-agent-spec.md §6).
--
-- Datafile is capped (no autoextend) at 20M on purpose -- "near full"
-- doesn't need gigabytes, just a small ceiling. Idempotent: re-running
-- against an already-seeded database skips tablespace/user creation
-- (caught as "already exists") rather than failing `make seed`.
ALTER SESSION SET CONTAINER = FREEPDB1;

DECLARE
    v_dir  VARCHAR2(500);
    v_file VARCHAR2(600);
BEGIN
    -- Reuse the directory of an existing datafile so this works
    -- regardless of the exact oradata path the image lays out.
    SELECT regexp_replace(file_name, '[^/\]+$', '')
      INTO v_dir
      FROM dba_data_files
     WHERE tablespace_name = 'USERS'
       AND rownum = 1;

    v_file := v_dir || 'user_index_04_01.dbf';

    BEGIN
        EXECUTE IMMEDIATE
            'CREATE TABLESPACE USER_INDEX_04 DATAFILE ''' || v_file || '''' ||
            ' SIZE 20M AUTOEXTEND OFF' ||
            ' EXTENT MANAGEMENT LOCAL SEGMENT SPACE MANAGEMENT AUTO';
        DBMS_OUTPUT.PUT_LINE('created tablespace USER_INDEX_04 at ' || v_file);
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLCODE = -1543 THEN -- ORA-01543: tablespace already exists
                DBMS_OUTPUT.PUT_LINE('tablespace USER_INDEX_04 already exists, skipping');
            ELSE
                RAISE;
            END IF;
    END;
END;
/

BEGIN
    EXECUTE IMMEDIATE
        'CREATE USER dbaagent_seed IDENTIFIED BY "DevOnly_Seed_Pw1"' ||
        ' DEFAULT TABLESPACE USER_INDEX_04 QUOTA UNLIMITED ON USER_INDEX_04';
    EXECUTE IMMEDIATE 'GRANT CREATE SESSION, CREATE TABLE TO dbaagent_seed';
    DBMS_OUTPUT.PUT_LINE('created user dbaagent_seed');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE = -1920 THEN -- ORA-01920: user name conflicts with another user or role
            DBMS_OUTPUT.PUT_LINE('user dbaagent_seed already exists, skipping');
        ELSE
            RAISE;
        END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE
        'CREATE TABLE dbaagent_seed.tablespace_filler (' ||
        '  id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ' ||
        '  payload VARCHAR2(2000)' ||
        ') TABLESPACE USER_INDEX_04';
    DBMS_OUTPUT.PUT_LINE('created table dbaagent_seed.tablespace_filler');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE = -955 THEN -- ORA-00955: name is already used by an existing object
            DBMS_OUTPUT.PUT_LINE('table dbaagent_seed.tablespace_filler already exists, skipping');
        ELSE
            RAISE;
        END IF;
END;
/
