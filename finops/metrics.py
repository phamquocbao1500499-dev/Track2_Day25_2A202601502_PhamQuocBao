"""Efficiency metrics — the numbers that actually drive GPU cost.

Key teaching point (deck §5): nvidia-smi "GPU-Util %" is a *time-active* clock,
not an efficiency metric. A GPU can read 100% util while its MFU is ~20% — you
are paying the full GPU-hour for a fraction of the FLOPs you rented.
"""
from __future__ import annotations


def compute_mfu(achieved_tflops: float, peak_tflops: float) -> float:
    """Model FLOPs Utilization = achieved / peak (clamped to 0..1).

    Good training MFU is ~0.35-0.45; >0.50 is excellent. Returns 0 if peak<=0.
    """
    if peak_tflops <= 0:
        return 0.0
    return max(0.0, min(1.0, achieved_tflops / peak_tflops))


def compute_mbu(achieved_bw_tbs: float, peak_bw_tbs: float) -> float:
    """Model Bandwidth Utilization = achieved HBM BW / peak BW (clamped 0..1).

    The right metric for memory-bound decode; target ~0.60 on H100-80GB batch-1.
    """
    if peak_bw_tbs <= 0:
        return 0.0
    return max(0.0, min(1.0, achieved_bw_tbs / peak_bw_tbs))


def arithmetic_intensity(flops: float, bytes_moved: float) -> float:
    """FLOP / byte for a workload (the x-axis of the roofline model)."""
    if bytes_moved <= 0:
        return 0.0
    return flops / bytes_moved


def roofline_regime(intensity: float, ridge_point: float) -> str:
    """Below the ridge point a workload is memory-bound; at/above it is compute-bound.

    H100 ridge ~295 FLOP/byte (BF16). LLM decode (~1-2) is memory-bound; prefill
    (~455) is compute-bound — which is *why* prefill/decode disaggregation pays off.
    """
    return "compute-bound" if intensity >= ridge_point else "memory-bound"


def flag_util_lies(rows, util_threshold: float = 0.90, mfu_threshold: float = 0.30):
    """Return the rows where GPU-Util is high but MFU is low — money leaking.

    `rows` is an iterable of dicts each having 'gpu_util_pct' (0-100) and 'mfu' (0-1).
    These are GPUs you are billed full-rate for while they do little real compute.
    """
    out = []
    for r in rows:
        util = float(r.get("gpu_util_pct", 0)) / 100.0
        mfu = float(r.get("mfu", 0))
        if util >= util_threshold and mfu < mfu_threshold:
            out.append(r)
    return out


def idle_waste_usd(idle_hours: float, on_demand_hr: float) -> float:
    """Dollars burned by a GPU left running idle (training done, instance up)."""
    return max(0.0, idle_hours) * max(0.0, on_demand_hr)


# Reasoning budget analysis (deck §D.4)

def calculate_reasoning_overhead(
    reasoning_pct: float,
    total_tokens: int,
    cost_per_million: float = 2.50,
    reasoning_multiplier: float = 80.0,
) -> dict:
    """Compute extra cost from reasoning tokens vs normal tokens.

    Args:
        reasoning_pct: Fraction of tokens that are reasoning (0-1).
        total_tokens: Total tokens in workload.
        cost_per_million: Base cost per 1M tokens (USD).
        reasoning_multiplier: Energy/compute multiplier for reasoning (default 80x).

    Returns:
        Dict with baseline_cost, reasoning_cost, overhead_usd, overhead_pct.
    """
    reasoning_pct = max(0.0, min(1.0, reasoning_pct))
    reasoning_tokens = total_tokens * reasoning_pct
    normal_tokens = total_tokens - reasoning_tokens

    baseline_cost = (total_tokens / 1e6) * cost_per_million
    # Reasoning tokens cost reasoning_multiplier more
    reasoning_cost = (normal_tokens / 1e6) * cost_per_million + (reasoning_tokens / 1e6) * cost_per_million * reasoning_multiplier
    overhead_usd = reasoning_cost - baseline_cost
    overhead_pct = (overhead_usd / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

    return {
        "total_tokens": total_tokens,
        "reasoning_tokens": int(reasoning_tokens),
        "normal_tokens": int(normal_tokens),
        "reasoning_pct": round(reasoning_pct * 100, 2),
        "baseline_cost": round(baseline_cost, 4),
        "reasoning_cost": round(reasoning_cost, 4),
        "overhead_usd": round(overhead_usd, 4),
        "overhead_pct": round(overhead_pct, 2),
    }


def analyze_reasoning_budget(
    reasoning_pct: float,
    total_tokens: int,
    cost_per_million: float = 2.50,
    reasoning_multiplier: float = 80.0,
    target_reasoning_pct: float | None = None,
) -> dict:
    """Analyze reasoning budget impact and recommend max_tokens limits.

    Args:
        reasoning_pct: Current fraction of tokens that are reasoning (0-1).
        total_tokens: Total tokens in workload.
        cost_per_million: Base cost per 1M tokens (USD).
        reasoning_multiplier: Energy/compute multiplier for reasoning (default 80x).
        target_reasoning_pct: Cap to compare against (e.g., 0.10 for 10%).

    Returns:
        Dict with current analysis, energy impact, and recommendation.
    """
    overhead = calculate_reasoning_overhead(reasoning_pct, total_tokens, cost_per_million, reasoning_multiplier)

    # Energy impact (reasoning uses ~80x more energy per token)
    wh_per_1k_normal = 0.30  # baseline Wh per 1K tokens
    normal_energy = (overhead["normal_tokens"] / 1000.0) * wh_per_1k_normal
    reasoning_energy = (overhead["reasoning_tokens"] / 1000.0) * wh_per_1k_normal * reasoning_multiplier
    baseline_energy = (total_tokens / 1000.0) * wh_per_1k_normal
    energy_overhead_pct = ((reasoning_energy + normal_energy) / baseline_energy - 1) * 100 if baseline_energy > 0 else 0

    result = {
        "current": overhead,
        "energy_multiplier": reasoning_multiplier,
        "normal_wh": round(normal_energy, 4),
        "reasoning_wh": round(reasoning_energy, 4),
        "total_wh": round(normal_energy + reasoning_energy, 4),
        "baseline_wh": round(baseline_energy, 4),
        "energy_overhead_pct": round(energy_overhead_pct, 2),
        "recommendation": None,
        "savings_with_limit": None,
    }

    # If target provided, calculate savings from capping reasoning
    if target_reasoning_pct is not None:
        target_reasoning_pct = max(0.0, min(1.0, target_reasoning_pct))
        capped = calculate_reasoning_overhead(target_reasoning_pct, total_tokens, cost_per_million, reasoning_multiplier)
        savings_usd = overhead["reasoning_cost"] - capped["reasoning_cost"]
        result["savings_with_limit"] = {
            "target_pct": round(target_reasoning_pct * 100, 2),
            "capped_cost": capped["reasoning_cost"],
            "savings_usd": round(savings_usd, 4),
        }
        result["current"]["reasoning_pct"]  # already set

    # Generate recommendation
    if reasoning_pct > 0.20:
        result["recommendation"] = "CRITICAL: Reasoning >20% of tokens. Set max_tokens limits or route to cheaper models for simple tasks."
    elif reasoning_pct > 0.10:
        result["recommendation"] = "HIGH: Reasoning >10%. Consider confidence-based routing: use reasoning only for complex tasks."
    elif reasoning_pct > 0.05:
        result["recommendation"] = "MEDIUM: Reasoning 5-10%. Monitor for drift; set per-team budget alerts."
    else:
        result["recommendation"] = "LOW: Reasoning within acceptable range. Continue monitoring."

    return result
