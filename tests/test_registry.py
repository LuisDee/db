from pathlib import Path

import pytest

from dba_agent.registry import (
    AmbiguousAliasError,
    CredentialRefError,
    Endpoint,
    RegistryError,
    UnknownEndpointError,
    load_registry,
)

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


def test_resolve_by_exact_top_level_key():
    registry = load_registry(FIXTURES / "registry.yaml")

    endpoint = registry.resolve("dev-pg")

    assert endpoint.key == "dev-pg"
    assert endpoint.engine == "postgres"


def test_resolve_by_db_name_alias():
    registry = load_registry(FIXTURES / "registry.yaml")

    endpoint = registry.resolve("boproddb")

    assert endpoint.key == "boproddb-prod"


def test_resolve_by_hostname_alias():
    registry = load_registry(FIXTURES / "registry.yaml")

    endpoint = registry.resolve("uk01vdb301")

    assert endpoint.key == "boproddb-prod"


def test_resolve_unknown_name_raises_unknown_endpoint_error():
    registry = load_registry(FIXTURES / "registry.yaml")

    with pytest.raises(UnknownEndpointError, match="nope-does-not-exist"):
        registry.resolve("nope-does-not-exist")


def test_resolve_credential_reads_from_env_mapping():
    registry = load_registry(FIXTURES / "registry.yaml")
    endpoint = registry.resolve("boproddb-prod")

    value = endpoint.resolve_credential(env={"ORACLE_RO_BOPRODDB": "hunter2"})

    assert value == "hunter2"


def test_resolve_credential_missing_env_var_raises():
    registry = load_registry(FIXTURES / "registry.yaml")
    endpoint = registry.resolve("boproddb-prod")

    with pytest.raises(CredentialRefError, match="ORACLE_RO_BOPRODDB"):
        endpoint.resolve_credential(env={})


def test_endpoint_repr_never_contains_resolved_secret():
    registry = load_registry(FIXTURES / "registry.yaml")
    endpoint = registry.resolve("boproddb-prod")

    endpoint.resolve_credential(env={"ORACLE_RO_BOPRODDB": "super-secret-value"})

    assert "super-secret-value" not in repr(endpoint)


def test_ambiguous_alias_shared_by_two_endpoints_raises_at_load_time(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "db-one:\n"
        "  engine: postgres\n"
        "  dsn: db-one:5432/app\n"
        "  credential_ref: PG_RO_ONE\n"
        "  tier: prod\n"
        "  aliases: [shared-alias]\n"
        "db-two:\n"
        "  engine: postgres\n"
        "  dsn: db-two:5432/app\n"
        "  credential_ref: PG_RO_TWO\n"
        "  tier: staging\n"
        "  aliases: [shared-alias]\n"
    )

    with pytest.raises(AmbiguousAliasError, match="shared-alias"):
        load_registry(bad)


def test_alias_colliding_with_another_top_level_key_raises_at_load_time(tmp_path: Path):
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "db-one:\n"
        "  engine: postgres\n"
        "  dsn: db-one:5432/app\n"
        "  credential_ref: PG_RO_ONE\n"
        "  tier: prod\n"
        "  aliases: [db-two]\n"
        "db-two:\n"
        "  engine: postgres\n"
        "  dsn: db-two:5432/app\n"
        "  credential_ref: PG_RO_TWO\n"
        "  tier: staging\n"
    )

    with pytest.raises(AmbiguousAliasError, match="db-two"):
        load_registry(bad)
