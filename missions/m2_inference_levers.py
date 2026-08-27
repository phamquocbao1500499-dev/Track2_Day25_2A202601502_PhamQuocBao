"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Run: python missions/m2_inference_levers.py

EXTENSION D.3: cache_is_worth_it() analysis
EXTENSION D.4: Reasoning budget analysis
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num
from finops import pricing, sustainability

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}

# Extension D.3: Estimate avg cache reads from token_usage.csv
def _estimate_avg_cache_reads(rows):
    """Estimate average times each cached prefix is reused."""
    total_cached = 0
    reused = 0
    for r in rows:
        cached = int(num(r["cached_input_tokens"]))
        if cached > 0:
            total_cached += 1
            # Assume prefixes reused 2-5x on average (realistic for LLM apps)
            reused += cached * 3  # ~3x reuse assumption
    return (reused / total_cached) if total_cached > 0 else 0


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")

    # Extension D.3: Cache break-even analysis
    if verbose:
        print("== EXTENSION D.3: Cache Break-Even Analysis ==")
        for tier, (pin, pout) in MODEL_PRICES.items():
            break_even = pin / (1.0 - 0.10)  # break-even reads needed
            print(f"  {tier:7} model: break-even reads = {break_even:.2f}x (write cost ${pin}/1M, 90% read discount)")

    # Analyze cache_is_worth_it for realistic scenarios
    avg_reads_large = 3.0  # realistic avg reads per cached prefix (large model)
    avg_reads_small = 5.0  # small model often used repeatedly
    write_cost_large = 0.50  # hypothetical cache storage cost $/1M tokens written
    write_cost_small = 0.20

    cache_worth_large = pricing.cache_is_worth_it(
        avg_requests_per_day=1000,
        cache_hit_rate=avg_reads_large / 5.0,
        cache_storage_cost_per_gb_day=0.10,
        inference_cost_per_1m_tokens=3.00,
        avg_tokens_per_request=2000
    )
    cache_worth_small = pricing.cache_is_worth_it(
        avg_requests_per_day=1000,
        cache_hit_rate=avg_reads_small / 5.0,
        cache_storage_cost_per_gb_day=0.10,
        inference_cost_per_1m_tokens=0.20,
        avg_tokens_per_request=500
    )

    if verbose:
        print(f"  Cache worth it (large, {avg_reads_large}x reads)? {cache_worth_large}")
        print(f"  Cache worth it (small, {avg_reads_small}x reads)? {cache_worth_small}")
        print()

    # Main cost analysis
    base_cost = opt_cost = 0.0
    total_tokens = 0

    # Extension D.4: Reasoning budget tracking
    reasoning_base_cost = reasoning_opt_cost = 0.0
    reasoning_tokens = 0
    normal_tokens = 0

    for r in rows:
        inp, out = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        is_reasoning = bool(int(num(r.get("is_reasoning", "0"))))
        total_tokens += inp + out

        # Track reasoning vs normal separately (Extension D.4)
        if is_reasoning:
            reasoning_tokens += inp + out
        else:
            normal_tokens += inp + out

        # BASELINE: naive deployment — everything on the large model, no cache, no batch
        lin, lout = MODEL_PRICES["large"]
        req_cost = pricing.request_cost(inp, out, lin, lout)
        base_cost += req_cost

        if is_reasoning:
            reasoning_base_cost += req_cost

        # OPTIMIZED: cascade (route_tier), prompt caching, batch API
        pin, pout = MODEL_PRICES[r["route_tier"]]
        opt_req_cost = pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        opt_cost += opt_req_cost

        if is_reasoning:
            reasoning_opt_cost += opt_req_cost

    base_pm = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0

    # Extension D.4: Reasoning budget analysis
    reasoning_pct = (reasoning_tokens / total_tokens * 100) if total_tokens > 0 else 0
    reasoning_base_pm = pricing.dollars_per_million(reasoning_base_cost, reasoning_tokens) if reasoning_tokens > 0 else 0
    reasoning_opt_pm = pricing.dollars_per_million(reasoning_opt_cost, reasoning_tokens) if reasoning_tokens > 0 else 0

    # Estimate savings if reasoning capped at 10%
    target_reasoning_pct = 10.0
    if reasoning_pct > target_reasoning_pct:
        cap_factor = target_reasoning_pct / reasoning_pct
        potential_savings = reasoning_opt_cost * (1 - cap_factor) * 0.7  # 70% of capped reasoning goes to normal tier
    else:
        potential_savings = 0.0

    # Calculate energy for reasoning
    total_reasoning_wh = sustainability.wh_per_query(
        reasoning_tokens / max(1, reasoning_tokens // 1000 + 1),  # avg tokens per reasoning request
        is_reasoning=True
    ) if reasoning_tokens > 0 else 0

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={len(rows)}  tokens={total_tokens:,}")
        print(f"baseline  : ${base_cost:,.2f}/day   ${base_pm:.3f}/1M-token")
        print(f"optimized : ${opt_cost:,.2f}/day   ${opt_pm:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + caching + batch)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")
        print()

        print("== EXTENSION D.4: Reasoning Budget Analysis ==")
        print(f"  Reasoning traffic: {reasoning_tokens:,} tokens ({reasoning_pct:.1f}% of total)")
        print(f"  Normal traffic:    {normal_tokens:,} tokens ({100-reasoning_pct:.1f}% of total)")
        print(f"  Reasoning $/1M-token: baseline ${reasoning_base_pm:.2f} -> optimized ${reasoning_opt_pm:.2f}")
        if potential_savings > 0:
            print(f"  Potential savings if capping reasoning at {target_reasoning_pct}%: ${potential_savings:.2f}/day")
        print(f"  Reasoning energy multiplier: {sustainability.REASONING_ENERGY_MULTIPLIER:.0f}x normal query")

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3), "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1), "total_tokens": total_tokens,
        # Extension D.4 data
        "reasoning_pct": round(reasoning_pct, 1),
        "reasoning_tokens": reasoning_tokens,
        "reasoning_base_cost": round(reasoning_base_cost, 2),
        "reasoning_opt_cost": round(reasoning_opt_cost, 2),
        "potential_reasoning_savings": round(potential_savings, 2),
    }


if __name__ == "__main__":
    run()
