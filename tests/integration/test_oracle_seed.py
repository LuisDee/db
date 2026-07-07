"""Proves compose/oracle/init/*.sql against a real Oracle instance.

Not provable in this sandbox: there's no realistic non-container way to
run a real Oracle engine, and the testcontainers path here needs a
Docker daemon this environment doesn't have. The oracle_dsn fixture
(tests/integration/conftest.py) mounts compose/oracle/init/ into
gvenzl/oracle-free's own init-on-first-boot mechanism, so on a real
Docker host this proves the exact same SQL the compose stack ships.
"""

from __future__ import annotations

import oracledb
import pytest

pytestmark = pytest.mark.integration


def test_near_full_tablespace_seeded(oracle_dsn):
    with oracledb.connect(dsn=oracle_dsn, user="system", password="test") as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ROUND(100 * used.bytes / files.bytes, 1) AS pct_used "
            "FROM (SELECT SUM(bytes) bytes FROM dba_data_files "
            "      WHERE tablespace_name = 'USER_INDEX_04') files, "
            "     (SELECT SUM(bytes) bytes FROM dba_data_files df "
            "      WHERE tablespace_name = 'USER_INDEX_04' "
            "        AND df.file_id NOT IN ("
            "          SELECT file_id FROM dba_free_space "
            "          WHERE tablespace_name = 'USER_INDEX_04')) used"
        )
        (pct_used,) = cur.fetchone()
        # See compose/README.md's "check this first" note: the fill loop
        # targets ~90% but block-size/segment overhead were never
        # measured against a real instance until this test runs for real.
        assert 80 <= pct_used <= 99, f"expected a believable near-full tablespace, got {pct_used}%"
