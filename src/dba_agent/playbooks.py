from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Load-time defence in depth: a preset playbook query should never be
# write-shaped. This doesn't replace grant-based enforcement (the read
# identity has no write grants) -- it catches a bad playbook file
# before it's ever run against anything.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)


class PlaybookError(Exception):
    pass


@dataclass(frozen=True)
class PlaybookQuery:
    name: str
    sql: str
    redact_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Playbook:
    key: str
    queries: dict[str, tuple[PlaybookQuery, ...]] = field(default_factory=dict)
    notes: str = ""

    def queries_for(self, engine: str) -> tuple[PlaybookQuery, ...]:
        return self.queries.get(engine, ())


def load_playbook(path: Path) -> Playbook:
    if not path.exists():
        raise PlaybookError(f"playbook file not found: {path}")

    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise PlaybookError(f"playbook file must contain a YAML mapping: {path}")

    key = data.get("name")
    if not key:
        raise PlaybookError(f"playbook missing required 'name': {path}")

    raw_queries = data.get("engine_queries", {})
    if not isinstance(raw_queries, dict):
        raise PlaybookError(f"playbook '{key}' 'engine_queries' must be a mapping: {path}")

    queries: dict[str, tuple[PlaybookQuery, ...]] = {}
    for engine, items in raw_queries.items():
        if not isinstance(items, list):
            raise PlaybookError(f"playbook '{key}' engine '{engine}' queries must be a list")

        built: list[PlaybookQuery] = []
        for item in items:
            if not isinstance(item, dict) or "name" not in item or "sql" not in item:
                raise PlaybookError(
                    f"playbook '{key}' engine '{engine}' has a malformed query entry: {item!r}"
                )

            sql = item["sql"]
            match = _FORBIDDEN_KEYWORDS.search(sql)
            if match:
                raise PlaybookError(
                    f"playbook '{key}' engine '{engine}' query '{item['name']}' contains "
                    f"forbidden keyword '{match.group(0)}' -- playbooks are read-only by design"
                )

            built.append(
                PlaybookQuery(
                    name=item["name"],
                    sql=sql,
                    redact_columns=tuple(item.get("redact_columns", ())),
                )
            )
        queries[engine] = tuple(built)

    return Playbook(key=key, queries=queries, notes=data.get("notes", ""))
