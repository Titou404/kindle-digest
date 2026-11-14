"""Claude API prices, in USD per million tokens.

Source: Claude API pricing for Haiku 5.5 and Sonnet 5.5, as of November 2026.
Re-check the official pricing page before quoting these numbers.
"""

PRICES = {
    # Haiku 5.5 prices apply to prompts under 100K tokens (ours are far below).
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
}
CACHE_WRITE_FACTOR = 1.25  # writing to the cache (5-minute TTL): 1.25x the input price
CACHE_READ_FACTOR = 0.10  # reading from the cache: 0.1x the input price


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    price = PRICES[model]  # unknown model: KeyError, better than a silent $0
    input_price = price["input"] / 1_000_000
    return (
        input_tokens * input_price
        + cache_creation_input_tokens * input_price * CACHE_WRITE_FACTOR
        + cache_read_input_tokens * input_price * CACHE_READ_FACTOR
        + output_tokens * price["output"] / 1_000_000
    )
