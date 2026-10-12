# Expanded exits: full available window through October 11

Each alternative starts with 10,000 quote units and uses fixed 10,000 entry notional, without compounding. All balances include 5 bps round-trip costs. These are full portfolios: one short at a time per alternative and fresh entry selection as positions close.

Raw dates: October 2–11 UTC. Primary continuous window: October 2 21:13 UTC through October 12 00:00 UTC (the final close of October 11), including volatility warmup.

The expanded comparison now uses 150%, 200%, and 300% targets. The 100% alternative was removed from this comparison; earlier historical reports retain their original experiments.
Target = signal price − fraction × (signal price − price five minutes before signal). For a rise from 100 to 102: 150% targets 99, 200% targets 98, and 300% targets 96. These are retracements of the original move, not trade percentage returns. Target crossings execute at the following sampled minute close; otherwise exit at the stated limit.

## 120-minute limit

| Strategy | Fixed hold | 150% retrace | 200% retrace | 300% retrace |
|---|---:|---:|---:|---:|
| BTC 2σ | 9,996.28 | 9,944.63 | 10,004.07 | 10,036.20 |
| BTC 3σ | 10,061.05 | 10,035.11 | 10,061.79 | 9,986.31 |
| ETH 2σ | 10,457.05 | 10,298.90 | 10,232.61 | 10,401.12 |
| ETH 3σ | 10,247.04 | 10,045.91 | 10,068.78 | 10,188.90 |
| HYPE 2σ | 9,960.06 | 10,048.57 | 10,047.14 | 9,998.41 |
| HYPE 3σ | 9,774.00 | 10,190.78 | 10,155.73 | 9,757.78 |

## 180-minute limit

| Strategy | Fixed hold | 150% retrace | 200% retrace | 300% retrace |
|---|---:|---:|---:|---:|
| BTC 2σ | 10,015.93 | 9,962.05 | 9,900.09 | 9,956.89 |
| BTC 3σ | 10,013.43 | 9,941.76 | 9,951.62 | 9,973.78 |
| ETH 2σ | 10,461.37 | 10,221.68 | 10,091.88 | 10,369.68 |
| ETH 3σ | 10,019.11 | 10,068.66 | 10,108.49 | 10,208.36 |
| HYPE 2σ | 9,393.14 | 10,210.24 | 10,380.70 | 10,024.48 |
| HYPE 3σ | 9,855.21 | 10,279.47 | 10,262.82 | 9,820.91 |

## 240-minute limit

| Strategy | Fixed hold | 150% retrace | 200% retrace | 300% retrace |
|---|---:|---:|---:|---:|
| BTC 2σ | 10,216.07 | 10,032.87 | 10,020.82 | 10,081.57 |
| BTC 3σ | 10,374.29 | 10,032.87 | 10,079.54 | 10,085.63 |
| ETH 2σ | 10,514.41 | 10,437.42 | 10,237.76 | 10,410.81 |
| ETH 3σ | 10,404.67 | 10,246.28 | 10,264.06 | 10,425.87 |
| HYPE 2σ | 10,024.79 | 10,343.68 | 10,523.16 | 10,134.85 |
| HYPE 3σ | 10,072.01 | 10,263.65 | 10,211.09 | 9,995.51 |

## Interpretation

These 72 portfolio runs broaden an already repeatedly explored short sample. Do not interpret the best cell as a validated choice. Timing changes which signals are available for subsequent entries, so balances can vary non-monotonically with the time limit.
At a 240-minute cap, the 300% target improves over the 150/200% targets for BTC 2σ, BTC 3σ and ETH 3σ, but not ETH 2σ or either HYPE threshold. ETH 3σ / 300% / 240 ends at 10,425.87, versus 10,404.67 for fixed 240 minutes. The best tested target remains HYPE 2σ / 200% / 240 (10,523.16).
Extending targets below the original price can reduce hit rates, lengthen exposure and change entries. Minute sampled prices omit intraminute crossings. Each strategy is an independent alternative; no optimal mix or aggregate allocation has been selected.
Prices are quote units from repository samples labeled Binance, with exact instrument/currency provenance unverified. No funding, margin, liquidation, depth or actual execution costs are modeled. Remaining open positions close at the dataset end; forced-exit counts are in the summary CSV.

## Reproduce

```sh
python3 research/repo_baseline.py --capital 10000 --notional 10000 --rules expanded --output research/runs/expanded-10k-300
```

Input/source hashes and full settings are in expanded-10k-manifest.json; metrics for all alternatives are in expanded-10k-summary.csv. Large detailed ledgers and equity files are local ignored outputs.
