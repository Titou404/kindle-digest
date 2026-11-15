"""Tests for llm.py and pricing.py, without network and without spending anything.

The real SDK client is used, with a mock HTTP transport answering in place of the API:
this checks our code against the SDK's actual objects and field names.
"""

import json

import anthropic
import httpx2
import pytest

from digest.llm import ClaudeLLM, FakeLLM, LLMOutputError, make_llm
from digest.pricing import cost_usd

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def api_returning(text='{"ok": true}', stop_reason="end_turn", sent=None):
    """A real SDK client whose HTTP layer returns a canned API response."""

    def handler(request):
        if sent is not None:
            sent.append(json.loads(request.content))
        return httpx2.Response(200, headers={"request-id": "req_test"}, json={
            "id": "msg_test", "type": "message", "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {
                "input_tokens": 1000, "output_tokens": 300,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                "output_tokens_details": {"thinking_tokens": 100},
            },
        })

    http_client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return anthropic.Anthropic(api_key="test-key", http_client=http_client)


def ask(llm):
    return llm.complete_json(
        task="rank", prompt_version="v1", system="system prompt", user="hello",
        schema=SCHEMA, max_tokens=500, fake_output=lambda: {"ok": False},
    )


def test_cost_uses_prices_per_million_tokens():
    assert cost_usd("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(0.10)
    assert cost_usd("claude-haiku-5-5", 0, 1_000_000) == pytest.approx(0.50)
    assert cost_usd("claude-haiku-5-5", 0, 0, cache_read_input_tokens=1_000_000) == pytest.approx(0.01)
    assert cost_usd("claude-haiku-5-5", 0, 0, cache_creation_input_tokens=1_000_000) == pytest.approx(0.125)


def test_unknown_model_has_no_silent_price():
    with pytest.raises(KeyError):
        cost_usd("claude-unknown", 10, 10)


def test_claude_llm_returns_parsed_json_and_measures_the_call():
    data, call = ask(ClaudeLLM(client=api_returning()))

    assert data == {"ok": True}
    assert (call.input_tokens, call.output_tokens, call.thinking_tokens) == (1000, 300, 100)
    assert call.cost_usd == pytest.approx(1000 * 0.10 / 1e6 + 300 * 0.50 / 1e6)
    assert (call.task, call.model, call.prompt_version) == ("rank", "claude-haiku-5-5", "v1")
    assert call.request_id == "req_test"


def test_request_always_sets_effort_and_schema():
    sent = []

    ask(ClaudeLLM(effort="low", client=api_returning(sent=sent)))

    [body] = sent
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["schema"] == SCHEMA
    assert "temperature" not in body  # rejected by the current API


def test_cut_off_answer_raises_but_keeps_the_billed_call():
    client = api_returning(text='{"ok": tr', stop_reason="max_tokens")

    with pytest.raises(LLMOutputError) as error:
        ask(ClaudeLLM(client=client))

    assert error.value.call.output_tokens == 300  # paid for, even though unusable


def test_fake_llm_is_free_and_returns_the_canned_answer():
    data, call = ask(FakeLLM())

    assert data == {"ok": False}
    assert call.cost_usd == 0.0
    assert call.model == "fake"


def test_each_task_gets_its_production_effort(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # no request is sent
    assert make_llm(fake=False, task="rank").effort == "low"
    assert make_llm(fake=False, task="summarize").effort == "medium"
    assert make_llm(fake=True, task="rank").model == "fake"


def test_the_call_records_its_effort():
    _, call = ask(ClaudeLLM(effort="low", client=api_returning()))

    assert call.effort == "low"
