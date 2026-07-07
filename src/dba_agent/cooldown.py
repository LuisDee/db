"""Fingerprint dedup/cooldown and per-day LLM budget for triage
(docs/dba-agent-spec.md §4 "Dedup/cooldown", tasks/triage/dedup-cooldown.md).

Why this exists (docs/dba-agent-direction.md's alert inventory): 34% of
real channel volume is QuestDB health-check flapping. A flapping check
going CRITICAL -> OK -> CRITICAL is one underlying problem, not a new
one on every state flip -- classifier.fingerprint() already collides
those events to the same key by excluding severity (see that module's
docstring). This module is what actually *acts* on that collision: the
first occurrence of a fingerprint gets a full diagnosis; repeats within
a cooldown window get, at most, a counter update; nothing here posts to
Slack itself (no listener wiring exists yet -- tasks/poc/e2e-demo.md's
job) -- the caller does that with the `CooldownDecision` this module
hands back.

Persistence is deliberately real SQLite (stdlib `sqlite3`), not an
in-memory dict: this is the agent's own internal bookkeeping (distinct
from, and never sharing a file or schema with, the target databases it
monitors or the sibling diagnosis-synthesis task's storage), and it
must survive a process restart -- both the in-flight marker (so a crash
mid-investigation can't let a second run start against the same
fingerprint after restart) and the daily LLM-call counter (a restart
must not silently reset today's spend) depend on that.

Security note (docs/security-threat-model.md H11, M9): an attacker who
can post into the alert channel could vary fingerprints to exhaust the
daily LLM budget (spend/DoS -- M9), or pre-seed a colliding fingerprint
to force a genuine CRITICAL into cooldown (targeted blinding -- H11).
This module does not solve fingerprint-collision-resistance itself
(that's tasks/security/threat-model-remediation.md); what it does do,
per M9's explicit remediation ("make budget-exhaustion behavior
explicit and alerting, not silent"), is make the daily budget a real,
persisted, enforced limit and log loudly -- every refusal, not just the
first -- once it's hit.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("dba_agent")

# Default location for the agent's own bookkeeping store. Always passed
# explicitly by the caller -- CooldownStore.__init__ has no default
# argument for this (an adversarial review caught an earlier version
# that did, contradicting this very comment) -- so tests can point at
# tmp_path and production can point at a real persistent volume; see
# config.py for the same explicit-injection convention used elsewhere
# in this repo. DEFAULT_DB_PATH is a suggested value for callers to
# pass explicitly, not a signature default.
DEFAULT_DB_PATH = Path("var/cooldown.sqlite3")

# --- Cooldown windows --------------------------------------------------
#
# Default: 30 minutes. Reasoning -- the three real playbooked classes
# (filesystem disk-space, standby replication lag, tablespace usage;
# docs/dba-agent-direction.md's inventory) describe conditions that
# don't meaningfully change on a sub-30-minute timescale (a filesystem
# doesn't fill and drain in 10 minutes), so re-diagnosing the same
# fingerprint inside that window would just re-confirm the same
# evidence at LLM cost for no new information. 30 minutes is also long
# enough to cover the walk from "alert fires" to "Jira draft posted"
# without a second alert on the same underlying condition landing a
# competing diagnosis in the same thread.
DEFAULT_COOLDOWN = timedelta(minutes=30)

# Per-class overrides. questdb-health-flap gets a *shorter* window
# (5 minutes) than the default -- deliberate, not an oversight, and
# worth spelling out because it looks backwards at first glance (why
# would the noisiest class get *less* suppression?):
#
# 1. The durable fix for this class is a one-time, out-of-band RCA and
#    suppression at the Check_MK layer (docs/dba-agent-direction.md
#    "Alert hygiene" item 1: "not a per-alert-triage problem -- a
#    fix-it-once RCA problem"). This module is a safety net while that
#    lands, not the mechanism meant to carry all the suppression
#    weight for a class already flagged for a source-level fix.
# 2. Five minutes is still comfortably longer than an actual flap cycle
#    (a health check's own check interval, on the order of a minute or
#    two), so back-to-back flaps inside one burst still collapse into
#    one diagnosis plus cheap counter updates -- the noise-discipline
#    goal (docs/dba-agent-spec.md §4) is still met.
# 3. QuestDB is called out as "operationally a concern *today*"
#    (direction doc), not purely historical noise -- if the pattern
#    ever turns into a genuine sustained failure rather than a flap,
#    a shorter window means the agent notices and re-diagnoses within
#    5 minutes instead of staying silent for up to 30 on a live
#    production check.
DEFAULT_CLASS_COOLDOWNS: dict[str, timedelta] = {
    "questdb-health-flap": timedelta(minutes=5),
}

# In-flight staleness: how long an "in flight" marker is honoured
# before it's treated as abandoned (crashed run) and reclaimed. Chosen
# well above the read-path's own per-query timeout
# (executor.DEFAULT_QUERY_TIMEOUT_SECONDS = 10s, and a playbook runs a
# handful of queries plus at least one LLM synthesis call) so a run
# that is merely slow is never falsely reclaimed out from under itself,
# while a genuinely crashed run doesn't block its fingerprint forever.
DEFAULT_IN_FLIGHT_STALE_AFTER = timedelta(minutes=20)

# Daily LLM call budget. Reasoning -- the alert inventory
# (docs/dba-agent-direction.md) observes ~6 alerts/day in steady state,
# and a full triage of one fresh fingerprint costs a small, bounded
# number of LLM calls (classify, then synthesis; a couple more if a
# playbook's evidence needs interpretation). 200/day gives roughly an
# order of magnitude of headroom over steady-state volume -- enough to
# absorb a genuine alert storm (many distinct fingerprints, all
# legitimately fresh) without the very first busy day tripping the
# guard, while still bounding worst-case spend to a fixed, known
# number regardless of how adversarial or noisy the channel gets.
DEFAULT_DAILY_LLM_BUDGET = 200

_ACTION_DIAGNOSE = "diagnose"
_ACTION_COOLDOWN = "cooldown"
_ACTION_IN_FLIGHT = "in_flight"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat()


def _parse(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _day_key(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class CooldownDecision:
    """What the caller should do about one classified alert.

    action:
      - "diagnose"  -- fresh (never seen, or cooldown expired, or a
        stale in-flight marker was just reclaimed). Caller should call
        `start_diagnosis()` immediately, run the playbook, then call
        `mark_complete()`.
      - "cooldown"  -- a repeat within the fingerprint's cooldown
        window. Caller does *not* run a fresh diagnosis; at most, uses
        `repeat_count` to update a counter on the existing thread.
      - "in_flight" -- another (possibly crashed-and-not-yet-stale) run
        is still marked in flight for this fingerprint. Caller does
        nothing further.
    """

    fingerprint: str
    action: str
    repeat_count: int
    window: timedelta

    @property
    def should_diagnose(self) -> bool:
        return self.action == _ACTION_DIAGNOSE


class CooldownStore:
    """SQLite-backed fingerprint cooldown, in-flight marker, and daily
    LLM budget. One instance per process; safe to construct fresh
    against the same file after a restart (that's the crash-recovery
    contract the in-flight marker exists for).
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        default_cooldown: timedelta = DEFAULT_COOLDOWN,
        class_cooldowns: dict[str, timedelta] | None = None,
        in_flight_stale_after: timedelta = DEFAULT_IN_FLIGHT_STALE_AFTER,
        daily_llm_budget: int = DEFAULT_DAILY_LLM_BUDGET,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._default_cooldown = default_cooldown
        self._class_cooldowns = {**DEFAULT_CLASS_COOLDOWNS, **(class_cooldowns or {})}
        self._in_flight_stale_after = in_flight_stale_after
        self._daily_llm_budget = daily_llm_budget
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fingerprint_state (
                fingerprint TEXT PRIMARY KEY,
                alert_class TEXT NOT NULL,
                last_diagnosed_at TEXT NOT NULL,
                repeat_count INTEGER NOT NULL DEFAULT 0,
                in_flight_since TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_budget (
                day TEXT PRIMARY KEY,
                consumed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> CooldownStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- cooldown window -------------------------------------------------

    def cooldown_for(self, alert_class: str) -> timedelta:
        return self._class_cooldowns.get(alert_class, self._default_cooldown)

    def decide(
        self, fingerprint: str, alert_class: str, now: datetime | None = None
    ) -> CooldownDecision:
        """Decide what to do with one classified alert. Never mutates
        `last_diagnosed_at`/`in_flight_since` itself for the "diagnose"
        outcome -- the caller commits to that by calling
        `start_diagnosis()` next. Does persist the incremented repeat
        counter for the "cooldown" outcome, since that counter *is* the
        thing this call is answering the alert with.
        """
        now = now or _utcnow()
        window = self.cooldown_for(alert_class)

        row = self._conn.execute(
            "SELECT last_diagnosed_at, repeat_count, in_flight_since "
            "FROM fingerprint_state WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()

        if row is None:
            return CooldownDecision(fingerprint, _ACTION_DIAGNOSE, 1, window)

        last_diagnosed_at, repeat_count, in_flight_since = row

        if in_flight_since is not None:
            started = _parse(in_flight_since)
            if now - started < self._in_flight_stale_after:
                return CooldownDecision(fingerprint, _ACTION_IN_FLIGHT, repeat_count, window)
            logger.warning(
                'cooldown: reclaiming stale in-flight marker fingerprint="%s" '
                'in_flight_since="%s" stale_after=%s -- treating as crashed run',
                fingerprint,
                in_flight_since,
                self._in_flight_stale_after,
            )
            return CooldownDecision(fingerprint, _ACTION_DIAGNOSE, 1, window)

        last = _parse(last_diagnosed_at)
        if now - last < window:
            new_count = repeat_count + 1
            self._conn.execute(
                "UPDATE fingerprint_state SET repeat_count = ? WHERE fingerprint = ?",
                (new_count, fingerprint),
            )
            self._conn.commit()
            return CooldownDecision(fingerprint, _ACTION_COOLDOWN, new_count, window)

        return CooldownDecision(fingerprint, _ACTION_DIAGNOSE, 1, window)

    # --- in-flight marker -------------------------------------------------

    def start_diagnosis(
        self, fingerprint: str, alert_class: str, now: datetime | None = None
    ) -> None:
        """Persist the "a full diagnosis is starting now" marker. Call
        this immediately after `decide()` returns action="diagnose",
        before running the playbook -- that's the window a crash needs
        to be caught in. Resets the repeat counter and (re)anchors the
        cooldown window at `now`.
        """
        now = now or _utcnow()
        ts = _fmt(now)
        self._conn.execute(
            """
            INSERT INTO fingerprint_state
                (fingerprint, alert_class, last_diagnosed_at, repeat_count, in_flight_since)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                alert_class = excluded.alert_class,
                last_diagnosed_at = excluded.last_diagnosed_at,
                repeat_count = 0,
                in_flight_since = excluded.in_flight_since
            """,
            (fingerprint, alert_class, ts, ts),
        )
        self._conn.commit()

    def mark_complete(self, fingerprint: str) -> None:
        """Clear the in-flight marker once a diagnosis finishes
        (successfully or not -- an error still means the run is no
        longer in flight; the cooldown window it started still holds).
        """
        self._conn.execute(
            "UPDATE fingerprint_state SET in_flight_since = NULL WHERE fingerprint = ?",
            (fingerprint,),
        )
        self._conn.commit()

    def is_in_flight(self, fingerprint: str, now: datetime | None = None) -> bool:
        """Raw, staleness-aware in-flight check, independent of
        `decide()`'s cooldown bookkeeping -- mainly useful for tests
        and operational inspection.
        """
        now = now or _utcnow()
        row = self._conn.execute(
            "SELECT in_flight_since FROM fingerprint_state WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None or row[0] is None:
            return False
        return now - _parse(row[0]) < self._in_flight_stale_after

    # --- daily LLM budget ---------------------------------------------

    def try_consume_llm_call(
        self, now: datetime | None = None, *, n: int = 1, context: str | None = None
    ) -> bool:
        """Attempt to spend `n` of today's (UTC calendar day) LLM call
        budget. Returns True and records the spend if there's room;
        returns False and logs a loud warning if not -- every refusal
        logs, for as long as the day keeps refusing (security-threat-
        model.md M9: "make budget-exhaustion behavior explicit and
        alerting, not silent").
        """
        now = now or _utcnow()
        day = _day_key(now)
        row = self._conn.execute(
            "SELECT consumed FROM llm_budget WHERE day = ?", (day,)
        ).fetchone()
        consumed = row[0] if row else 0

        if consumed + n > self._daily_llm_budget:
            logger.warning(
                "cooldown: daily LLM call budget exhausted "
                'day="%s" limit=%d consumed=%d requested=%d%s -- refusing call',
                day,
                self._daily_llm_budget,
                consumed,
                n,
                f' context="{context}"' if context else "",
            )
            return False

        self._conn.execute(
            """
            INSERT INTO llm_budget (day, consumed) VALUES (?, ?)
            ON CONFLICT(day) DO UPDATE SET consumed = excluded.consumed
            """,
            (day, consumed + n),
        )
        self._conn.commit()
        return True

    def llm_calls_consumed_today(self, now: datetime | None = None) -> int:
        now = now or _utcnow()
        day = _day_key(now)
        row = self._conn.execute(
            "SELECT consumed FROM llm_budget WHERE day = ?", (day,)
        ).fetchone()
        return row[0] if row else 0
