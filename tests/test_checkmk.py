import pytest

from dba_agent.checkmk import (
    CheckMkError,
    FakeCheckMkClient,
    FilesystemUsage,
    _filesystem_query_url,
    _parse_filesystem_response,
)


def test_filesystem_query_url_targets_the_host_services_collection():
    url = _filesystem_query_url("https://checkmk.example.com/mysite/check_mk/api/1.0", "uk01vdb301")
    assert url.startswith(
        "https://checkmk.example.com/mysite/check_mk/api/1.0/objects/host/uk01vdb301/collections/services?"
    )
    assert "Filesystem" in url


def test_parse_filesystem_response_extracts_expected_fields():
    payload = {
        "value": [
            {
                "title": "Filesystem /quest",
                "extensions": {"mountpoint": "/quest", "used_percent": 91.4, "size_bytes": 500_000_000_000},
            },
            {
                "title": "Filesystem /local",
                "extensions": {"mountpoint": "/local", "used_percent": 42.0, "size_bytes": 100_000_000_000},
            },
        ]
    }

    results = _parse_filesystem_response("uk01vdb301", payload)

    assert results == (
        FilesystemUsage(host="uk01vdb301", mountpoint="/quest", used_percent=91.4, size_bytes=500_000_000_000),
        FilesystemUsage(host="uk01vdb301", mountpoint="/local", used_percent=42.0, size_bytes=100_000_000_000),
    )


def test_parse_filesystem_response_handles_empty_result():
    assert _parse_filesystem_response("unknown-host", {"value": []}) == ()


def test_parse_filesystem_response_falls_back_to_title_when_mountpoint_missing():
    payload = {"value": [{"title": "Filesystem /weird", "extensions": {}}]}
    results = _parse_filesystem_response("host1", payload)
    assert results[0].mountpoint == "Filesystem /weird"
    assert results[0].used_percent == 0.0


def test_fake_checkmk_client_returns_scripted_response():
    usage = (FilesystemUsage(host="h1", mountpoint="/quest", used_percent=90.0, size_bytes=1_000),)
    client = FakeCheckMkClient(responses={"h1": usage})

    assert client.filesystem_usage("h1") == usage
    assert client.calls == ["h1"]


def test_fake_checkmk_client_raises_for_unscripted_host():
    client = FakeCheckMkClient(responses={})
    with pytest.raises(CheckMkError, match="no scripted response"):
        client.filesystem_usage("unknown-host")
