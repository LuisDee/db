"""Check_MK REST API client for host-level facts (filesystem usage) --
no SSH (spec principle 3: host facts come from the Check_MK API, DB
facts from read-only SQL).

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
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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


class RealCheckMkClient:
    def __init__(self, base_url: str, username: str, secret: str) -> None:
        self._base_url = base_url
        self._username = username
        self._secret = secret

    def filesystem_usage(self, host: str) -> tuple[FilesystemUsage, ...]:
        url = _filesystem_query_url(self._base_url, host)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._username} {self._secret}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise CheckMkError(f"Check_MK API request for {host!r} failed: {exc}") from exc
        return _parse_filesystem_response(host, payload)


@dataclass
class FakeCheckMkClient:
    responses: dict[str, tuple[FilesystemUsage, ...]]
    calls: list[str] = field(default_factory=list)

    def filesystem_usage(self, host: str) -> tuple[FilesystemUsage, ...]:
        self.calls.append(host)
        if host not in self.responses:
            raise CheckMkError(f"no scripted response for host {host!r}")
        return self.responses[host]
