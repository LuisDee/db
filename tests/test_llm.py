import pytest

from dba_agent.llm import FakeLLMClient


def test_fake_llm_returns_scripted_responses_in_order():
    client = FakeLLMClient(responses=["first", "second"])

    assert client.complete("system prompt", "prompt one") == "first"
    assert client.complete("system prompt", "prompt two") == "second"


def test_fake_llm_records_calls_for_assertions():
    client = FakeLLMClient(responses=["ok"])

    client.complete("sys-prompt", "user-prompt")

    assert client.calls == [("sys-prompt", "user-prompt")]


def test_fake_llm_raises_when_scripted_responses_are_exhausted():
    client = FakeLLMClient(responses=[])

    with pytest.raises(AssertionError, match="no scripted responses left"):
        client.complete("s", "p")
