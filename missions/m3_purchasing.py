"""M3 — Purchasing Strategy: break-even, tier choice, spot-checkpoint sim (deck §4).

Run: python missions/m3_purchasing.py

EXTENSION D.5: Carbon-aware Scheduling
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num, catalog_by_type
from finops import pricing, sustainability

DAYS = 30


def run(verbose: bool = True) -> dict:
    jobs = load_csv("workloads.csv")
    cat = catalog_by_type()
    on_demand_monthly = optimized_monthly = 0.0
    recs = []
    interruptible_jobs = []

    for j in jobs:
        gtype = j["gpu_type"]
        ngpu = int(num(j["num_gpus"]))
        hpd = num(j["hours_per_day"])
        interruptible = bool(int(num(j["interruptible"])))
        c = cat[gtype]
        gpu_hours = hpd * DAYS * ngpu
        od = num(c["on_demand_hr"])
        on_demand_cost = gpu_hours * od
        watts = num(c["watts"])
        total_wh = watts * gpu_hours

        tier = pricing.recommend_tier(hpd, interruptible)
        if tier == "spot":
            sim = pricing.spot_checkpoint_cost(gpu_hours, num(c["spot_hr"]), od)
            opt_cost = sim["spot_cost"]
        elif tier == "reserved":
            opt_cost = gpu_hours * num(c["reserved_3yr_hr"])
        else:
            opt_cost = on_demand_cost

        on_demand_monthly += on_demand_cost
        optimized_monthly += opt_cost
        recs.append({"job_id": j["job_id"], "gpu_type": gtype, "tier": tier,
                     "on_demand": round(on_demand_cost), "optimized": round(opt_cost)})

        # Track interruptible jobs for carbon analysis (Extension D.5)
        if interruptible:
            interruptible_jobs.append({
                "job_id": j["job_id"],
                "gpu_type": gtype,
                "total_wh": total_wh,
                "hours": gpu_hours,
                "tier": tier,
            })

    savings = on_demand_monthly - optimized_monthly
    savings_pct = savings / on_demand_monthly * 100 if on_demand_monthly else 0.0

    # Extension D.5: Carbon-aware scheduling analysis
    regions = list(sustainability.REGION_CARBON.keys())
    carbon_by_region = {}
    energy_cost_by_region = {}

    for region in regions:
        carbon_by_region[region] = sum(
            sustainability.carbon_g(j["total_wh"], region) for j in interruptible_jobs
        )
        energy_cost_by_region[region] = sum(
            sustainability.energy_cost_usd(j["total_wh"], region) for j in interruptible_jobs
        )

    # Find optimal region (lowest carbon for same energy cost, or best combined)
    best_carbon_region = min(carbon_by_region, key=carbon_by_region.get)
    best_cost_region = min(energy_cost_by_region, key=energy_cost_by_region.get)
    best_combined_region = min(regions, key=lambda r:
        (carbon_by_region[r] / max(carbon_by_region.values()) +
         energy_cost_by_region[r] / max(energy_cost_by_region.values())) / 2
    )

    # Calculate savings if moving to cleanest region
    current_carbon = carbon_by_region.get("us-east-1", 0)
    best_carbon_savings = current_carbon - carbon_by_region[best_carbon_region]
    best_carbon_savings_pct = (best_carbon_savings / current_carbon * 100) if current_carbon > 0 else 0

    if verbose:
        print("== M3 Purchasing Strategy ==")
        print(f"break-even utilization @ 45% reserved discount = {pricing.break_even_utilization(0.45):.0%}")
        print(f"{'job':18}{'gpu':7}{'tier':11}{'on-demand':>12}{'optimized':>12}")
        for r in recs:
            print(f"{r['job_id']:18}{r['gpu_type']:7}{r['tier']:11}${r['on_demand']:>11,}${r['optimized']:>11,}")
        print(f"\nmonthly: on-demand ${on_demand_monthly:,.0f} -> optimized ${optimized_monthly:,.0f}  ({savings_pct:.1f}% saved)")

        print()
        print("== EXTENSION D.5: Carbon-Aware Scheduling ==")
        print(f"{'Region':20}{'$/kWh':>8}{'gCO2/kWh':>10}{'Energy$':>10}{'Carbon(kg)':>12}")
        for region in regions:
            price = sustainability.REGION_PRICE_KWH.get(region, 0)
            carbon_intensity = sustainability.REGION_CARBON.get(region, 0)
            print(f"{region:20}${price:>7.3f}{carbon_intensity:>10}{energy_cost_by_region[region]:>10.2f}{carbon_by_region[region]/1000:>12.1f}")

        print(f"\n  Interruptible jobs: {len(interruptible_jobs)}")
        print(f"  Best region for cost:      {best_cost_region} (${energy_cost_by_region[best_cost_region]:.2f}/month)")
        print(f"  Best region for carbon:   {best_carbon_region} ({carbon_by_region[best_carbon_region]/1000:.1f} kgCO2/month)")
        print(f"  Best combined region:      {best_combined_region}")
        print(f"  Carbon savings vs us-east-1: {best_carbon_savings/1000:.1f} kg ({best_carbon_savings_pct:.1f}%)")
        print(f"\n  Recommendation: Use {best_combined_region} for interruptible jobs")
        print(f"  - Combines lowest carbon with competitive energy costs")
        print(f"  - Supports spot instance use (checkpoint-enabled)")

    return {
        "recommendations": recs,
        "on_demand_monthly": round(on_demand_monthly),
        "optimized_monthly": round(optimized_monthly),
        "savings_pct": round(savings_pct, 1),
        # Extension D.5 data
        "carbon_by_region": {k: round(v, 2) for k, v in carbon_by_region.items()},
        "best_carbon_region": best_carbon_region,
        "best_cost_region": best_cost_region,
        "best_combined_region": best_combined_region,
        "carbon_savings_kg": round(best_carbon_savings / 1000, 2),
        "carbon_savings_pct": round(best_carbon_savings_pct, 1),
    }


if __name__ == "__main__":
    run()
