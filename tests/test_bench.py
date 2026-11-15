"""Tests for the evaluation bench (eval/), with the fake LLM: no network, no spending."""

from dataclasses import replace
from datetime import UTC, datetime

from bench import (
    Config,
    article_from_dict,
    article_to_dict,
    load_configs,
    load_fixture,
    run_config,
    save_fixture,
)

from digest.llm import FakeLLM
from digest.state import Article


def article(i, section="monde", text="mot " * 3000, raw=False):
    return Article(f"src{i}", section, f"Titre {i}", f"https://example.com/{i}",
                   published=datetime(2026, 11, 15, 8, i, tzinfo=UTC),
                   snippet=f"Chapô {i}.", text=text, raw=raw)


def config(**changes):
    base = Config(id="T1", task="summarize", question="test", model="claude-haiku-5-5",
                  effort="medium", repeats=1)
    return replace(base, **changes)


def test_the_grid_is_valid():
    configs = load_configs()
    assert {"S1", "S7", "R1", "R5"} <= {c.id for c in configs}
    assert all(c.repeats >= 1 for c in configs)


def test_an_article_survives_the_round_trip_through_json(tmp_path):
    original = article(1)
    assert article_from_dict(article_to_dict(original)) == original

    save_fixture(tmp_path / "day.json", [original], [original], {"frozen_at": "now"})
    candidates, articles, meta = load_fixture(tmp_path / "day.json")
    assert candidates == [original] and articles == [original] and meta == {"frozen_at": "now"}


def test_summarize_config_cuts_the_text_and_uses_its_prompt_version():
    result = run_config(config(max_text=6000, prompt="v2"), [], [article(1), article(2)], FakeLLM())

    assert result["totals"]["llm_calls"] == 2
    assert {c["prompt_version"] for c in result["llm_calls"]} == {"v2"}
    for item in result["items"]:
        assert item["input_chars"] <= 6001  # cut at a whole word, plus "…"
        assert item["summary"]


def test_rank_configs_score_every_candidate_and_apply_the_quotas():
    candidates = [article(i, section=s) for i, s in enumerate(["monde", "eco", "france"] * 3)]
    candidates.append(article(9, section="data", raw=True))

    for mode in ("batched", "per_article"):
        result = run_config(config(task="rank", mode=mode), candidates, [], FakeLLM())
        calls = 1 if mode == "batched" else len(candidates)
        assert result["totals"]["llm_calls"] == calls
        assert all(item["score"] is not None for item in result["items"])
        # Quotas of 3 per section, at most: never more than 3 per section selected.
        for section in ("monde", "eco", "france"):
            kept = [i for i in result["items"] if i["selected"] and i["section"] == section]
            assert len(kept) <= 3
