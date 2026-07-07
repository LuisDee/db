from datetime import datetime, timezone

import pytest

from dba_agent.checkmk import (
    CheckMkError,
    FakeCheckMkClient,
    FilesystemUsage,
    _filesystem_history_request_body,
    _filesystem_history_query_url,
    _filesystem_query_url,
    _parse_filesystem_history_response,
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


# --- filesystem_history ------------------------------------------------
#
# UNVERIFIED against a live Check_MK instance, same caveat as the module
# docstring and filesystem_usage above (spec open question 2) -- there
# isn't one available to this project. The request/response shape below
# follows Check_MK's REST API 1.0 "get a single metric" endpoint
# (Werk #13955: "/domain-types/metric/actions/*/invoke") as closely as
# this sandbox's blocked egress to docs.checkmk.com/checkmk.atlassian.net
# allows -- confirmed via web search summaries only, never against the
# actual OpenAPI schema. The response parsing assumes the historical
# `start_time` + `step` + `curves[0].rrddata` shape Check_MK's older
# get_graph Web API used, on the (unconfirmed) assumption the REST
# endpoint kept a similar time-series encoding. Expect this to need
# adjustment the first time it runs against a real site.


def test_filesystem_history_query_url_targets_the_metric_get_action():
    url = _filesystem_history_query_url("https://checkmk.example.com/mysite/check_mk/api/1.0")
    assert url == "https://checkmk.example.com/mysite/check_mk/api/1.0/domain-types/metric/actions/get/invoke"


def test_filesystem_history_request_body_shape():
    body = _filesystem_history_request_body("uk01vdb301", "/quest", hours=24)

    assert body["host_name"] == "uk01vdb301"
    assert "quest" in body["service_description"]
    assert body["metric_id"] == "fs_used_percent"
    assert body["time_range"]["start"] < body["time_range"]["end"]
    # roughly a 24h window (allow slack for wall-clock jitter in the test)
    start = datetime.fromisoformat(body["time_range"]["start"])
    end = datetime.fromisoformat(body["time_range"]["end"])
    assert (end - start).total_seconds() == pytest.approx(24 * 3600, abs=5)


def test_parse_filesystem_history_response_builds_timestamped_points():
    payload = {
        "start_time": 1_800_000_000,
        "step": 60,
        "curves": [{"title": "used_percent", "rrddata": [10.0, 20.0, 30.0]}],
    }

    points = _parse_filesystem_history_response(payload)

    assert len(points) == 3
    assert points[0][1] == 10.0
    assert points[1][1] == 20.0
    assert points[2][1] == 30.0
    assert points[1][0] - points[0][0] == points[2][0] - points[1][0]  # evenly spaced by `step`
    assert points[0][0] == datetime.fromtimestamp(1_800_000_000, tz=timezone.utc)


def test_parse_filesystem_history_response_skips_null_gaps():
    payload = {"start_time": 1_800_000_000, "step": 60, "curves": [{"rrddata": [10.0, None, 30.0]}]}

    points = _parse_filesystem_history_response(payload)

    assert [value for _, value in points] == [10.0, 30.0]


def test_parse_filesystem_history_response_handles_no_curves():
    assert _parse_filesystem_history_response({"start_time": 0, "step": 60, "curves": []}) == ()


def test_fake_checkmk_client_filesystem_history_returns_scripted_series():
    series = ((datetime(2026, 7, 1, tzinfo=timezone.utc), 42.0),)
    client = FakeCheckMkClient(responses={}, history_responses={("h1", "/quest", 24): series})

    assert client.filesystem_history("h1", "/quest", hours=24) == series
    assert client.history_calls == [("h1", "/quest", 24)]


def test_fake_checkmk_client_filesystem_history_raises_for_unscripted_request():
    client = FakeCheckMkClient(responses={})
    with pytest.raises(CheckMkError, match="no scripted history"):
        client.filesystem_history("h1", "/quest", hours=24)
