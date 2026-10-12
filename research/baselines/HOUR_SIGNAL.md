# One-hour signal: expanded exit comparison through October 11

Each independent alternative starts with 10,000 quote units, uses fixed 10,000 entry notional without compounding, and pays assumed 5 bps round-trip costs. Signal data and execution stay on completed minute closes.

The signal is ln(P[t]/P[t−60]). Its baseline is 360 overlapping one-hour log returns ending at t−419, …, t−60, using sample standard deviation (ddof=1). The earliest baseline price is P[t−479]. The current hour is excluded; 480 contiguous closes are needed for warmup. This is 360 observations sampled one minute apart, not 360 independent hours.

Targets now reference the ONE-HOUR move: target = P[t] − fraction × (P[t]−P[t−60]). At 100%, target=P[t−60]. The strategy still enters at the next minute close, detects targets on subsequent minute closes, and fills at the next observed minute.

Raw dates are October 2–11 UTC. The primary common segment begins October 2 at 21:13 UTC and ends at October 12 00:00 UTC (October 11’s final minute close), including warmup. Earlier October 2 data are excluded because of the outage.

## 120-minute limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,049.60 | 9,820.85 | 9,926.51 | 9,972.33 | 10,017.87 | 10,029.59 |
| BTC 3σ | 9,909.37 | 9,842.14 | 9,904.81 | 9,937.44 | 9,930.45 | 9,909.37 |
| ETH 2σ | 10,164.53 | 9,848.73 | 9,904.73 | 9,881.35 | 10,006.44 | 10,012.39 |
| ETH 3σ | 10,381.69 | 10,134.08 | 10,200.77 | 10,246.82 | 10,228.50 | 10,313.68 |
| HYPE 2σ | 10,152.58 | 9,986.55 | 9,991.49 | 9,991.34 | 10,099.08 | 10,132.97 |
| HYPE 3σ | 10,055.82 | 10,026.25 | 10,083.43 | 10,094.08 | 10,055.82 | 10,055.82 |

## 180-minute limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,154.13 | 9,949.16 | 9,989.11 | 10,045.15 | 10,106.15 | 10,119.66 |
| BTC 3σ | 9,896.40 | 9,886.80 | 9,843.87 | 9,876.50 | 9,948.14 | 9,896.40 |
| ETH 2σ | 10,038.73 | 9,917.91 | 9,906.97 | 9,797.12 | 9,821.56 | 9,856.25 |
| ETH 3σ | 10,425.37 | 10,216.30 | 10,242.34 | 10,267.50 | 10,240.99 | 10,326.16 |
| HYPE 2σ | 9,716.06 | 9,666.48 | 9,808.21 | 9,734.06 | 9,860.07 | 9,787.42 |
| HYPE 3σ | 10,092.91 | 10,217.44 | 10,204.52 | 10,203.48 | 10,092.91 | 10,092.91 |

## 240-minute limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,109.89 | 9,895.22 | 9,958.17 | 10,035.37 | 10,138.84 | 10,140.83 |
| BTC 3σ | 9,800.51 | 9,845.99 | 9,831.07 | 9,863.70 | 9,935.34 | 9,800.51 |
| ETH 2σ | 10,067.79 | 10,019.65 | 10,150.44 | 9,929.25 | 9,931.48 | 10,003.82 |
| ETH 3σ | 10,194.33 | 10,197.59 | 10,157.17 | 10,179.11 | 10,112.95 | 10,198.12 |
| HYPE 2σ | 9,817.67 | 9,720.39 | 9,913.76 | 9,905.00 | 10,063.70 | 9,853.54 |
| HYPE 3σ | 9,969.92 | 9,993.12 | 10,021.43 | 10,048.43 | 9,969.92 | 9,969.92 |

## Interpretation

One-hour returns normalize against historical one-hour returns; a larger absolute move does not automatically imply a higher sigma score. These different signals and hour-based targets change the trades, not just their sizing.
These are full portfolios with independent entry schedules, one short at a time; longer/different exits can change later entries. The first valid score above a threshold can trigger; crossings while holding are discarded. Some deep targets never hit and therefore replicate the timed exit.
Costs exclude funding, margin, liquidation, lot rounding, depth and actual spread/latency. Source label is Binance but instrument/quote provenance is unverified. End-of-data liquidation applies to remaining positions and is counted in the summary CSV. Minute samples miss intraminute extremes.
This is another parameter experiment on the same short dataset, not out-of-sample validation. The previous five-minute tables remain in EXPANDED_EXITS.md. Compare their performance with awareness that signal duration, target reference and warmup all differ.

## Reproduce

```sh
python3 research/repo_baseline.py --move-minutes 60 --capital 10000 --notional 10000 --rules expanded --output research/runs/hour-wide
```

Exact settings and input/source hashes: hour-10k-manifest.json. Complete metrics: hour-10k-summary.csv. Detailed trades/equity are generated locally and ignored by Git.
