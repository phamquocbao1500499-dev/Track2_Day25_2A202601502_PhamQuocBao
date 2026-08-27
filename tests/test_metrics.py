import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from finops import metrics


def test_mfu_basic():
    assert metrics.compute_mfu(200, 990) == round(200 / 990, 10) or abs(metrics.compute_mfu(200, 990) - 0.20202) < 1e-3
    assert metrics.compute_mfu(0, 990) == 0.0
    assert metrics.compute_mfu(100, 0) == 0.0           # guard against div-by-zero
    assert metrics.compute_mfu(2000, 990) == 1.0        # clamped


def test_mbu_and_roofline():
    assert abs(metrics.compute_mbu(2.0, 4.0) - 0.5) < 1e-9
    assert metrics.roofline_regime(1.5, 295) == "memory-bound"
    assert metrics.roofline_regime(455, 295) == "compute-bound"


def test_flag_util_lies():
    rows = [{"gpu_util_pct": 98, "mfu": 0.2}, {"gpu_util_pct": 95, "mfu": 0.8}, {"gpu_util_pct": 40, "mfu": 0.1}]
    lies = metrics.flag_util_lies(rows)
    assert len(lies) == 1 and lies[0]["gpu_util_pct"] == 98


def test_idle_waste():
    assert metrics.idle_waste_usd(12, 2.5) == 30.0
    assert metrics.idle_waste_usd(-5, 2.5) == 0.0


def test_calculate_reasoning_overhead():
    # 16.5% reasoning at $2.50/M tokens with 80x multiplier
    result = metrics.calculate_reasoning_overhead(0.165, 1_000_000, 2.50, 80.0)
    assert result["reasoning_pct"] == 16.5
    assert result["reasoning_tokens"] == 165_000
    assert result["normal_tokens"] == 835_000
    # baseline cost: 1M * 2.50/1M = $2.50
    assert result["baseline_cost"] == 2.50
    # reasoning cost: 835K * 2.50/1M + 165K * 2.50 * 80 / 1M
    #              = 2.0875 + 33.0 = 35.0875
    assert abs(result["reasoning_cost"] - 35.0875) < 0.001
    assert result["overhead_pct"] > 1000  # 80x multiplier on 16.5% tokens


def test_analyze_reasoning_budget():
    result = metrics.analyze_reasoning_budget(0.165, 1_000_000, 2.50)
    assert result["current"]["reasoning_pct"] == 16.5
    assert result["energy_multiplier"] == 80.0
    assert result["recommendation"] is not None
    assert "HIGH" in result["recommendation"]  # 16.5% is between 10-20%


def test_analyze_reasoning_budget_with_target():
    result = metrics.analyze_reasoning_budget(0.165, 1_000_000, 2.50, target_reasoning_pct=0.10)
    assert result["savings_with_limit"] is not None
    assert result["savings_with_limit"]["target_pct"] == 10.0
    assert result["savings_with_limit"]["savings_usd"] > 0
