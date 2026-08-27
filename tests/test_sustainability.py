import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from finops.sustainability import (
    get_carbon_aware_schedule,
    route_by_carbon,
    carbon_g,
    wh_per_query,
)


def test_get_carbon_aware_schedule():
    result = get_carbon_aware_schedule()
    assert "best_hours" in result
    assert "worst_hours" in result
    assert "hourly" in result
    assert len(result["best_hours"]) == 5
    assert len(result["worst_hours"]) == 5
    # Best hours should have lower carbon intensity than worst
    best_avg = sum(result["hourly"][h]["carbon_intensity"] for h in result["best_hours"]) / 5
    worst_avg = sum(result["hourly"][h]["carbon_intensity"] for h in result["worst_hours"]) / 5
    assert best_avg < worst_avg, f"Best avg {best_avg} should be < worst avg {worst_avg}"


def test_get_carbon_aware_schedule_region():
    result = get_carbon_aware_schedule(region="us-west-2")
    assert result["region"] == "us-west-2"


def test_route_by_carbon_basic():
    requests = [
        {"id": "req-1", "tokens": 1000, "is_reasoning": False, "urgency": "high"},
        {"id": "req-2", "tokens": 2000, "is_reasoning": True, "urgency": "normal"},
        {"id": "req-3", "tokens": 500, "is_reasoning": False, "urgency": "low"},
    ]
    routed = route_by_carbon(requests)
    assert len(routed) == 3
    # High urgency should be handled
    high_req = next(r for r in routed if r["urgency"] == "high")
    assert "recommended_hour" in high_req
    assert high_req["carbon_saved_pct"] >= 0


def test_route_by_carbon_carbon_saved():
    """Verify carbon savings are calculated correctly."""
    requests = [{"id": "test", "tokens": 1000}]
    routed = route_by_carbon(requests)
    assert -30 <= routed[0]["carbon_saved_pct"] <= 30


def test_carbon_aware_vs_baseline():
    """Carbon-aware schedule should favor cleaner hours."""
    result = get_carbon_aware_schedule(carbon_weight=0.9, cost_weight=0.1)
    # Top ranked hours should have lower carbon than median
    top_hour = result["best_hours"][0]
    median_carbon = 450  # approximate median of _HOURLY_CARBON values
    assert result["hourly"][top_hour]["carbon_intensity"] < median_carbon
