"""Check_MK REST API client for host-level facts (filesystem usage,
filesystem history) -- no SSH (spec principle 3: host facts come from
the Check_MK API, DB facts from read-only SQL).

UNVERIFIED against a live Check_MK instance -- there isn't one available
to this project yet (docs/dba-agent-spec.md open question 2: "Check_MK
API availability/version... and a read-only API user"). The request/
response shape here follows Check_MK's documented REST API 1.0 ("list
host services" + its unusual `Authorization: Bearer <user> <secret>`
header, space-separated within one token, per their public docs) as
closely as possible without a real site to confirm against. Expect the
query params, `extensions` field names, or auth header to need
adjustment the first time this runs for real -- that's exactly the
kind of thing tests/integration/ exists to catch once a real instance
is available, the same way Oracle/QuestDB are scaffolded but unproven
today.

`filesystem_history` (added for tasks/playbooks/playbook-disk-space.md's
time-to-full estimate) carries the same caveat, doubled: not only is
there no live instance to confirm the shape against, this project also
couldn't reach docs.checkmk.com or the Checkmk forum/knowledge-base from
this sandbox to read the REST API 1.0 "get a single metric" endpoint's
schema directly (egress blocked, same class of restriction that blocks
downloading QuestDB's binary -- see tests/integration/conftest.py). The
request shape here is a best-effort reconstruction from search-engine
summaries of that documentation; the response parsing assumes the
`start_time` + `step` + `curves[0].rrddata` encoding Check_MK's older
Web API `get_graph` action used, on the unconfirmed assumption the REST
successor kept a similar time-series shape. Treat this as the least
trustworthy piece of this module until proven against a real site.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol


class CheckMkError(Exception):
    pass


@dataclass(frozen=True)
class FilesystemUsage:
    host: str
    mountpoint: str
    used_percent: float
    size_bytes: int


class CheckMkClient(Protocol):
    def filesystem_usage(self, host: str) -> tuple[FilesystemUsage, ...]: ...
    def filesystem_history(
        self, host: str, mountpoint: str, hours: int
    ) -> tuple[tuple[datetime, float], ...]: ...


def _filesystem_query_url(base_url: str, host: str) -> str:
    query = json.dumps({"op": "~", "left": "description", "right": "Filesystem.*"})
    params = urllib.parse.urlencode({"query": query, "columns": "host_name,description,extensions"})
    return f"{base_url.rstrip('/')}/objects/host/{host}/collections/services?{params}"


def _parse_filesystem_response(host: str, payload: dict) -> tuple[FilesystemUsage, ...]:
    results = []
    for member in payload.get("value", []):
        ext = member.get("extensions", {})
        results.append(
            FilesystemUsage(
                host=host,
                mountpoint=ext.get("mountpoint", member.get("title", "unknown")),
                used_percent=float(ext.get("used_percent", 0.0)),
                size_bytes=int(ext.get("size_bytes", 0)),
            )
        )
    return tuple(results)


def _filesystem_history_query_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/domain-types/metric/actions/get/invoke"


def _filesystem_history_request_body(host: str, mountpoint: str, hours: int) -> dict:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return {
        "host_name": host,
        "service_description": f"Filesystem {mountpoint}",
        "type": "single_metric",
        "metric_id": "fs_used_percent",
        "time_range": {"start": start.isoformat(), "end": end.isoformat()},
    }


def _parse_filesystem_history_response(payload: dict) -> tuple[tuple[datetime, float], ...]:
    curves = payload.get("curves", [])
    if not curves:
        return ()

    start_time = payload.get("start_time", 0)
    step = payload.get("step", 60)
    rrddata = curves[0].get("rrddata", [])

    points = []
    for i, value in enumerate(rrddata):
        if value is None:
            continue  # RRD gap -- no sample for this slot, not a zero
        timestamp = datetime.fromtimestamp(start_time + i * step, tz=timezone.utc)
        points.append((timestamp, float(value)))
    return tuple(points)


class RealCheckMkClient:
    def __init__(self, base_url: str, username: str, secret: str) -> None:
        self._base_url = base_url
        self._username = username
        self._secret = secret

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._username} {self._secret}",
            "Accept": "application/json",
        }

    def filesystem_usage(self, host: str) -> tuple[FilesystemUsage, ...]:
        url = _filesystem_query_url(self._base_url, host)
        request = urllib.request.Request(url, headers=self._auth_headers())
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise CheckMkError(f"Check_MK API request for {host!r} failed: {exc}") from exc
        return _parse_filesystem_response(host, payload)

    def filesystem_history(
        self, host: str, mountpoint: str, hours: int
    ) -> tuple[tuple[datetime, float], ...]:
        # UNVERIFIED -- see module docstring and the caveat above
        # test_filesystem_history_query_url_targets_the_metric_get_action
        # in tests/test_checkmk.py. No live Check_MK instance available
        # to this project (docs/dba-agent-spec.md open question 2) to
        # confirm this request/response shape against.
        url = _filesystem_history_query_url(self._base_url)
        body = _filesystem_history_request_body(host, mountpoint, hours)
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise CheckMkError(
                f"Check_MK filesystem history request for {host!r}/{mountpoint!r} failed: {exc}"
            ) from exc
        return _parse_filesystem_history_response(payload)


@dataclass
class FakeCheckMkClient:
    responses: dict[str, tuple[FilesystemUsage, ...]]
    calls: list[str] = field(default_factory=list)
    history_responses: dict[tuple[str, str, int], tuple[tuple[datetime, float], ...]] = field(
        default_factory=dict
    )
    history_calls: list[tuple[str, str, int]] = field(default_factory=list)

    def filesystem_usage(self, host: str) -> tuple[FilesystemUsage, ...]:
        self.calls.append(host)
        if host not in self.responses:
            raise CheckMkError(f"no scripted response for host {host!r}")
        return self.responses[host]

    def filesystem_history(
        self, host: str, mountpoint: str, hours: int
    ) -> tuple[tuple[datetime, float], ...]:
        key = (host, mountpoint, hours)
        self.history_calls.append(key)
        if key not in self.history_responses:
            raise CheckMkError(
                f"no scripted history for host={host!r} mountpoint={mountpoint!r} hours={hours!r}"
            )
        return self.history_responses[key]
