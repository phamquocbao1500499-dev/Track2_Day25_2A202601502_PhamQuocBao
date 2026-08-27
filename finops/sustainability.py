"""Sustainability economics — energy and carbon as governed cost levers (deck §11).

Region selection cuts $ and carbon together; reasoning queries are an energy bomb.
"""
from __future__ import annotations

# Grid carbon intensity (gCO2 / kWh) — illustrative 2026 snapshot.
REGION_CARBON = {
    "us-east-1": 380,
    "us-west-2": 120,   # Oregon hydro
    "europe-north1": 30,  # Norway
    "europe-central2": 660,  # Poland (dirtiest)
    "us-east-wa": 90,
}
# Electricity price (USD / kWh) — illustrative.
REGION_PRICE_KWH = {
    "us-east-1": 0.12,
    "us-west-2": 0.07,
    "europe-north1": 0.09,
    "europe-central2": 0.18,
    "us-east-wa": 0.055,
}

REASONING_ENERGY_MULTIPLIER = 80.0  # deck: reasoning ~74-86x a small-model query


def wh_per_query(total_tokens: int, wh_per_1k_tokens: float = 0.30, is_reasoning: bool = False) -> float:
    """Energy for one query. Median Gemini prompt ~0.24 Wh; reasoning ~74-86x."""
    base = (total_tokens / 1000.0) * wh_per_1k_tokens
    return base * (REASONING_ENERGY_MULTIPLIER if is_reasoning else 1.0)


def carbon_g(wh: float, region: str = "us-east-1") -> float:
    """Grams CO2 for an energy amount in a region."""
    gco2_kwh = REGION_CARBON.get(region, 400)
    return (wh / 1000.0) * gco2_kwh


def energy_cost_usd(wh: float, region: str = "us-east-1") -> float:
    """Electricity cost of an energy amount in a region."""
    return (wh / 1000.0) * REGION_PRICE_KWH.get(region, 0.12)


def tokens_per_watt(total_tokens: int, wh: float, seconds: float = 1.0) -> float:
    """Energy efficiency of serving: tokens per watt (higher is better)."""
    watts = (wh * 3600.0) / seconds if seconds > 0 else 0.0
    return total_tokens / watts if watts > 0 else 0.0


# --- Carbon-aware scheduling (Extension D.5) ---

# Sample hourly carbon intensity (gCO2/kWh) — typical grid patterns.
# Low at night (solar/wind), peak midday (demand + less renewables).
_HOURLY_CARBON = {
    0: 380, 1: 350, 2: 340, 3: 330, 4: 320, 5: 330,
    6: 400, 7: 480, 8: 520, 9: 540, 10: 560, 11: 550,
    12: 530, 13: 510, 14: 490, 15: 470, 16: 450, 17: 460,
    18: 500, 19: 530, 20: 510, 21: 470, 22: 420, 23: 400,
}

# Typical request volume distribution (relative weight 0-1).
_HOURLY_DEMAND = {
    0: 0.1, 1: 0.08, 2: 0.05, 3: 0.04, 4: 0.04, 5: 0.05,
    6: 0.08, 7: 0.15, 8: 0.25, 9: 0.35, 10: 0.40, 11: 0.42,
    12: 0.38, 13: 0.36, 14: 0.35, 15: 0.34, 16: 0.32, 17: 0.30,
    18: 0.28, 19: 0.30, 20: 0.32, 21: 0.35, 22: 0.28, 23: 0.18,
}


def get_carbon_aware_schedule(
    carbon_weight: float = 0.6,
    cost_weight: float = 0.4,
    region: str = "us-east-1",
) -> dict:
    """Recommend best hours for inference based on carbon intensity + demand.

    Args:
        carbon_weight: weight for carbon optimization (0-1)
        cost_weight: weight for cost optimization (0-1); weights sum should be ~1
        region: AWS region for price lookup

    Returns:
        Dict with best_hours, worst_hours, and score per hour
    """
    hourly_scores = {}
    base_carbon = REGION_CARBON.get(region, 400)
    base_price = REGION_PRICE_KWH.get(region, 0.12)

    for hour in range(24):
        grid_intensity = _HOURLY_CARBON.get(hour, 400)
        demand = _HOURLY_DEMAND.get(hour, 0.2)

        # Normalize: carbon_score higher when grid is cleaner
        carbon_score = 1.0 - (grid_intensity / 600)  # 600 = "dirty" ceiling
        # Cost score: lower price = higher score
        price_factor = 1.0 - (base_price / 0.25)
        # Demand score: lower demand = more capacity headroom = better
        demand_score = 1.0 - (demand / 0.5)

        combined = (
            carbon_weight * carbon_score +
            cost_weight * price_factor +
            0.1 * demand_score  # slight boost for low-demand hours
        )
        hourly_scores[hour] = {
            "carbon_intensity": grid_intensity,
            "demand": demand,
            "score": round(combined, 4),
            "carbon_rank": 0,
            "overall_rank": 0,
        }

    # Rank hours
    by_carbon = sorted(hourly_scores.items(), key=lambda x: x[1]["carbon_intensity"])
    for rank, (hour, _) in enumerate(by_carbon):
        hourly_scores[hour]["carbon_rank"] = rank + 1

    by_score = sorted(hourly_scores.items(), key=lambda x: -x[1]["score"])
    for rank, (hour, _) in enumerate(by_score):
        hourly_scores[hour]["overall_rank"] = rank + 1

    best = [h for h, _ in by_score[:5]]
    worst = [h for h, _ in by_score[-5:]]

    return {
        "region": region,
        "weights": {"carbon": carbon_weight, "cost": cost_weight},
        "best_hours": best,
        "worst_hours": worst,
        "hourly": hourly_scores,
    }


def route_by_carbon(
    requests: list[dict],
    region: str = "us-east-1",
    max_delay_hours: int = 4,
) -> list[dict]:
    """Route requests based on carbon-aware schedule.

    Args:
        requests: List of {"id", "tokens", "is_reasoning", "urgency"} dicts
        region: Target region
        max_delay_hours: Max hours to delay non-urgent requests

    Returns:
        List of requests with "recommended_hour", "reason", "carbon_saved_pct"
    """
    schedule = get_carbon_aware_schedule(region=region)
    hourly = schedule["hourly"]
    best_hours = set(schedule["best_hours"])

    # Baseline: average carbon intensity
    avg_carbon = sum(s["carbon_intensity"] for s in hourly.values()) / 24

    routed = []
    for req in requests:
        urgency = req.get("urgency", "normal")
        tokens = req.get("tokens", 1000)
        is_reasoning = req.get("is_reasoning", False)

        if urgency == "high":
            # Immediate execution, pick lowest-carbon available hour
            best_hour = min(hourly, key=lambda h: hourly[h]["carbon_intensity"])
            reason = "urgent request, routed to lowest-carbon hour"
        else:
            # Find best hour within delay window
            current_hour = 12  # assume noon start; in prod would use actual time
            candidates = [
                (h, hourly[h]["score"])
                for h in range(24)
                if (h - current_hour) % 24 <= max_delay_hours
            ]
            if candidates:
                best_hour = max(candidates, key=lambda x: x[1])[0]
                reason = f"deferred {max_delay_hours}h to optimize carbon"
            else:
                best_hour = 0
                reason = "no window available"

        target_carbon = hourly[best_hour]["carbon_intensity"]
        carbon_saved = round((avg_carbon - target_carbon) / avg_carbon * 100, 1)

        routed.append({
            "id": req.get("id", id(req)),
            "tokens": tokens,
            "is_reasoning": is_reasoning,
            "urgency": urgency,
            "recommended_hour": best_hour,
            "carbon_intensity": target_carbon,
            "carbon_saved_pct": carbon_saved,
            "reason": reason,
        })

    return routed
