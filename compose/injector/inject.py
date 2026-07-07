#!/usr/bin/env python3
"""Alert injector for the local compose stack.

Posts fixture alert texts (compose/injector/fixtures/alerts.json --
~10 real-shaped, anonymised messages spanning the classes in the 16-day
alert inventory: docs/dba-agent-direction.md) into Slack, using the same
SlackClient wrapper the agent itself uses (src/dba_agent/slack.py) --
FakeSlackClient by default, RealSlackClient in an opt-in real mode.

Scope boundary (read tasks/foundation/compose-stack.md before touching
this): this script's job ends at "the message was posted (or logged) and
the three databases are seeded and queryable". It does NOT wire the
alert through a listener or classifier -- those don't exist yet
(listener/slack-listener, listener/alert-classifier are separate,
not-yet-started tasks). Wiring an injected alert through an actual
end-to-end loop happens in tasks/poc/e2e-demo.md.

Run via `make inject-alert TYPE=<slug>` (see the Makefile), which runs
this inside the already-built `agent` container so `import dba_agent`
resolves without any extra setup. Default fake mode needs no Slack
credentials and writes a visible local artifact
(compose/injector/out/injected-alerts.json) so the target has an
observable result even with no real Slack workspace.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dba_agent.slack import FakeSlackClient, RealSlackClient

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "alerts.json"
OUT_PATH = Path(__file__).parent / "out" / "injected-alerts.json"

FAKE_CHANNEL = "#dba-alerts-fake"


def load_fixtures() -> list[dict]:
    return json.loads(FIXTURES_PATH.read_text())


def known_types(fixtures: list[dict]) -> list[str]:
    seen: list[str] = []
    for fx in fixtures:
        if fx["type"] not in seen:
            seen.append(fx["type"])
    return seen


def select(fixtures: list[dict], alert_type: str) -> list[dict]:
    if alert_type == "all":
        return fixtures
    matches = [fx for fx in fixtures if fx["type"] == alert_type]
    if not matches:
        types = ", ".join(known_types(fixtures))
        raise SystemExit(f"no fixtures with type={alert_type!r}. Known types: {types}, or 'all'")
    return matches


def append_log(records: list[dict]) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.extend(records)
    OUT_PATH.write_text(json.dumps(existing, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--type",
        required=True,
        help="alert fixture type to inject (see compose/injector/fixtures/alerts.json), or 'all'",
    )
    parser.add_argument(
        "--slack-mode",
        choices=["fake", "real"],
        default="fake",
        help="fake (default): in-memory FakeSlackClient, no credentials needed. "
        "real: post to an actual Slack channel via SLACK_BOT_TOKEN + SLACK_TEST_CHANNEL.",
    )
    args = parser.parse_args()

    fixtures = load_fixtures()
    batch = select(fixtures, args.type)

    if args.slack_mode == "real":
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        channel = os.environ.get("SLACK_TEST_CHANNEL")
        if not bot_token or bot_token.startswith("xoxb-dev-placeholder"):
            raise SystemExit("real mode needs a genuine SLACK_BOT_TOKEN (dev placeholder detected)")
        if not channel:
            raise SystemExit("real mode needs SLACK_TEST_CHANNEL (a test channel ID, e.g. C0123456789)")
        client = RealSlackClient(bot_token)
    else:
        channel = FAKE_CHANNEL
        client = FakeSlackClient()

    injected_at = datetime.now(timezone.utc).isoformat()
    records = []
    for fx in batch:
        ts = client.post_message(channel=channel, text=fx["text"])
        record = {
            "fixture_id": fx["id"],
            "type": fx["type"],
            "channel": channel,
            "slack_mode": args.slack_mode,
            "ts": ts,
            "injected_at": injected_at,
        }
        records.append(record)
        print(f"injected {fx['id']} ({fx['type']}) -> {channel} ts={ts}")

    append_log(records)
    print(f"\n{len(records)} alert(s) injected; log: {OUT_PATH}")
    if args.slack_mode == "fake":
        print(f"fake posts recorded in-process: {len(client.posts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
