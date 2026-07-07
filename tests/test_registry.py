from pathlib import Path

import pytest

from dba_agent.registry import Endpoint, RegistryError, load_registry

FIXTURES = Path(__file__).parent / "fixtures"


def test_loads_valid_registry():
    registry = load_registry(FIXTURES / "registry.yaml")

    prod = registry.endpoints["boproddb-prod"]
    assert prod == Endpoint(
        key="boproddb-prod",
        engine="oracle",
        dsn="boproddb-prod.internal:1521/BOPROD",
        credential_ref="ORACLE_RO_BOPRODDB",
        tier="prod",
        aliases=("boproddb", "uk01vdb301"),
    )


def test_missing_registry_file_raises():
    with pytest.raises(RegistryError, match="not found"):
        load_registry(FIXTURES / "does-not-exist.yaml")


def test_non_mapping_registry_raises(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text("- just\n- a\n- list\n")

    with pytest.raises(RegistryError, match="mapping"):
        load_registry(bad)


def test_missing_required_field_raises(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "boproddb-prod:\n"
        "  engine: oracle\n"
        "  dsn: boproddb-prod.internal:1521/BOPROD\n"
        "  tier: prod\n"
    )

    with pytest.raises(RegistryError, match="credential_ref"):
        load_registry(bad)


def test_unknown_engine_raises(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "some-db:\n"
        "  engine: mysql\n"
        "  dsn: some-db:3306/app\n"
        "  credential_ref: MYSQL_RO_SOMEDB\n"
        "  tier: prod\n"
    )

    with pytest.raises(RegistryError, match="engine"):
        load_registry(bad)


def test_duplicate_top_level_key_raises(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "boproddb-prod:\n"
        "  engine: oracle\n"
        "  dsn: a\n"
        "  credential_ref: A_REF\n"
        "  tier: prod\n"
        "boproddb-prod:\n"
        "  engine: oracle\n"
        "  dsn: b\n"
        "  credential_ref: B_REF\n"
        "  tier: prod\n"
    )

    with pytest.raises(RegistryError, match="duplicate"):
        load_registry(bad)
