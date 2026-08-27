"""Pricing & purchasing economics — measure in $/1M-token, not $/GPU-hr.

Figures are June-2026 as-of snapshots from the deck's RESEARCH dossier; treat
live prices as fast-moving (re-baseline before each cohort).
"""
from __future__ import annotations


def request_cost(
    input_tok: int,
    output_tok: int,
    price_in_per_m: float,
    price_out_per_m: float,
    cached_in: int = 0,
    cache_discount: float = 0.10,   # Anthropic cached-read ~0.1x (=-90%)
    batch: bool = False,
    batch_discount: float = 0.50,   # Batch API ~ -50%
) -> float:
    """USD cost of a single request. Cached input billed at cache_discount x price."""
    cached_in = min(max(0, cached_in), input_tok)
    uncached_in = input_tok - cached_in
    cost = (
        (uncached_in / 1e6) * price_in_per_m
        + (cached_in / 1e6) * price_in_per_m * cache_discount
        + (output_tok / 1e6) * price_out_per_m
    )
    if batch:
        cost *= batch_discount
    return cost


def dollars_per_million(total_cost_usd: float, total_tokens: int) -> float:
    """Aggregate unit economics: $ per 1,000,000 tokens served."""
    if total_tokens <= 0:
        return 0.0
    return total_cost_usd / (total_tokens / 1e6)


def discount_stack(
    batch: bool = False,
    cache_hit_frac: float = 0.0,
    batch_discount: float = 0.50,
    cache_discount: float = 0.10,
) -> float:
    """Effective fraction of the naive bill after stacking discounts (input-heavy view).

    Discounts MULTIPLY: cache applies to the cached share of input, batch to the
    whole bill. batch + 100% cache-hit -> 0.5 * 0.1 = 0.05 (~95% off).
    """
    cache_mult = cache_hit_frac * cache_discount + (1.0 - cache_hit_frac)
    batch_mult = batch_discount if batch else 1.0
    return cache_mult * batch_mult


def break_even_utilization(discount_frac: float) -> float:
    """Utilization at which a commitment pays off ~= 1 - discount.

    A 45% reserved discount needs ~55% utilization (~13.2h/day) to beat on-demand.
    """
    return max(0.0, min(1.0, 1.0 - discount_frac))


def recommend_tier(hours_per_day: float, interruptible: bool, reserved_discount: float = 0.45) -> str:
    """Pick a purchasing tier from a workload's duty cycle + interruptibility.

    DOCUMENTED simple policy (instructor extension point — swap in your own):
      - interruptible & not 24/7  -> 'spot'      (checkpoint and ride the discount)
      - duty cycle >= break-even  -> 'reserved'  (steady, high utilization)
      - otherwise                 -> 'on_demand' (spiky / low duty)
    """
    duty = max(0.0, hours_per_day) / 24.0
    be = break_even_utilization(reserved_discount)
    if interruptible and hours_per_day < 24:
        return "spot"
    if duty >= be:
        return "reserved"
    return "on_demand"


def cache_is_worth_it(
    avg_requests_per_day: float,
    cache_hit_rate: float,
    cache_storage_cost_per_gb_day: float,
    inference_cost_per_1m_tokens: float,
    avg_tokens_per_request: int,
) -> dict:
    """Cache break-even analysis: should you enable prompt caching?

    Args:
        avg_requests_per_day: Average daily request volume
        cache_hit_rate: Fraction of requests served from cache (0.0-1.0)
        cache_storage_cost_per_gb_day: Storage cost for cached prompts
        inference_cost_per_1m_tokens: Non-cached inference cost per 1M tokens
        avg_tokens_per_request: Average tokens per request (input)

    Returns:
        dict with break_even_requests, is_worth_it boolean, savings_per_month
    """
    if cache_hit_rate <= 0 or cache_hit_rate >= 1.0:
        return {
            "break_even_requests": float("inf"),
            "is_worth_it": False,
            "savings_per_month": 0.0,
        }

    cache_discount = 0.10  # cached reads cost 10% of normal
    daily_requests = avg_requests_per_day
    monthly_requests = daily_requests * 30

    # Daily cost without caching
    daily_inference_cost = (avg_tokens_per_request / 1e6) * inference_cost_per_1m_tokens * daily_requests

    # Daily cost with caching
    cached_requests = daily_requests * cache_hit_rate
    uncached_requests = daily_requests * (1 - cache_hit_rate)
    daily_cost_with_cache = (
        (avg_tokens_per_request / 1e6) * inference_cost_per_1m_tokens * uncached_requests
        + (avg_tokens_per_request / 1e6) * inference_cost_per_1m_tokens * cache_discount * cached_requests
    )

    # Daily savings from caching
    daily_savings = daily_inference_cost - daily_cost_with_cache

    # Break-even: savings per day = storage cost per day
    # => daily_savings / cache_hit_rate * X = storage_cost * X (per request)
    # Simplified: savings per cached request = tokens * cost * (1 - discount)
    savings_per_cached_request = (
        (avg_tokens_per_request / 1e6) * inference_cost_per_1m_tokens * (1 - cache_discount)
    )

    if savings_per_cached_request <= 0:
        break_even_requests = float("inf")
        is_worth_it = False
    else:
        # Break-even: total savings = storage cost
        # Per day: cached_requests * savings_per_request = storage_cost
        # cached_requests = daily_requests * cache_hit_rate
        # break_even_daily_requests = cache_storage_cost / (savings_per_request * cache_hit_rate)
        break_even_daily_requests = cache_storage_cost_per_gb_day / (savings_per_cached_request * cache_hit_rate)
        break_even_requests = break_even_daily_requests * 30  # monthly break-even

        # Break-even point in total requests needed to justify cache investment
        is_worth_it = daily_savings >= cache_storage_cost_per_gb_day

    savings_per_month = daily_savings * 30 if daily_savings > 0 else 0.0

    return {
        "break_even_requests": round(break_even_requests, 0),
        "is_worth_it": bool(is_worth_it),
        "savings_per_month": round(savings_per_month, 2),
    }


def spot_checkpoint_cost(
    job_hours: float,
    spot_hr: float,
    on_demand_hr: float,
    interrupt_rate: float = 0.05,      # per-hour chance (H100 spot ~<5%)
    ckpt_overhead_frac: float = 0.03,  # steady cost of writing checkpoints
    rework_hours_per_interrupt: float = 0.5,
) -> dict:
    """Effective cost of running a checkpointable job on spot vs on-demand.

    Interruptions waste the compute since the last checkpoint (rework); checkpointing
    adds a small steady overhead. Spot still wins for interruptible jobs.
    """
    expected_interrupts = job_hours * interrupt_rate
    rework_hours = expected_interrupts * rework_hours_per_interrupt
    effective_hours = job_hours * (1.0 + ckpt_overhead_frac) + rework_hours
    spot_cost = effective_hours * spot_hr
    on_demand_cost = job_hours * on_demand_hr
    savings_pct = (1.0 - spot_cost / on_demand_cost) * 100.0 if on_demand_cost > 0 else 0.0
    return {
        "spot_effective_hours": round(effective_hours, 2),
        "spot_cost": round(spot_cost, 2),
        "on_demand_cost": round(on_demand_cost, 2),
        "savings_pct": round(savings_pct, 1),
    }
