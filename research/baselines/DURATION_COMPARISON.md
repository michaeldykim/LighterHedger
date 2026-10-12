# Log-return duration comparison: 5, 10 and 15 minutes

Same repository sampled-price data through October 11, UTC. Common uninterrupted segment October 2 21:13 through October 12 00:00 (the last minute close of October 11). Each independent alternative starts with 10,000 and fixed 10,000 entry notional, without compounding, after 5 bps round-trip costs.

Every duration uses 360 overlapping historical returns of that SAME duration, with the newest return ending at the current move start. Targets reference the start of the selected-duration move. Hence this compares complete strategy definitions, including target distances and signal frequency; entries are not held fixed. Warmup requires 370, 380, or 390 closes, respectively. Different earliest eligibility is explicitly retained. No trading or liquidation assumptions were changed.

## Fixed-hold ending balances (identical exit rules across durations)

| Strategy | Hold | 5-minute signal | 10-minute signal | 15-minute signal |
|---|---:|---:|---:|---:|
| BTC 2σ | 120 min | 9,996.28 | 9,939.34 | 9,635.42 |
| BTC 2σ | 180 min | 10,015.93 | 10,010.72 | 10,139.87 |
| BTC 2σ | 240 min | 10,216.07 | 10,202.70 | 10,227.99 |
| BTC 3σ | 120 min | 10,061.05 | 10,031.21 | 10,082.24 |
| BTC 3σ | 180 min | 10,013.43 | 10,227.71 | 10,201.09 |
| BTC 3σ | 240 min | 10,374.29 | 10,148.95 | 10,269.50 |
| ETH 2σ | 120 min | 10,457.05 | 10,249.05 | 9,850.37 |
| ETH 2σ | 180 min | 10,461.37 | 10,086.61 | 10,509.82 |
| ETH 2σ | 240 min | 10,514.41 | 10,621.93 | 10,705.64 |
| ETH 3σ | 120 min | 10,247.04 | 10,436.41 | 10,329.92 |
| ETH 3σ | 180 min | 10,019.11 | 10,414.70 | 10,427.91 |
| ETH 3σ | 240 min | 10,404.67 | 10,495.66 | 10,515.60 |
| HYPE 2σ | 120 min | 9,960.06 | 9,817.35 | 9,619.29 |
| HYPE 2σ | 180 min | 9,393.14 | 9,919.24 | 9,320.23 |
| HYPE 2σ | 240 min | 10,024.79 | 10,070.29 | 9,544.14 |
| HYPE 3σ | 120 min | 9,774.00 | 10,146.15 | 10,059.53 |
| HYPE 3σ | 180 min | 9,855.21 | 10,224.98 | 10,259.61 |
| HYPE 3σ | 240 min | 10,072.01 | 10,329.07 | 9,803.05 |

## Breadth across the 108 exit/strategy combinations

This is a descriptive sensitivity grid, not 108 independent observations or a portfolio recommendation. Median ending equity treats all six asset/threshold identities and all 18 exits equally; alternatives share many underlying trades.

| Duration | Profitable combinations | Median ending equity | Configurations beating the same 5-minute rule |
|---|---:|---:|---:|
| 5 min | 77/108 | 10,074.83 | reference |
| 10 min | 84/108 | 10,159.09 | 61/108 |
| 15 min | 71/108 | 10,084.20 | 53/108 |

## Median ending equity across all 18 exits, by strategy

| Strategy | 5 min | 10 min | 15 min |
|---|---:|---:|---:|
| BTC 2σ | 10,010.00 | 9,943.60 | 9,914.15 |
| BTC 3σ | 10,023.15 | 10,056.80 | 10,109.18 |
| ETH 2σ | 10,281.62 | 10,247.85 | 10,121.93 |
| ETH 3σ | 10,174.60 | 10,239.79 | 10,338.19 |
| HYPE 2σ | 10,089.32 | 10,082.70 | 9,710.99 |
| HYPE 3σ | 10,147.98 | 10,303.90 | 10,097.72 |

## 5-minute signal: all exit configurations

### 120-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 9,996.28 | 10,017.22 | 9,944.63 | 10,004.07 | 9,992.63 | 10,036.20 |
| BTC 3σ | 10,061.05 | 9,893.33 | 10,035.11 | 10,061.79 | 10,168.74 | 9,986.31 |
| ETH 2σ | 10,457.05 | 9,816.90 | 10,298.90 | 10,232.61 | 10,310.24 | 10,401.12 |
| ETH 3σ | 10,247.04 | 9,953.15 | 10,045.91 | 10,068.78 | 10,160.30 | 10,188.90 |
| HYPE 2σ | 9,960.06 | 10,130.06 | 10,048.57 | 10,047.14 | 9,966.51 | 9,998.41 |
| HYPE 3σ | 9,774.00 | 10,324.86 | 10,190.78 | 10,155.73 | 9,725.35 | 9,757.78 |

### 180-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,015.93 | 9,953.27 | 9,962.05 | 9,900.09 | 9,830.67 | 9,956.89 |
| BTC 3σ | 10,013.43 | 9,912.74 | 9,941.76 | 9,951.62 | 9,978.64 | 9,973.78 |
| ETH 2σ | 10,461.37 | 9,812.53 | 10,221.68 | 10,091.88 | 10,188.43 | 10,369.68 |
| ETH 3σ | 10,019.11 | 9,968.02 | 10,068.66 | 10,108.49 | 10,209.17 | 10,208.36 |
| HYPE 2σ | 9,393.14 | 10,035.92 | 10,210.24 | 10,380.70 | 10,132.59 | 10,024.48 |
| HYPE 3σ | 9,855.21 | 10,495.47 | 10,279.47 | 10,262.82 | 9,802.49 | 9,820.91 |

### 240-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,216.07 | 10,021.76 | 10,032.87 | 10,020.82 | 10,077.64 | 10,081.57 |
| BTC 3σ | 10,374.29 | 9,882.86 | 10,032.87 | 10,079.54 | 10,205.12 | 10,085.63 |
| ETH 2σ | 10,514.41 | 10,033.14 | 10,437.42 | 10,237.76 | 10,264.35 | 10,410.81 |
| ETH 3σ | 10,404.67 | 10,117.23 | 10,246.28 | 10,264.06 | 10,384.06 | 10,425.87 |
| HYPE 2σ | 10,024.79 | 10,182.61 | 10,343.68 | 10,523.16 | 10,426.04 | 10,134.85 |
| HYPE 3σ | 10,072.01 | 10,331.81 | 10,263.65 | 10,211.09 | 10,140.24 | 9,995.51 |


## 10-minute signal: all exit configurations

### 120-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 9,939.34 | 9,895.75 | 9,928.55 | 9,947.87 | 10,136.89 | 10,049.21 |
| BTC 3σ | 10,031.21 | 9,878.94 | 10,054.74 | 10,082.56 | 10,217.67 | 10,081.03 |
| ETH 2σ | 10,249.05 | 9,926.08 | 10,234.29 | 10,455.08 | 10,457.22 | 10,384.71 |
| ETH 3σ | 10,436.41 | 10,148.39 | 10,224.98 | 10,234.15 | 10,260.88 | 10,304.11 |
| HYPE 2σ | 9,817.35 | 10,335.09 | 10,429.36 | 10,222.71 | 9,829.92 | 9,900.62 |
| HYPE 3σ | 10,146.15 | 10,182.70 | 10,278.73 | 10,195.19 | 10,167.00 | 10,187.85 |

### 180-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,010.72 | 9,800.50 | 9,912.10 | 9,845.63 | 9,880.05 | 9,924.76 |
| BTC 3σ | 10,227.71 | 9,958.44 | 10,058.86 | 9,912.48 | 10,051.05 | 10,125.13 |
| ETH 2σ | 10,086.61 | 9,938.24 | 10,149.01 | 10,246.64 | 10,061.01 | 10,012.58 |
| ETH 3σ | 10,414.70 | 10,162.03 | 10,199.79 | 10,174.62 | 10,147.02 | 10,222.29 |
| HYPE 2σ | 9,919.24 | 9,904.06 | 10,081.01 | 10,116.32 | 9,648.40 | 9,785.79 |
| HYPE 3σ | 10,224.98 | 10,187.15 | 10,422.35 | 10,462.19 | 10,617.96 | 10,491.26 |

### 240-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,202.70 | 9,930.80 | 9,979.26 | 10,019.77 | 10,111.93 | 10,059.28 |
| BTC 3σ | 10,148.95 | 9,925.83 | 10,016.67 | 10,015.73 | 10,156.15 | 10,105.94 |
| ETH 2σ | 10,621.93 | 10,163.86 | 10,293.69 | 10,487.38 | 10,377.61 | 10,286.43 |
| ETH 3σ | 10,495.66 | 10,170.16 | 10,255.02 | 10,245.44 | 10,271.54 | 10,408.35 |
| HYPE 2σ | 10,070.29 | 10,267.85 | 10,441.35 | 10,420.29 | 10,084.39 | 10,340.54 |
| HYPE 3σ | 10,329.07 | 10,125.42 | 10,529.79 | 10,628.99 | 10,602.11 | 10,599.17 |


## 15-minute signal: all exit configurations

### 120-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 9,635.42 | 9,860.82 | 9,866.73 | 9,903.02 | 9,788.10 | 9,635.42 |
| BTC 3σ | 10,082.24 | 10,012.02 | 10,166.79 | 10,271.07 | 10,117.70 | 10,100.66 |
| ETH 2σ | 9,850.37 | 9,864.52 | 10,026.86 | 10,054.49 | 10,170.41 | 10,107.60 |
| ETH 3σ | 10,329.92 | 10,281.61 | 10,364.47 | 10,334.75 | 10,438.86 | 10,329.92 |
| HYPE 2σ | 9,619.29 | 9,933.15 | 9,941.82 | 9,704.76 | 9,717.22 | 9,562.27 |
| HYPE 3σ | 10,059.53 | 10,094.08 | 10,333.91 | 10,080.38 | 10,086.17 | 10,059.53 |

### 180-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,139.87 | 9,918.02 | 9,904.97 | 9,962.42 | 9,910.27 | 9,868.43 |
| BTC 3σ | 10,201.09 | 9,959.97 | 10,054.72 | 10,179.95 | 10,077.98 | 10,150.33 |
| ETH 2σ | 10,509.82 | 10,048.88 | 10,086.73 | 10,045.66 | 10,136.25 | 10,153.89 |
| ETH 3σ | 10,427.91 | 10,186.48 | 10,222.39 | 10,207.42 | 10,341.63 | 10,262.42 |
| HYPE 2σ | 9,320.23 | 9,726.05 | 9,521.01 | 9,554.03 | 9,451.14 | 9,354.42 |
| HYPE 3σ | 10,259.61 | 10,005.48 | 10,417.55 | 10,383.44 | 10,386.14 | 10,419.78 |

### 240-minute exit limit

| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |
|---|---:|---:|---:|---:|---:|---:|
| BTC 2σ | 10,227.99 | 9,959.91 | 9,998.51 | 10,147.02 | 10,066.41 | 10,050.94 |
| BTC 3σ | 10,269.50 | 9,934.33 | 10,015.23 | 10,157.75 | 10,086.93 | 10,218.92 |
| ETH 2σ | 10,705.64 | 10,063.94 | 10,193.22 | 10,195.95 | 10,274.69 | 10,304.00 |
| ETH 3σ | 10,515.60 | 10,246.40 | 10,360.37 | 10,360.29 | 10,498.07 | 10,436.07 |
| HYPE 2σ | 9,544.14 | 10,040.01 | 9,946.33 | 9,908.96 | 9,820.82 | 9,868.98 |
| HYPE 3σ | 9,803.05 | 9,891.49 | 10,240.44 | 10,300.68 | 10,101.36 | 9,926.14 |

## Interpretation and reproduction

Performance by duration and exit is highly variable. Comparing all exits reduces emphasis on a selected best cell but does not remove repeated-search bias. No duration is established as reliably profitable from these repeatedly explored dates. A new time interval and a fixed configuration are needed for validation.
Returns are in unverified quote units from prices labeled Binance. No funding, exchange constraints, actual spread/depth, liquidation or intraminute target detection is modeled. Targets execute one minute after an observed crossing. One position per strategy; different exits change subsequent entries. End-of-data positions close at the final observed price.
Run each duration, then this report builder:

```sh
python3 research/repo_baseline.py --move-minutes 5 --capital 10000 --notional 10000 --rules expanded --output research/runs/compare-duration-5
python3 research/repo_baseline.py --move-minutes 10 --capital 10000 --notional 10000 --rules expanded --output research/runs/compare-duration-10
python3 research/repo_baseline.py --move-minutes 15 --capital 10000 --notional 10000 --rules expanded --output research/runs/compare-duration-15
python3 research/duration_comparison.py
```

Input and calculation-source hashes are preserved in duration-{5,10,15}-manifest.json. Full metrics are in the corresponding summary CSVs. Large generated trades/equity are ignored by Git.
