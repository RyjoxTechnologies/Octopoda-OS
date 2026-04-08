"""
LLM Cost Database — pricing per 1M tokens for common models.

Used by loop detection to estimate how much money a loop is wasting
and how much Octopoda saved by catching it early.
"""

# Cost per 1M tokens (USD)
MODEL_COSTS = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o3-mini": {"input": 1.10, "output": 4.40},

    # Anthropic
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-4": {"input": 0.80, "output": 4.00},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},

    # Google
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},

    # Open source / local (free)
    "llama-3.2": {"input": 0.00, "output": 0.00},
    "llama-3.1-70b": {"input": 0.00, "output": 0.00},
    "llama-3.1-8b": {"input": 0.00, "output": 0.00},
    "mistral-7b": {"input": 0.00, "output": 0.00},
    "mixtral-8x7b": {"input": 0.00, "output": 0.00},
    "qwen-2.5": {"input": 0.00, "output": 0.00},
    "deepseek-v3": {"input": 0.27, "output": 1.10},
    "deepseek-r1": {"input": 0.55, "output": 2.19},

    # Fallbacks
    "unknown": {"input": 0.00, "output": 0.00},
    "custom": {"input": 0.00, "output": 0.00},
}

# Average tokens per memory write (estimated from real usage)
AVG_TOKENS_PER_WRITE = 150

# Average tokens per memory read/recall
AVG_TOKENS_PER_READ = 80


def get_model_names():
    """Return list of supported model names for the settings dropdown."""
    return sorted(MODEL_COSTS.keys())


def get_cost_per_write(model: str) -> float:
    """Estimate cost of a single memory write in USD.

    Assumes ~150 tokens input (the value being stored) + ~80 tokens output
    (embedding/extraction response). Conservative estimate.
    """
    costs = MODEL_COSTS.get(model, MODEL_COSTS["unknown"])
    input_cost = (AVG_TOKENS_PER_WRITE / 1_000_000) * costs["input"]
    output_cost = (AVG_TOKENS_PER_READ / 1_000_000) * costs["output"]
    return input_cost + output_cost


def get_cost_per_read(model: str) -> float:
    """Estimate cost of a single memory recall in USD."""
    costs = MODEL_COSTS.get(model, MODEL_COSTS["unknown"])
    return (AVG_TOKENS_PER_READ / 1_000_000) * costs["input"]


def estimate_loop_cost(model: str, write_count: int) -> dict:
    """Estimate the cost of a detected loop.

    Returns dict with wasted cost, per-write cost, and model info.
    """
    cost_per_write = get_cost_per_write(model)
    total_wasted = cost_per_write * write_count
    return {
        "estimated_wasted": round(total_wasted, 4),
        "write_count_in_loop": write_count,
        "avg_cost_per_write": round(cost_per_write, 6),
        "model": model,
        "currency": "USD",
    }


def estimate_savings(model: str, writes_per_minute: float, minutes_saved: float = 30.0) -> float:
    """Estimate how much money was saved by catching a loop early.

    Assumes the loop would have continued for `minutes_saved` minutes
    if not detected (conservative default: 30 minutes).
    """
    cost_per_write = get_cost_per_write(model)
    projected_writes = writes_per_minute * minutes_saved
    return round(projected_writes * cost_per_write, 4)


def estimate_hourly_cost(model: str, writes_per_minute: float) -> float:
    """Project hourly cost at current write velocity."""
    cost_per_write = get_cost_per_write(model)
    return round(writes_per_minute * 60 * cost_per_write, 4)
