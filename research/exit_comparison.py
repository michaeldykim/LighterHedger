"""Compare exits on matched entries from the original 60-minute short strategy."""
import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hedger.sim_input import observations
from research.reversal_study import minute_prices, write_csv

ROOT=Path(__file__).resolve().parents[1]
HOLDS=(5,15,30,60,120)


def evaluate(prices, signal, entry, cost=5, fraction=.5, cap=60):
    """Common complete 120-minute sample; target eligible before comparison."""
    if not 0 < fraction <= 1 or cap not in HOLDS:
        raise ValueError("fraction must be in (0, 1] and cap must be a tested fixed hold")
    target=prices[signal]-fraction*(prices[signal]-prices[signal-timedelta(minutes=5)])
    entry_price=prices[entry]
    if entry_price<=target:
        return 'target_reached_before_entry', []
    if any(entry+timedelta(minutes=k) not in prices for k in range(121)):
        return 'incomplete_120m_path', []
    hit=next((k for k in range(1,cap) if prices[entry+timedelta(minutes=k)]<=target),None)
    exits=[(f'fixed_{h}m',h,'time',None) for h in HOLDS]
    exits.append((f'target_{fraction*100:g}pct_{cap}m',hit+1 if hit is not None else cap,
                  'target' if hit is not None else 'time',hit))
    rows=[]
    for rule,held,reason,trigger in exits:
        exit_time=entry+timedelta(minutes=held)
        gross=(1-prices[exit_time]/entry_price)*10000
        rows.append(dict(signal_time=signal.isoformat(),entry_time=entry.isoformat(),
            entry_price=entry_price,target_price=target,rule=rule,exit_time=exit_time.isoformat(),
            exit_price=prices[exit_time],held_minutes=held,exit_reason=reason,
            trigger_minutes=trigger if trigger is not None else '',gross_bps=gross,
            net_bps=gross-cost,net_pnl_10000=gross-cost))
    return 'included',rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fraction',type=float,default=.5)
    parser.add_argument('--cap',type=int,choices=HOLDS,default=60)
    parser.add_argument('--output',type=Path,default=None)
    args=parser.parse_args()
    if not 0 < args.fraction <= 1:
        parser.error('--fraction must be in (0, 1]')
    fraction,cap=args.fraction,args.cap
    target_rule=f'target_{fraction*100:g}pct_{cap}m'
    output=args.output or ROOT/'research'/('exit_results' if (fraction,cap)==(.5,60) else f'exit_results_{fraction*100:g}pct_{cap}m')
    output.mkdir(parents=True,exist_ok=True)
    all_rows=[]; exclusions=[]; summaries=[]; inputs={}
    for asset in ('HYPE','BTC','ETH'):
        folder=ROOT/'simulations/simulation_test' if asset=='HYPE' else ROOT/'research/data'/asset
        paths=sorted(folder.glob(f'*_{asset}.csv.zip'))
        prices=minute_prices(observations(paths))
        for path in paths:
            inputs[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        for threshold in (2,3):
            trades_path=(ROOT/'research/short_results' if asset=='HYPE' else ROOT/'research/asset_comparison'/asset)/f'trades_{threshold}sigma.csv'
            inputs[str(trades_path.relative_to(ROOT))]=hashlib.sha256(trades_path.read_bytes()).hexdigest()
            with trades_path.open() as f:
                trades=list(csv.DictReader(f))
            rows=[]
            for trade in trades:
                signal=datetime.fromisoformat(trade['signal_time'])
                entry=datetime.fromisoformat(trade['entry_time'])
                status,outcomes=evaluate(prices,signal,entry,fraction=fraction,cap=cap)
                if status!='included':
                    exclusions.append(dict(asset=asset,threshold=threshold,entry_time=entry.isoformat(),reason=status))
                    continue
                fixed=next(r for r in outcomes if r['rule']=='fixed_60m')
                if abs(fixed['net_bps']-float(trade['net_bps']))>1e-7:
                    raise ValueError('Original 60-minute result does not reconcile')
                cap_fixed=next(r for r in outcomes if r['rule']==f'fixed_{cap}m')
                for row in outcomes:
                    row.update(asset=asset,threshold=threshold,delta_vs_60m_bps=row['net_bps']-fixed['net_bps'],delta_vs_cap_bps=row['net_bps']-cap_fixed['net_bps'])
                rows.extend(outcomes)
            all_rows.extend(rows)
            for rule in [f'fixed_{h}m' for h in HOLDS]+[target_rule]:
                selected=[r for r in rows if r['rule']==rule]
                values=[r['net_bps'] for r in selected]
                summaries.append(dict(asset=asset,threshold=threshold,rule=rule,original_entries=len(trades),
                    matched_entries=len(values),mean_net_bps=statistics.mean(values),
                    median_net_bps=statistics.median(values),win_pct=100*sum(v>0 for v in values)/len(values),
                    mean_held_minutes=statistics.mean(r['held_minutes'] for r in selected),
                    mean_delta_vs_cap_bps=statistics.mean(r['delta_vs_cap_bps'] for r in selected),
                    mean_delta_vs_60m_bps=statistics.mean(r['delta_vs_60m_bps'] for r in selected),
                    outperform_60m_pct=100*sum(r['delta_vs_60m_bps']>0 for r in selected)/len(selected),
                    target_exits=sum(r['exit_reason']=='target' for r in selected),
                    mean_net_at_10bps=statistics.mean(values)-5))
    write_csv(output/'trades.csv',all_rows)
    write_csv(output/'summary.csv',summaries)
    # Explicit schema even if no exclusions.
    with (output/'exclusions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['asset','threshold','entry_time','reason'])
        w.writeheader();w.writerows(exclusions)
    (output/'metadata.json').write_text(json.dumps(dict(input_sha256=inputs,
        cost_bps=5,entry_notional=10000,holds=HOLDS,target_fraction=fraction,target_cap_minutes=cap,
        target_trigger_fill_delay_minutes=1,selection='same original entries; exclude already-hit targets and incomplete 120m paths for every rule'),indent=2)+'\n')
    text=[f'# Fixed holding periods versus a {fraction*100:g}% retracement exit ({cap}-minute limit)','',
        '**Matched-entry exit study.** Every rule uses the same eligible entries from the original short-only 60-minute backtests. Five basis points round-trip costs, 10,000 quote-unit position per trade. Positive values favor the short.','',
        '## Mean net return per trade (basis points)','',
        f'| Asset | Threshold | Matched / original entries | 5 min | 15 min | 30 min | 60 min | 120 min | {fraction*100:g}% target / {cap} min |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for asset in ('HYPE','BTC','ETH'):
        for k in (2,3):
            group=[r for r in summaries if r['asset']==asset and r['threshold']==k]
            text.append(f'| {asset} | {k}σ | {group[0]["matched_entries"]} / {group[0]["original_entries"]} | '+' | '.join(f'{r["mean_net_bps"]:+.2f}' for r in group)+' |')
    text+=['',f'## Target versus {cap}-minute exit, paired on identical trades','',
        f'| Asset | Threshold | Target mean net bps | Change vs {cap}m | Target median net bps | Target win rate | Target exits / trades | Mean hold |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        if r['rule']==target_rule:
            text.append(f'| {r["asset"]} | {r["threshold"]}σ | {r["mean_net_bps"]:+.2f} | {r["mean_delta_vs_cap_bps"]:+.2f} | {r["median_net_bps"]:+.2f} | {r["win_pct"]:.1f}% | {r["target_exits"]} / {r["matched_entries"]} | {r["mean_held_minutes"]:.1f} min |')
    text+=['','## Rules and interpretation','',
        f'- For a signal at t, target = price at t − {fraction:g} × (price at t − price at t−5 minutes). This target is fixed; it is not recomputed as prices move.',
        '- If entry price is at or below target, exclude that entry from ALL rules to retain a matched sample. The exclusions file records every removal. This comparison therefore measures exit quality on target-eligible trades rather than the full original strategy.',
        f'- Observe target at minute closes strictly after entry. A target observed at minute k is filled at minute k+1 at the actual observed price, which may be worse than the target. A target observed at minute {cap-1} can fill at {cap}. Otherwise close at entry+{cap} minutes. There is no intraminute target fill assumption.',
        '- Fixed holds exit at the pre-scheduled minute close, as in the prior backtests. The target has one-minute reaction latency because its crossing is only known after that observation.',
        '- Require a complete 120-minute forward path for every included entry and every rule. This is explicit research sample matching, not a rule that uses future availability to place live trades.',
        '- Keep the original 60-minute strategy’s entry schedule. Earlier exits do not permit extra entries in this study; 120-minute outcomes can overlap later entries. Do not interpret sums as a one-position portfolio return. No portfolio drawdown or annualized metric is reported.',
        '- All costs are 5 bps per completed trade. At 10 bps costs subtract another 5 bps from every mean. Equal costs cancel in paired exit differences. Funding is excluded, so holding-period-dependent funding costs are not represented.',
        '- BTC/ETH prices and position amounts are USDT; HYPE retains its original USD-labeled data. Source sampling differs as documented in the asset comparison.',
        '- This is the same short sample already used for parameter exploration. Selecting the best holding time adds selection bias. A later full-strategy run must recompute entries as positions free up, followed by validation on new dates.',
        '', f'Reproduce: `.venv/bin/python research/exit_comparison.py --fraction {fraction:g} --cap {cap}`. Detailed outcomes, paired differences and exclusions are saved beside this report.','']
    (output/'REPORT.md').write_text('\n'.join(text))
    print('\n'.join(text[:14]))
    print('Exclusions:',json.dumps(exclusions))

if __name__=='__main__':
    main()
