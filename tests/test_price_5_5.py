"""List prices of the 5.5 models, as Langfuse names them, and Haiku 5.5's long-prompt rate."""

import pytest

from cbioportal_mcp_qa.config import MODELS, price_for


def test_5_5_models_are_priced_by_their_bedrock_style_ids():
    haiku = price_for("us.anthropic.claude-haiku-5-5")
    sonnet = price_for("us.anthropic.claude-sonnet-5-5")
    assert haiku is MODELS["haiku-5.5"].price and sonnet is MODELS["sonnet-5.5"].price
    assert (haiku.input, haiku.output) == (0.10, 0.50)
    assert (sonnet.input, sonnet.output, sonnet.cache_read) == (2.0, 10.0, 0.10)


def test_older_models_keep_their_prices():
    assert price_for("us.anthropic.claude-haiku-4-5-20251001-v1:0").input == 1.0
    assert price_for("us.anthropic.claude-sonnet-5").cache_read == 0.20
    assert price_for("us.anthropic.claude-unknown-9") is None


def test_haiku_5_5_prompts_over_100k_tokens_cost_five_times():
    p = price_for("us.anthropic.claude-haiku-5-5")
    short = p.call_cost(1_000, 1_000_000, 0, 99_000)  # prompt of 100,000: not over
    assert short == pytest.approx(p.cost(1_000, 1_000_000, 0, 99_000))
    long = p.call_cost(1_000, 1_000_000, 0, 99_001)  # 100,001: over
    assert long == pytest.approx(5 * p.cost(1_000, 1_000_000, 0, 99_001))


def test_prices_without_a_long_prompt_rate_are_flat():
    p = price_for("us.anthropic.claude-sonnet-5-5")
    assert p.call_cost(0, 0, 0, 500_000) == p.cost(0, 0, 0, 500_000)
