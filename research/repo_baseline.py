"""Offline minute-close portfolios from the repository's sampled-price archives."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hedger.sim_input import observations
from research.reversal_study import minute_prices, write_csv
from research.short_backtest import backtest, longest_segment, signals

ASSETS = ('BTC', 'ETH', 'HYPE')
ROOT = Path(__file__).resolve().parents[1]


def load_asset(folder, asset):
    if asset not in ASSETS:
        raise ValueError('Unsupported asset')
    paths = sorted(folder.glob(f'*_{asset}.csv.zip'))
    if not paths:
        raise ValueError(f'No {asset} daily CSV ZIPs in {folder}')
    rows = list(observations(paths))
    intervals = Counter((b.timestamp-a.timestamp).total_seconds() for a,b in zip(rows,rows[1:]))
    manifest = dict(asset=asset, rows=len(rows), first=rows[0].label, last=rows[-1].label,
        source_labels=sorted({r.source for r in rows}),
        intervals_seconds={str(k):v for k,v in sorted(intervals.items())},
        files=[dict(path=str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths],
        provenance='Repository price_usd samples labeled binance; exact instrument and quote currency not independently verified.')
    return minute_prices(rows), manifest


def common_segment(series, end=None, warmup=370):
    common = set.intersection(*(set(prices) for prices in series.values()))
    if end is not None:
        common = {t for t in common if t <= end}
    if not common:
        raise ValueError('No common timestamps')
    segment = longest_segment({t:1 for t in common})
    if len(segment) < warmup+1:
        raise ValueError('Common segment too short for warmup and next-minute entry')
    return {asset:{t:prices[t] for t in segment} for asset,prices in series.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT/'simulations/simulation_test')
    parser.add_argument('--output', type=Path, required=True, help='New output folder; existing folders are never overwritten')
    parser.add_argument('--thresholds', type=int, nargs='+', choices=(2,3,4), default=[2,3])
    parser.add_argument('--move-minutes', type=int, default=5, help='Log-return and target reference lookback')
    parser.add_argument('--capital', type=float, default=1000, help='Starting equity per strategy')
    parser.add_argument('--notional', type=float, default=1000, help='Fixed entry notional; no compounding')
    parser.add_argument('--rules', choices=('all', '120-only', 'expanded'), default='all')
    parser.add_argument('--end', help='Inclusive UTC minute-close cutoff, e.g. 2026-10-09T00:00:00Z')
    args = parser.parse_args()
    if any(not math.isfinite(v) or v <= 0 for v in (args.capital,args.notional)):
        parser.error('--capital and --notional must be positive finite values')
    if args.move_minutes <= 0:
        parser.error('--move-minutes must be positive')
    rules = [('fixed120',120,None),('retrace100_cap120',120,1)]
    if args.rules == 'expanded':
        rules = [(f'fixed{h}',h,None) for h in (120,180,240)] + [
            (f'retrace{int(f*100)}_cap{h}',h,f) for h in (120,180,240) for f in (1,1.5,2,2.5,3)]
    if args.rules == 'all':
        rules.insert(0,('fixed60',60,None))
    end = datetime.fromisoformat(args.end.replace('Z','+00:00')) if args.end else None
    if end is not None and (end.utcoffset()!=timedelta(0) or end.second or end.microsecond):
        parser.error('--end must specify a UTC minute boundary')
    if args.output.exists():
        parser.error('--output already exists; choose a new run directory')
    manifests=[]; series={}
    for asset in ASSETS:
        series[asset],manifest=load_asset(args.data.resolve(),asset)
        manifests.append(manifest)
    series=common_segment(series,end,warmup=360+2*args.move_minutes)
    args.output.mkdir(parents=True)
    summaries=[]
    for asset,prices in series.items():
        scores=signals(prices,move=args.move_minutes)
        for threshold in sorted(set(args.thresholds)):
            for rule,hold,target in rules:
                s,trades,equity=backtest(prices,scores,threshold,capital=args.capital,notional=args.notional,
                                       cost_bps=5,hold=hold,target_fraction=target,move=args.move_minutes)
                s.update(asset=asset,rule=rule)
                if abs(sum(t['net_pnl'] for t in trades)-(s['final_equity']-args.capital))>1e-7:
                    raise ValueError('P&L reconciliation failure')
                if abs(equity[-1]['equity']-s['final_equity'])>1e-7:
                    raise ValueError('Equity reconciliation failure')
                if any(a['exit_time']>b['entry_time'] for a,b in zip(trades,trades[1:])):
                    raise ValueError('Overlapping strategy positions')
                summaries.append(s)
                prefix=args.output/f'{asset}_{threshold}sigma_{rule}'
                write_csv(Path(str(prefix)+'_trades.csv'),trades)
                write_csv(Path(str(prefix)+'_equity.csv'),equity)
    try:
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except (OSError,subprocess.CalledProcessError):
        revision='unavailable'
    source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [Path(__file__),ROOT/'research/short_backtest.py',ROOT/'research/reversal_study.py',ROOT/'hedger/sim_input.py',ROOT/'hedger/strategy.py']}
    first=next(iter(series.values()))
    metadata=dict(model='minute-close-short-v1',repository_revision=revision,source_sha256=source_hashes,
        primary_start=min(first).isoformat(),primary_end=max(first).isoformat(),minute_closes=len(first),
        segment_policy='Longest contiguous common minute-close segment after optional end cutoff; earliest wins ties',
        assets=manifests,capital_per_strategy=args.capital,fixed_entry_notional=args.notional,cost_bps=5,
        exit_rules=[r[0] for r in rules],
        move_minutes=args.move_minutes,baseline_returns=360,ddof=1,baseline_excludes_shock=True,
        thresholds=sorted(set(args.thresholds)),entry_delay_minutes=1,target_fill_delay_minutes=1,
        compounding=False,regimes='Each rule is an alternative portfolio, not an additional funded live strategy')
    (args.output/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (args.output/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    write_csv(args.output/'summary.csv',summaries)
    text=['# Repository minute-close baseline','',
          f'Common interval: {metadata["primary_start"]} to {metadata["primary_end"]}, including warmup.',
          f'Each independent strategy starts with {args.capital:,.0f} quote units, uses fixed {args.notional:,.0f} entry notional and 5 bps round-trip costs. No compounding.','',
          '| Asset | Threshold | '+' | '.join(r[0] for r in rules)+' |',
          '|---|---:|'+'---:|'*len(rules)]
    for asset in ASSETS:
        for threshold in sorted(set(args.thresholds)):
            group=[s for s in summaries if s['asset']==asset and s['threshold']==threshold]
            text.append(f'| {asset} | {threshold}σ | '+' | '.join(f'{s["final_equity"]:.2f}' for s in group)+' |')
    text+=['','## Interpretation','',
        'Inputs are approximately 10-second price observations, not independently verified exchange trade ticks. Source labels say Binance; instrument type and quote currency remain unverified. Prices are treated as quote units without currency conversion.',
        f'The signal uses completed minute closes (last observation in each minute), not tick crossings. The shock is a {args.move_minutes}-minute log return, normalized by 360 preceding overlapping {args.move_minutes}-minute returns, with the newest baseline return ending at the shock start. Warmup requires {360+2*args.move_minutes} contiguous closes. Retracement targets refer to the price {args.move_minutes} minutes before the signal. Target crossings execute at the following minute close; fixed time exits execute at their scheduled close. Positions are closed at data end, if necessary. See summary.json for forced-exit counts.',
        'Positions do not overlap within each strategy; new entry opportunities depend on its exit policy. Configurations shown are alternative backtests, not a recommended combined allocation. Costs are assumptions, with no funding, margin, liquidation, liquidity or intraminute extremes. This repeatedly explored short period is not an out-of-sample validation.',
        'The exact inputs, source-code hashes, cutoff, settings and repository revision are recorded in manifest.json. Large generated equity/trade files remain local and ignored by Git.','']
    (args.output/'REPORT.md').write_text('\n'.join(text))
    print('\n'.join(text[:13]))

if __name__=='__main__':
    main()
