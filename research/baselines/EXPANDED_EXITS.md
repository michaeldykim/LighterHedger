# Expanded exits: full available window through October 11

Each alternative starts with 10,000 quote units and uses fixed 10,000 entry notional, without compounding. All balances include 5 bps round-trip costs. These are full portfolios: one short at a time per alternative and fresh entry selection as positions close.

Raw dates: October 2–11 UTC. Primary continuous window: October 2 21:13 UTC through October 12 00:00 UTC (the final close of October 11), including volatility warmup.

Target = signal price − fraction × (signal price − price five minutes before signal). For a rise from 100 to 102: 100% targets 100, 150% targets 99, and 200% targets 98. They are not trade percentage returns. Target crossings execute at the following sampled minute close; otherwise exit at the stated limit.

## 120-minute limit

| Strategy | Fixed hold | 100% retrace | 150% retrace | 200% retrace |
|---|---:|---:|---:|---:|
| BTC 2σ | 9,996.28 | 10,017.22 | 9,944.63 | 10,004.07 |
| BTC 3σ | 10,061.05 | 9,893.33 | 10,035.11 | 10,061.79 |
| ETH 2σ | 10,457.05 | 9,816.90 | 10,298.90 | 10,232.61 |
| ETH 3σ | 10,247.04 | 9,953.15 | 10,045.91 | 10,068.78 |
| HYPE 2σ | 9,960.06 | 10,130.06 | 10,048.57 | 10,047.14 |
| HYPE 3σ | 9,774.00 | 10,324.86 | 10,190.78 | 10,155.73 |

## 180-minute limit

| Strategy | Fixed hold | 100% retrace | 150% retrace | 200% retrace |
|---|---:|---:|---:|---:|
| BTC 2σ | 10,015.93 | 9,953.27 | 9,962.05 | 9,900.09 |
| BTC 3σ | 10,013.43 | 9,912.74 | 9,941.76 | 9,951.62 |
| ETH 2σ | 10,461.37 | 9,812.53 | 10,221.68 | 10,091.88 |
| ETH 3σ | 10,019.11 | 9,968.02 | 10,068.66 | 10,108.49 |
| HYPE 2σ | 9,393.14 | 10,035.92 | 10,210.24 | 10,380.70 |
| HYPE 3σ | 9,855.21 | 10,495.47 | 10,279.47 | 10,262.82 |

## 240-minute limit

| Strategy | Fixed hold | 100% retrace | 150% retrace | 200% retrace |
|---|---:|---:|---:|---:|
| BTC 2σ | 10,216.07 | 10,021.76 | 10,032.87 | 10,020.82 |
| BTC 3σ | 10,374.29 | 9,882.86 | 10,032.87 | 10,079.54 |
| ETH 2σ | 10,514.41 | 10,033.14 | 10,437.42 | 10,237.76 |
| ETH 3σ | 10,404.67 | 10,117.23 | 10,246.28 | 10,264.06 |
| HYPE 2σ | 10,024.79 | 10,182.61 | 10,343.68 | 10,523.16 |
| HYPE 3σ | 10,072.01 | 10,331.81 | 10,263.65 | 10,211.09 |

## Interpretation

These 72 portfolio runs broaden an already repeatedly explored short sample. Do not interpret the best cell as a validated choice. Timing changes which signals are available for subsequent entries, so balances can vary non-monotonically with the time limit.
The 240-minute fixed holds outperform fixed 120/180 holds for all six strategies in this sample. Among the tested target alternatives, HYPE 2σ / 200% / 240 minutes ends highest (10,523.16); it narrowly exceeds ETH 2σ fixed 240 minutes (10,514.41). The differences require fresh-data validation.
Extending a target below the original price may reduce hit rates, lengthen exposure and change entries. Minute sampled prices omit intraminute crossings. Each strategy is an independent alternative; no optimal mix or aggregate allocation has been selected.
Prices are quote units from repository samples labeled Binance, with exact instrument/currency provenance unverified. No funding, margin, liquidation, depth or actual execution costs are modeled. Remaining open positions close at the dataset end; forced-exit counts are in the summary CSV.

## Reproduce

```sh
python3 research/repo_baseline.py --capital 10000 --notional 10000 --rules expanded --output research/runs/expanded-10k
```

Input/source hashes and full settings are in expanded-10k-manifest.json; metrics for all alternatives are in expanded-10k-summary.csv. Large detailed ledgers and equity files are local ignored outputs.
