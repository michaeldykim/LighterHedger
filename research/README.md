# Offline sigma-reversal research

This directory is independent of the live fixed-strike hedger. It does not read
credentials, submit exchange orders or send notifications. Python 3.11+ standard
library is sufficient for the new repository-data runner.

## Supported repository-data workflow

From the repository root:

```sh
python3 research/repo_baseline.py --end 2026-10-09T00:00:00Z --output research/runs/original-window
python3 research/repo_baseline.py --output research/runs/extended-window
```

For the full-window 10,000-capital / 10,000-notional comparison focused on
120-minute exits:

```sh
python3 research/repo_baseline.py --capital 10000 --notional 10000 --rules 120-only --output research/runs/extended-10k-120
```

For all fixed 120/180/240-minute holds and 100/150/200/250/300% targets with each limit:

```sh
python3 research/repo_baseline.py --capital 10000 --notional 10000 --rules expanded --output research/runs/expanded-10k
```

A retracement beyond 100% targets a price below the original five-minute move's
starting price. See [expanded exit results](baselines/EXPANDED_EXITS.md).

Capital and notional are independent positive finite settings. Defaults remain
1,000 each; `--rules all` includes the fixed-60 comparator. These are research
run parameters, not changes to the six agreed live implementation budgets.

Use a new output directory per run; existing runs are never overwritten. The
runner selects `*_BTC.csv.zip`, `*_ETH.csv.zip` and `*_HYPE.csv.zip` separately
from `simulations/simulation_test` (override with `--data`). It validates each
asset's input with the existing strict offline loader, intersects minute-close
timestamps and selects the longest uninterrupted common interval. Earliest
wins equal-length ties. Missing minutes are not interpolated; a long outage
removes that segment from the primary comparison. Inspect the manifest for
raw observation intervals, gaps, source labels and exact selected coverage.

Every run compares thresholds 2 and 3, fixed 60/120-minute exits and full
retracement with a 120-minute cap. Capital and fixed notional are each 1,000
quote units per independent strategy, without compounding, with 5 bps costs.
Signal: five-minute log return normalized by 360 preceding five-minute returns
ending at or before the shock start; sample standard deviation (ddof=1), 370
contiguous closes for warmup. Short positive-return upward threshold crossings;
next-minute entry. One position; update crossing state while holding and discard
entry signals while occupied. Full retracement targets the price five minutes
before the signal, with next-minute fills after target detection. Entry already
at/below target is skipped. Time limit starts at entry. Final positions are
closed at the final data observation, flagged in summaries.

Outputs: `REPORT.md`, `summary.csv`, `summary.json`, `manifest.json`, and separate
trade/equity files for each asset/threshold/exit policy. Manifest hashes identify
input archives and calculation source code, including uncommitted changes;
`repository_revision` alone is not a claim of a clean source snapshot. New runs
are local artifacts. See [checked-in baseline results](baselines/README.md) for
the full-window comparison through October 11 first, followed by the earlier
window through October 8. The full-window endpoint October 12 00:00 UTC labels
the close of October 11’s final minute, not an additional day of data.

Large generated files and downloaded duplicate datasets are ignored. The
repository's already tracked sampled-price ZIPs remain the authoritative inputs;
this change adds no copies. Track only code/tests, methodology, and small baseline
summaries/manifests. Source label `binance` is not proof of a particular spot or
perpetual instrument. Quote currency remains unverified; no conversion is made.

The legacy `hedger.simulate` folder workflow expects a single asset with all its
ZIPs in time order. Do not point that CLI at the now-mixed sample folder: select
one asset into a separate simulation folder, or use the research runner above.
No change to that simulator or live hedger is part of this research integration.

Validation:

```sh
TMPDIR=/private/tmp python3 -m unittest discover -s tests
```

The full suite requires the existing project dependencies. Research-only tests
can run separately with `-p 'test_research_input.py'`, `test_reversal_study.py`,
`test_short_backtest.py`, `test_asset_comparison.py`, or `test_exit_comparison.py`.
Use a real temporary path for TMPDIR on other platforms; macOS symlink aliases
otherwise affect an existing simulator path assertion.

## Earlier experiment workflows

The following scripts reproduce earlier research and may require local artifacts
or external datasets from the standalone archive. They are not prerequisites for
the supported repository-data runner. Old published reports used 10,000 capital
unless explicitly stated otherwise; they are not live configuration defaults.


## 100% retracement portfolio comparison

Run `.venv/bin/python research/retrace_portfolio.py` for independent one-position
accounts comparing a fixed 120-minute hold against a full retracement target
with a 120-minute limit. Results are in `research/retrace100_portfolio`.
Each starts with 10,000 quote units and fixed 10,000 entry notional, with 5 bps
round-trip costs. Entries are recalculated as positions close, so these ending
balances are not sums of the earlier overlapping matched-entry outcomes.
The target is the price five minutes before the signal, observed on minute
closes and executed one minute later. Positions remaining at sample end close
at the final available price. See the report for source and execution limits.

## Matched-entry exit comparison

Run `.venv/bin/python research/exit_comparison.py` after the short-only and
asset comparisons. It compares 5/15/30/60/120-minute holds with a fixed 50%
retracement target and a 60-minute deadline, on the original entry schedules.
Targets trigger at minute closes and execute at the next minute's price.
Entries whose target was already reached are removed from every alternative;
all alternatives also require the same complete 120-minute price path.
Results, paired trade details, exclusions and input hashes are written under
`research/exit_results`. This isolates exits; it is not a portfolio simulation
with entries rescheduled after earlier exits, and 120-minute outcomes can overlap.

For the 75% retracement target with a 120-minute deadline, run:

```sh
.venv/bin/python research/exit_comparison.py --fraction .75 --cap 120
```

That run saves separately to `research/exit_results_75pct_120m`. Target eligibility
is recalculated, so compare rules within each run on their matched samples;
the 50% and 75% experiments need not contain identical entries. The report pairs
the target with the fixed hold matching its deadline, while retaining all five
fixed-hold alternatives. `--output PATH` can override the destination.

## BTC and ETH comparison

```sh
.venv/bin/python research/compare_assets.py
```

Reads the retained Binance USD-M BTCUSDT and ETHUSDT daily 1-minute archives
in `research/data/binance_raw`, verifies their published SHA-256 checksums,
and converts candle closes into the loader format under `research/data/BTC`
and `research/data/ETH`. The legacy `price_usd` column holds USDT prices here;
no currency conversion is applied. Source labels identify that distinction.

Both strategies run on the same uninterrupted window as the existing HYPE
comparison. Results and source URLs are saved to `research/asset_comparison`.
See `REPORT.md`, `sources.json`, and each asset's trade logs and equity curves.
The script reads HYPE's `research/short_results/metadata.json` for the common
window. It performs no downloads or exchange actions when rerun.

## Short-only portfolio comparison

```sh
.venv/bin/python research/short_backtest.py
```

This compares upward 2σ and 3σ crossings with next-minute entry, 60-minute
holds, and one short position at a time. Outputs go to `research/short_results`:
`REPORT.md`, an SVG equity chart, trade logs, marked equity, daily P&L and cost
sensitivity. The primary sample is the longest uninterrupted minute-price
segment; the full-data run with delayed gap exits is saved separately.
Capital and fixed entry notional are both $10,000, without compounding.
Costs of 0, 2, 5 and 10 basis points round trip are hypothetical assumptions.
No stop, target, funding or liquidity model is included. Optional `--data` and
`--output` arguments select alternative input and output folders.

## Event study

Run the offline study from the repository root:

```sh
.venv/bin/python research/reversal_study.py
```

Optional `--data PATH` selects a folder of daily ZIPs; `--output PATH` selects
the results directory. Existing research output files at that path are replaced.
No exchange connections or credentials are used. Python's standard library is
sufficient. The existing live strategy and replay simulator are unchanged.

Open `results/report.html` for the heatmaps. `threshold_summary.csv` is the main
comparison: separate 1, 1.5, 2, 2.5 and 3 sigma crossing experiments. Each has an
independent 60-minute cooldown. `threshold_events.csv` contains the underlying
signals and outcomes, and `threshold_daily.csv` breaks results down by day and
direction. Threshold experiments share observations; do not pool their events.

The secondary `summary.csv`, `events.csv` and `daily.csv` describe magnitudes at
the first 1-sigma crossing, rather than independent higher-threshold strategies.
`metadata.json` records inputs, hashes and research parameters.

## Method

- Use the last sample in each UTC minute, available at that minute's end.
- Measure the five-minute log return. Subtract the historical mean and divide
  by the sample standard deviation of 360 preceding five-minute log returns.
  The newest baseline return ends at the start of the measured shock. The
  overlapping baseline returns use 365 minute closes, not 360 independent
  observations. The first eligible signal needs 370 consecutive minute closes.
- Reset warmup after a missing minute. No interpolation. A gap within an
  otherwise populated minute is not detected by the minute-level continuity rule.
- Trigger on the first crossing of either signed threshold from inside it,
  or on a crossing to the opposite sign. Record only after a 60-minute cooldown;
  do not enter a still-active crossing simply because the cooldown expired.
- Enter at the next minute close: short upward shocks, buy downward shocks.
- Measure fixed-entry-notional simple returns over 1, 5, 15, 30 and 60 minutes
  from entry. Positive values favor reversal. One basis point is 0.01%.
- Require all 61 forward minute closes for scoring, giving the same sample at
  each horizon. An unscorable event still starts the cooldown, preventing future
  availability from changing signal selection.
- Measure maximum favorable/adverse excursion from entry using minute closes.
  Retracement times start at the signal and target 25%, 50%, or 100% of the
  original price move, with a 60-minute deadline. Conditional median retracement
  time excludes failures; read it alongside the hit percentage.
- Subtract hypothetical round-trip costs of 2, 5 and 10 bps. Funding, depth,
  spreads, latency and liquidation are unavailable. Costs are sensitivity inputs,
  not verified venue charges. Source labels say Binance; execution on Lighter
  cannot be inferred from this dataset.

## Interpretation

This is an exploratory event study, not a validated strategy backtest. No
parameter selection, held-out evaluation or portfolio sizing is performed.
Cooldown limits overlap but does not establish statistical independence. Daily
regimes, market drift, repeated comparisons and a short sample remain material.
In particular, stronger short-side returns may reflect the market's direction.
The heatmap color encodes the sign of the mean, not statistical significance.

Next steps are collecting more weeks, comparing matched random-time entries,
testing volatility-window and entry-delay sensitivity, and evaluating a fixed
candidate chronologically out of sample. Avoid selecting the best cell from this
week and treating its return as an expected live return.

Validation:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_reversal_study.py' -v
```

Tests cover lagged volatility, delayed entry, return direction, missing-data
handling, cooldown and transaction-cost arithmetic.
