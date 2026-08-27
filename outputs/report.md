# NimbusAI — GPU Cost Optimization Report

**Period:** monthly  
**Baseline spend:** $27,133  
**Optimized spend:** $14,626  
**Projected savings:** $12,507  (**46%**)

## Executive Summary

This report analyzes GPU cost optimization opportunities for NimbusAI's LLM infrastructure.
Using the $/1M-token metric (not $/GPU-hour), we identified **4 major optimization levers**
that can reduce monthly GPU spend by **46%** (from $27,133 to $14,626).

### Key Findings

- **GPU-Util Lie Detected**: GPU `gpu-h100-4` shows 98% GPU-Util but only 20% MFU
  - Cause: Memory-bound decode phase causes GPU to wait for HBM (memory stall)
  - Impact: Paying for full H100 compute when only 1/5 FLOPs are utilized
- **Inference Savings**: 82.6% via cascade + cache + batch
- **Purchasing Savings**: 39.1% via spot/reserved tier optimization
- **Reasoning Traffic**: 16.5% of tokens are reasoning-type

## Savings by Lever

| Lever | Savings (USD/month) |
|---|---:|
| Inference (cascade/cache/batch) | $1,212 (4.5%) |
| Purchasing (spot/reserved) | $10,040 (37.0%) |
| Right-size util-lies | $655 (2.4%) |
| Kill idle GPUs | $600 (2.2%) |

## Extension D.3: Cache Economics Analysis

### Break-Even Analysis

| Model Tier | Write Cost ($/1M) | Break-Even Reads | Worth It? |
|---|---|---|---|
| small | $0.20 | 0.22x | ✓ Yes (low write cost) |
| large | $3.00 | 3.33x | ✓ Yes (high reuse expected) |

**Conclusion**: Cache is worth it for both tiers. Large model needs ~3.3x reads to break even,
which is realistic for LLM applications with repeated context prefixes.

## Extension D.4: Reasoning Budget Analysis

- **Reasoning traffic**: 1,241,156 tokens (16.5% of total)
- **Energy multiplier**: 80x normal query
- **Potential savings** if capped at 10%: $11.40/month

### Recommendation

1. Implement confidence-based routing: use reasoning only when confidence < 80%
2. Consider caching reasoning outputs for similar queries
3. Set budget limits per team/project for reasoning usage

## Extension D.5: Carbon-Aware Scheduling

### Regional Comparison (for interruptible jobs)

| Region | $/kWh | gCO2/kWh | Monthly Carbon (kg) |
|---|---|---|---:|
| us-east-1 | $0.120 | 380 | 1606.3 |
| us-west-2 | $0.070 | 120 | 507.2 |
| europe-north1 | $0.090 | 30 | 126.8 ← best |
| europe-central2 | $0.180 | 660 | 2789.8 |
| us-east-wa | $0.055 | 90 | 380.4 ← cheapest |

**Carbon savings** if moving to europe-north1: 1479.5 kg (92.1%)

### Recommendation

Use **us-east-wa** (Washington) for interruptible jobs:
- Best combination of low cost ($/kWh) and moderate carbon intensity
- Supports spot instance with checkpointing
- 92% carbon reduction vs us-east-1

## Deep Dive: The GPU-Util Lie

### What is GPU-Util?

NVIDIA's `nvidia-smi` reports GPU-Util as **% of time GPU cores are busy**.
However, this measures kernel activity, NOT actual compute efficiency.

### Why it Lies

When a GPU is waiting for memory (HBM) — called **memory stall** — the GPU-Util
still shows high because kernels are technically running. But no FLOPs are being executed.

**Case Study**: `gpu-h100-4` (H100 GPU)

| Metric | Value | Interpretation |
|---|---|---|
| GPU-Util | 98% | Looks busy! |
| MFU (Model FLOPs Utilization) | ~20% | Only using 1/5 compute |
| MBU (Model BW Utilization) | 45% | Memory-bound |

### Financial Impact

- Paying for full H100: $2.50/hour
- Getting only 20% of advertised FLOPs
- **Solution**: Right-size to A100 or use smaller batch

## Sustainability

- Energy per query (median 800 tokens): 0.24 Wh
- Carbon per query (us-east-1): 0.091 gCO2e
- Cheapest + cleanest region: europe-north1 (Norway - hydro power)

## Recommended Actions (by ROI priority)

| Priority | Action | Est. Monthly Savings | Effort |
|---|---|---|---|
| 1 | Enable cascade routing for simple queries | $800+ | Low |
| 2 | Move interruptible jobs to spot + {best_cost} region | $3,000+ | Medium |
| 3 | Right-size GPU-Util lie GPUs (H100→A100) | $655 | Low |
| 4 | Kill idle GPUs during off-hours | $600 | Low |
| 5 | Cap reasoning traffic at 10% | $11+ | Medium |

_Figures are June-2026 as-of snapshots; re-baseline before acting._