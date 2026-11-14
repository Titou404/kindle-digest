"""The only place that calls the model. Every call is measured.

ClaudeLLM calls the Anthropic API. FakeLLM returns canned answers for free
(--fake mode), so the whole pipeline runs without spending anything.
"""

import json
import time
from collections.abc import Callable
from typing import Protocol

import anthropic

from digest.pricing import cost_usd
from digest.state import LLMCall

DEFAULT_MODEL = "claude-haiku-5-5"
# Haiku 5.5 thinks by default (effort "medium") and thinking is billed as output:
# always set the effort explicitly. Experiment E3 compares "medium" with "low".
DEFAULT_EFFORT = "medium"


class LLMOutputError(Exception):
    """The model answered, but the answer is unusable. The call was billed anyway."""

    def __init__(self, message: str, call: LLMCall):
        super().__init__(message)
        self.call = call


class LLM(Protocol):
    def complete_json(
        self,
        *,
        task: str,
        prompt_version: str,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int,
        fake_output: Callable[[], dict],
    ) -> tuple[dict, LLMCall]: ...


class ClaudeLLM:
    def __init__(self, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT, client=None):
        self.model = model
        self.effort = effort
        # Reads ANTHROPIC_API_KEY from the environment; retries 429 and 5xx twice.
        self.client = client or anthropic.Anthropic(timeout=120.0)

    def complete_json(self, *, task, prompt_version, system, user, schema, max_tokens,
                      fake_output):
        # fake_output is only used by FakeLLM: both classes share one signature.
        start = time.perf_counter()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            # Structured outputs: the answer is JSON that matches the schema.
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        usage = response.usage
        details = usage.output_tokens_details
        call = LLMCall(
            task=task,
            model=self.model,
            prompt_version=prompt_version,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            thinking_tokens=(details.thinking_tokens or 0) if details else 0,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            latency_s=round(time.perf_counter() - start, 3),
            cost_usd=cost_usd(
                self.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_input_tokens or 0,
                usage.cache_creation_input_tokens or 0,
            ),
            stop_reason=response.stop_reason,
            request_id=response._request_id,
        )

        # "max_tokens": the JSON was cut off; "refusal": the model declined.
        if response.stop_reason != "end_turn":
            raise LLMOutputError(f"{task}: stop_reason={response.stop_reason}", call)
        text = next(block.text for block in response.content if block.type == "text")
        try:
            return json.loads(text), call
        except json.JSONDecodeError as e:
            raise LLMOutputError(f"{task}: invalid JSON ({e})", call) from e


class FakeLLM:
    """Free stand-in for --fake mode: returns the canned answer each node provides."""

    model = "fake"

    def complete_json(self, *, task, prompt_version, system, user, schema, max_tokens,
                      fake_output):
        data = fake_output()
        call = LLMCall(
            task=task,
            model=self.model,
            prompt_version=prompt_version,
            # Rough preview of a real call's size (~4 characters per token), for free.
            input_tokens=(len(system) + len(user)) // 4,
            output_tokens=len(json.dumps(data)) // 4,
            thinking_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            latency_s=0.0,
            cost_usd=0.0,
            stop_reason="end_turn",
        )
        return data, call


def make_llm(fake: bool) -> LLM:
    return FakeLLM() if fake else ClaudeLLM()
