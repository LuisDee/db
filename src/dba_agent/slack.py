from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class SlackClient(Protocol):
    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> str: ...


class RealSlackClient:
    def __init__(self, bot_token: str) -> None:
        from slack_sdk import WebClient

        self._client = WebClient(token=bot_token)

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        response = self._client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
        return response["ts"]


@dataclass
class FakeSlackClient:
    posts: list[dict] = field(default_factory=list)
    _next_ts: int = 1_000

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        ts = f"{self._next_ts}.000000"
        self._next_ts += 1
        self.posts.append({"channel": channel, "text": text, "thread_ts": thread_ts, "ts": ts})
        return ts
