import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from finops import pricing


def test_discount_stack_is_multiplicative():
    assert abs(pricing.discount_stack(batch=True, cache_hit_frac=1.0) - 0.05) < 1e-9   # ~95% off
    assert pricing.discount_stack() == 1.0
    assert abs(pricing.discount_stack(batch=True) - 0.5) < 1e-9


def test_break_even():
    assert abs(pricing.break_even_utilization(0.45) - 0.55) < 1e-9
    assert pricing.break_even_utilization(0.0) == 1.0


def test_recommend_tier():
    assert pricing.recommend_tier(2, True) == "spot"
    assert pricing.recommend_tier(24, False) == "reserved"
    assert pricing.recommend_tier(4, False) == "on_demand"


def test_request_cost_and_cache():
    full = pricing.request_cost(1000, 1000, 3.0, 15.0)
    cached = pricing.request_cost(1000, 1000, 3.0, 15.0, cached_in=1000)
    assert cached < full                       # caching reduces cost
    batched = pricing.request_cost(1000, 1000, 3.0, 15.0, batch=True)
    assert abs(batched - full * 0.5) < 1e-9    # batch = -50%


def test_spot_checkpoint_saves():
    res = pricing.spot_checkpoint_cost(100, 1.5, 2.5)
    assert res["spot_cost"] < res["on_demand_cost"]
    assert res["savings_pct"] > 0


def test_cache_is_worth_it():
    # High volume, good hit rate -> worth it
    res = pricing.cache_is_worth_it(1000, 0.3, 0.10, 2.50, 1000)
    assert res["is_worth_it"] is True
    assert res["break_even_requests"] == 4444.0
    assert res["savings_per_month"] == 20.25

    # Zero hit rate -> not worth it
    res = pricing.cache_is_worth_it(1000, 0.0, 0.10, 2.50, 1000)
    assert res["is_worth_it"] is False
    assert res["break_even_requests"] == float("inf")

    # Hit rate 1.0 -> not worth it (edge case)
    res = pricing.cache_is_worth_it(1000, 1.0, 0.10, 2.50, 1000)
    assert res["is_worth_it"] is False

    # Low volume, low hit rate -> not worth it
    res = pricing.cache_is_worth_it(10, 0.1, 0.50, 2.50, 1000)
    assert res["is_worth_it"] is False
