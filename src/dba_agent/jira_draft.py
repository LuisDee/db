"""Ready-to-paste Jira ticket draft, built from an evidence bundle plus
an optional time-to-full estimate.

docs/dba-agent-direction.md decision 4: v1 ships a ticket *draft in the
Slack thread* -- title, body, evidence, ready to paste -- not a live
Jira API call (that's a v1.5 item, gated on credentials this repo
doesn't have). This module is that draft: pure string-building from
data already in hand, no I/O, no Jira SDK. `owner` names which system
holds the fix (`"infra"` for host/filesystem-level problems Postgres/
QuestDB queries alone cannot resolve, `"db"` for problems a DBA fixes
inside the database itself, e.g. archiving app.event_log or dropping an
unused index) -- the playbook synthesis step decides which one applies
per docs/dba-agent-spec.md §4; this module just renders whichever it's
told.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from dba_agent.capacity import CapacityEstimate
from dba_agent.executor import EvidenceBundle

_SUGGESTED_ACTION = {
    "infra": (
        "Suggested action (infra-owned): extend or add capacity to the "
        "underlying filesystem/volume, or confirm this is expected growth. "
        "This playbook cannot resolve host-level disk provisioning -- no "
        "SSH, no host access (spec principle 3)."
    ),
    "db": (
        "Suggested action (DB-owned): investigate the growth inside the "
        "database itself -- archive or partition-prune the offending "
        "table, vacuum/reindex if index bloat dominates, or check for a "
        "stuck replication slot inflating WAL. No filesystem change "
        "needed if the fix lands here."
    ),
}

_DEFAULT_SUGGESTED_ACTION = (
    "Suggested action: unspecified owner -- review the evidence below and "
    "route to infra (filesystem/volume) or the DB team (table/index/WAL) "
    "as appropriate."
)


@dataclass(frozen=True)
class JiraDraft:
    title: str
    body: str


def _format_timedelta(td: timedelta) -> str:
    total_seconds = td.total_seconds()
    if total_seconds <= 0:
        return "already at or past capacity"
    days = td.days
    hours = (td.seconds // 3600)
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
    minutes = (td.seconds % 3600) // 60
    if hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def _time_to_full_section(estimate: CapacityEstimate | None) -> str:
    if estimate is None:
        return "Time-to-full: not available -- insufficient history to fit a growth trend."
    if estimate.time_to_full is None:
        return (
            f"Time-to-full: not growing (or no meaningful growth) at the observed rate "
            f"({estimate.growth_per_second:.4f} units/sec) -- no ETA to report."
        )
    return (
        f"Time-to-full: approximately {_format_timedelta(estimate.time_to_full)} "
        f"at the observed growth rate ({estimate.growth_per_second:.4f} units/sec)."
    )


def _evidence_section(evidence: EvidenceBundle) -> str:
    if not evidence.results:
        return "Evidence: no queries were run."

    lines = []
    for result in evidence.results:
        lines.append(f"* {result.query_name}")
        if not result.succeeded:
            lines.append(f"    error: {result.error}")
            continue
        lines.append(f"    columns: {', '.join(result.columns)}")
        for row in result.rows:
            lines.append(f"    {row}")
    return "Evidence:\n" + "\n".join(lines)


def build_jira_draft(
    *,
    host: str,
    mountpoint: str,
    owner: str,
    evidence: EvidenceBundle,
    estimate: CapacityEstimate | None,
) -> JiraDraft:
    title = f"[{owner}] Disk space growth on {host}:{mountpoint}"

    suggested_action = _SUGGESTED_ACTION.get(owner, _DEFAULT_SUGGESTED_ACTION)

    body = "\n\n".join(
        [
            f"Filesystem disk-space alert for {host}:{mountpoint} (playbook: {evidence.playbook_key}).",
            _time_to_full_section(estimate),
            _evidence_section(evidence),
            suggested_action,
        ]
    )

    return JiraDraft(title=title, body=body)
