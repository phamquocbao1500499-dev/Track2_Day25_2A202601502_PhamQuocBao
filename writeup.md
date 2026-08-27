# GPU FinOps Optimization - Write-up

## 1. Baseline vs. Optimized

| Metric | Baseline | Optimized | Change |
|--------|----------|----------|--------|
| Daily cost | $48.87 | $8.48 | -82.6% |
| $/1M-token | $6.488 | $1.126 | -82.6% |
| Monthly GPU spend | $27,133 | $14,626 | -46% |

**Total savings: 46%** ($12,507/month)

---

## 2. Phân tích từng đòn bẩy

| Lever | Savings ($/month) | % of Total |
|-------|-------------------|------------|
| Purchasing (spot/reserved) | $10,040 | 37.0% |
| Inference (cascade/cache/batch) | $1,212 | 4.5% |
| Right-size util-lies | $655 | 2.4% |
| Kill idle GPUs | $600 | 2.2% |

**Đòn bẩy lớn nhất: Purchasing strategy** (37%) — dùng spot cho interruptible jobs và reserved cho high-utilization jobs.

**Tại sao:** Spot instances giảm 40-60% so với on-demand cho training jobs có thể checkpoint. Reserved 3-year giảm 45% cho inference jobs chạy 24/7.

---

## 3. GPU-Util Lie

### GPU bị "lie":
- **gpu-h100-4**: 98% GPU-Util nhưng chỉ 20% MFU
- **gpu-a10g-1**: 97% GPU-Util nhưng chỉ 27% MFU

### Cơ chế:
GPU-Util đo "% thời gian GPU kernel đang chạy", không phải "% FLOPs thực sự được sử dụng". Khi GPU chờ bộ nhớ HBM (memory stall), GPU-Util vẫn cao vì kernel đang "active" nhưng không tính toán gì.

### Tác động tài chính:
- gpu-h100-4: Trả $2.50/giờ nhưng chỉ nhận được ~20% compute
- Right-size xuống A100: Tiết kiệm $655/tháng

---

## 4. Phần mở rộng đã làm

### Extension D.3: Cache Economics
- Tạo hàm `cache_is_worth_it()` tính break-even reads
- Large model cần 3.33x reads để break even
- Small model chỉ cần 0.22x (rẻ hơn để cache)
- **Insight**: Cache có lợi cho cả hai tier với realistic workload

### Extension D.4: Reasoning Budget
- Reasoning traffic: 16.5% of total tokens (1,241,156 tokens)
- Energy multiplier: 80x normal query
- Potential savings if cap at 10%: $11.40/month
- **Insight**: Reasoning queries tiêu tốn năng lượng gấp 80 lần — cần confidence-based routing

### Extension D.5: Carbon-aware Scheduling
- So sánh 5 vùng:
  - us-east-wa: $0.055/kWh, 90 gCO2/kWh — **best combined**
  - europe-north1: 30 gCO2/kWh — **cleanest** (hydro)
  - us-east-1: 380 gCO2/kWh — **dirtiest**
- Carbon savings vs us-east-1: **92.1%** (1,479 kg CO2/month)
- **Insight**: us-east-wa tối ưu cả chi phí và carbon

---

## 5. Khuyến nghị cho NimbusAI

### 3 hành động đầu tiên:

1. **Enable cascade routing** (Priority: HIGH, Effort: LOW)
   - Route simple queries to small model (15x cheaper)
   - Est. savings: $800+/month

2. **Move interruptible jobs to spot + us-east-wa** (Priority: HIGH, Effort: MEDIUM)
   - Training jobs → spot với checkpoint
   - 92% carbon reduction + 40% cost reduction
   - Est. savings: $3,000+/month

3. **Right-size GPU-Util lie GPUs** (Priority: MEDIUM, Effort: LOW)
   - gpu-h100-4: H100 → A100
   - gpu-a10g-1: A10G → L4
   - Est. savings: $655/month

### Long-term:
- Implement chargeback với tag coverage 92%
- Set reasoning budget limits per team
- Monitor MFU thay vì GPU-Util
