-- Fills USER_INDEX_04 (created in 01_tablespace_and_user.sql) to ~90%
-- used, computed from actual dba_data_files/dba_free_space bytes rather
-- than an assumed row-size -- robust to block size / segment overhead
-- differences. Naturally idempotent: if the tablespace is already at or
-- above the target, the loop exits immediately on the first check, so
-- `make seed` re-runs are a no-op here.
ALTER SESSION SET CONTAINER = FREEPDB1;

DECLARE
    v_total     NUMBER;
    v_free      NUMBER;
    v_used_pct  NUMBER := 0;
    v_batch     PLS_INTEGER := 200;
    v_max_loops PLS_INTEGER := 2000; -- safety bound, never spin forever
    v_loops     PLS_INTEGER := 0;
BEGIN
    SELECT SUM(bytes) INTO v_total
      FROM dba_data_files
     WHERE tablespace_name = 'USER_INDEX_04';

    LOOP
        SELECT NVL(SUM(bytes), 0) INTO v_free
          FROM dba_free_space
         WHERE tablespace_name = 'USER_INDEX_04';

        v_used_pct := (v_total - v_free) / v_total;
        EXIT WHEN v_used_pct >= 0.90 OR v_loops >= v_max_loops;
        v_loops := v_loops + 1;

        BEGIN
            FOR i IN 1..v_batch LOOP
                INSERT INTO dbaagent_seed.tablespace_filler (payload)
                VALUES (RPAD('x', 2000, 'x'));
            END LOOP;
            COMMIT;
        EXCEPTION
            WHEN OTHERS THEN
                -- ORA-01653/ORA-01688: unable to extend table/index in a
                -- tablespace with no autoextend room left. That's exactly
                -- "near full" from the other direction (fully full) --
                -- stop cleanly rather than fail the init script.
                ROLLBACK;
                EXIT;
        END;
    END LOOP;

    SELECT NVL(SUM(bytes), 0) INTO v_free
      FROM dba_free_space
     WHERE tablespace_name = 'USER_INDEX_04';
    v_used_pct := (v_total - v_free) / v_total;
    DBMS_OUTPUT.PUT_LINE('USER_INDEX_04 used_pct=' || ROUND(v_used_pct * 100, 1) || '%');
END;
/
