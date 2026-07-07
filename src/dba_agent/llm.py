from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str = "claude-opus-4-8") -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


@dataclass
class FakeLLMClient:
    responses: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if not self.responses:
            raise AssertionError("FakeLLMClient has no scripted responses left")
        return self.responses.pop(0)
