# AI experiments

## Memorization test: real names vs anonymized

### 2023-24 (in training data)

Benchmarks: SPY +57.2%, QQQ +94.1%

| Model | Real names | Anonymized | Gap | Format fixes (named / anon) |
|---|---|---|---|---|
| Gemma 3 12B | +136.1% | +95.3% | +40.8% | 0 / 0 |
| Gemma 4 e4b | +178.1% | +158.4% | +19.8% | 102 / 100 |
| Qwen 2.5 Coder 14B | +106.8% | +129.1% | -22.3% | 0 / 0 |
| Qwen 3 8B | +75.8% | +82.4% | -6.7% | 0 / 0 |

### 2026 (after training)

Benchmarks: SPY +14.0%, QQQ +22.7%

| Model | Real names | Anonymized | Gap | Format fixes (named / anon) |
|---|---|---|---|---|
| Gemma 3 12B | +18.9% | +13.8% | +5.1% | 0 / 0 |
| Gemma 4 e4b | +19.7% | +15.2% | +4.4% | 78 / 78 |
| Qwen 2.5 Coder 14B | +20.8% | +15.6% | +5.2% | 0 / 0 |
| Qwen 3 8B | +18.6% | +21.6% | -3.0% | 0 / 0 |

## Repeat runs: 5 seeds at temperature 0.7, 2026 (after training)

Benchmarks: SPY +14.0% (Sharpe 1.39), QQQ +22.7% (Sharpe 1.42)

| Model | Temp 0 | Sampled: worst | median | best | spread | Sharpe range | beat SPY | beat QQQ |
|---|---|---|---|---|---|---|---|---|
| Gemma 3 12B | +18.9% | +7.8% | +12.3% | +17.9% | 10.1% | 0.68–1.38 | 2/5 | 0/5 |
| Gemma 4 e4b | +19.7% | +16.3% | +18.5% | +19.3% | 3.0% | 1.10–1.27 | 5/5 | 0/5 |
| Qwen 2.5 Coder 14B | +20.8% | +15.6% | +17.9% | +24.1% | 8.6% | 1.22–1.81 | 5/5 | 2/5 |
| Qwen 3 8B | +18.6% | +18.1% | +19.7% | +20.5% | 2.4% | 1.30–1.45 | 5/5 | 0/5 |

