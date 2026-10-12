# Expanded exits: full available window through October 11

Each alternative starts with 10,000 quote units and uses fixed 10,000 entry notional, without compounding. All balances include 5 bps round-trip costs. These are full portfolios: one short at a time per alternative and fresh entry selection as positions close.

Raw dates: October 2–11 UTC. Primary continuous window: October 2 21:13 UTC through October 12 00:00 UTC (the final close of October 11), including volatility warmup.

Targets: 100%, 150%, 200%, 250%, and 300%. Target = signal price − fraction × (signal price − price five minutes before signal). For a rise from 100 to 102, target prices are 100, 99, 98, 97, and 96, respectively. These are retracements of the original move, not trade percentage returns. Target crossings execute at the following sampled minute close; otherwise exit at the stated limit.

## 120-minute limit

| Strategy | Fixed hold | 100% retrace | 150% retrace | 200% retrace | 250% retrace | 300% retrace |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 9,996.28 | 10,017.22 | 9,944.63 | 10,004.07 | 9,992.63 | 10,036.20 |
| BTC 3σ | 10,061.05 | 9,893.33 | 10,035.11 | 10,061.79 | 10,168.74 | 9,986.31 |
| ETH 2σ | 10,457.05 | 9,816.90 | 10,298.90 | 10,232.61 | 10,310.24 | 10,401.12 |
| ETH 3σ | 10,247.04 | 9,953.15 | 10,045.91 | 10,068.78 | 10,160.30 | 10,188.90 |
| HYPE 2σ | 9,960.06 | 10,130.06 | 10,048.57 | 10,047.14 | 9,966.51 | 9,998.41 |
| HYPE 3σ | 9,774.00 | 10,324.86 | 10,190.78 | 10,155.73 | 9,725.35 | 9,757.78 |

## 180-minute limit

| Strategy | Fixed hold | 100% retrace | 150% retrace | 200% retrace | 250% retrace | 300% retrace |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,015.93 | 9,953.27 | 9,962.05 | 9,900.09 | 9,830.67 | 9,956.89 |
| BTC 3σ | 10,013.43 | 9,912.74 | 9,941.76 | 9,951.62 | 9,978.64 | 9,973.78 |
| ETH 2σ | 10,461.37 | 9,812.53 | 10,221.68 | 10,091.88 | 10,188.43 | 10,369.68 |
| ETH 3σ | 10,019.11 | 9,968.02 | 10,068.66 | 10,108.49 | 10,209.17 | 10,208.36 |
| HYPE 2σ | 9,393.14 | 10,035.92 | 10,210.24 | 10,380.70 | 10,132.59 | 10,024.48 |
| HYPE 3σ | 9,855.21 | 10,495.47 | 10,279.47 | 10,262.82 | 9,802.49 | 9,820.91 |

## 240-minute limit

| Strategy | Fixed hold | 100% retrace | 150% retrace | 200% retrace | 250% retrace | 300% retrace |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,216.07 | 10,021.76 | 10,032.87 | 10,020.82 | 10,077.64 | 10,081.57 |
| BTC 3σ | 10,374.29 | 9,882.86 | 10,032.87 | 10,079.54 | 10,205.12 | 10,085.63 |
| ETH 2σ | 10,514.41 | 10,033.14 | 10,437.42 | 10,237.76 | 10,264.35 | 10,410.81 |
| ETH 3σ | 10,404.67 | 10,117.23 | 10,246.28 | 10,264.06 | 10,384.06 | 10,425.87 |
| HYPE 2σ | 10,024.79 | 10,182.61 | 10,343.68 | 10,523.16 | 10,426.04 | 10,134.85 |
| HYPE 3σ | 10,072.01 | 10,331.81 | 10,263.65 | 10,211.09 | 10,140.24 | 9,995.51 |

## Highest observed balance per strategy (descriptive, not selected live settings)

| Strategy | Rule | Ending balance | Trades | Max marked drawdown |
|---|---|---:|---:|---:|
| BTC 2σ | fixed240 | 10,216.07 | 37 | 4.43% |
| BTC 3σ | fixed240 | 10,374.29 | 24 | 3.18% |
| ETH 2σ | fixed240 | 10,514.41 | 37 | 4.38% |
| ETH 3σ | retrace300_cap240 | 10,425.87 | 21 | 2.67% |
| HYPE 2σ | retrace200_cap240 | 10,523.16 | 54 | 5.70% |
| HYPE 3σ | retrace100_cap180 | 10,495.47 | 28 | 2.72% |

## Interpretation

These 108 portfolio runs broaden an already repeatedly explored short sample. Choosing the best cell creates selection bias. The best-result table is descriptive and is not a validated configuration recommendation.
Outcomes do not improve monotonically with target depth or hold length. Early exits change the next available entry signals; larger targets also change hit rates and holding time. HYPE 3σ favors full retracement capped at 180 minutes in this sample, while ETH 3σ favors 300% capped at 240 minutes. Fresh data are needed before drawing conclusions about stability.
Minute sampled prices omit intraminute crossings. Each strategy is an independent alternative; no optimal mix or combined allocation has been selected.
Prices are quote units from repository samples labeled Binance, with exact instrument/currency provenance unverified. No funding, margin, liquidation, depth or actual execution costs are modeled. Remaining open positions close at the dataset end; forced-exit counts are in the summary CSV.

## Reproduce

```sh
python3 research/repo_baseline.py --capital 10000 --notional 10000 --rules expanded --output research/runs/expanded-10k-wide
```

Input/source hashes and full settings are in expanded-10k-manifest.json; metrics for all alternatives are in expanded-10k-summary.csv. Large detailed ledgers and equity files are local ignored outputs.
