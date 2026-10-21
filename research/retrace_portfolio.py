"""One-position 100% retracement/120-minute versus fixed-120 portfolios."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hedger.sim_input import observations
from research.reversal_study import minute_prices,write_csv
from research.short_backtest import signals,backtest
ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'research/retrace100_portfolio'
    out.mkdir(parents=True,exist_ok=True)
    prior=json.loads((ROOT/'research/short_results/metadata.json').read_text())
    start=datetime.fromisoformat(prior['primary_segment_start'])
    end=datetime.fromisoformat(prior['primary_segment_end'])
    summaries=[]; hashes={}; daily=[]
    for asset in ('HYPE','BTC','ETH'):
        folder=ROOT/'simulations/simulation_test' if asset=='HYPE' else ROOT/'research/data'/asset
        paths=sorted(folder.glob(f'*_{asset}.csv.zip'))
        for p in paths:
            hashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
        prices={t:p for t,p in minute_prices(observations(paths)).items() if start<=t<=end}
        if len(prices)!=int((end-start).total_seconds()/60)+1:
            raise ValueError('Missing minutes in common sample')
        scores=signals(prices)
        for k in (2,3):
            for rule,fraction in [('fixed120',None),('retrace100',1.0)]:
                s,trades,equity=backtest(prices,scores,k,hold=120,target_fraction=fraction)
                s.update(asset=asset,rule=rule)
                summaries.append(s)
                if abs(sum(t['net_pnl'] for t in trades)-(equity[-1]['equity']-10000))>1e-7:
                    raise ValueError('P&L reconciliation failure')
                for a,b in zip(trades,trades[1:]):
                    if a['exit_time']>b['entry_time']:
                        raise ValueError('Positions overlap')
                for trade in trades:
                    if trade['held_minutes']>120:
                        raise ValueError('Late exit')
                    if trade['exit_reason']=='target_exit':
                        trigger=datetime.fromisoformat(trade['target_trigger_time'])
                        if datetime.fromisoformat(trade['exit_time'])-trigger!=timedelta(minutes=1):
                            raise ValueError('Target latency error')
                stem=f'{asset}_{k}sigma_{rule}'
                write_csv(out/f'{stem}_trades.csv',trades)
                write_csv(out/f'{stem}_equity.csv',equity)
                for day in sorted(set(t['exit_time'][:10] for t in trades)):
                    chosen=[t for t in trades if t['exit_time'][:10]==day]
                    daily.append(dict(asset=asset,threshold=k,rule=rule,exit_day_utc=day,
                        trades=len(chosen),net_pnl=sum(t['net_pnl'] for t in chosen)))
    write_csv(out/'summary.csv',summaries)
    write_csv(out/'daily.csv',daily)
    (out/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    (out/'metadata.json').write_text(json.dumps(dict(start=start.isoformat(),end=end.isoformat(),
        input_sha256=hashes,capital_per_strategy=10000,fixed_entry_notional=10000,cost_bps=5,
        move_minutes=5,baseline_returns=360,hold_cap=120,target_fraction=1,
        target_fill_delay_minutes=1,compounding=False,position_limit=1),indent=2)+'\n')
    text=['# 100% retracement versus fixed 120-minute hold','',
        f'Common data window: {start.isoformat()} to {end.isoformat()}, including volatility warmup. Each row is an independent account starting with 10,000 quote units. Fixed position notional 10,000; no compounding; assumed 5 bps round-trip costs.','',
        '| Asset | Threshold | Fixed 120 ending equity | 100% target ending equity | Target minus fixed | Fixed / target trades | Fixed / target max drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for asset in ('HYPE','BTC','ETH'):
        for k in (2,3):
            a,b=[s for s in summaries if s['asset']==asset and s['threshold']==k]
            text.append(f'| {asset} | {k}σ | {a["final_equity"]:,.2f} | {b["final_equity"]:,.2f} | {b["final_equity"]-a["final_equity"]:+,.2f} | {a["trades"]} / {b["trades"]} | {a["max_drawdown_pct"]:.2f}% / {b["max_drawdown_pct"]:.2f}% |')
    text+=['','## Execution rules','',
        '- The same five-minute positive-return upward z-score crossings, with lagged 360-return volatility and next-minute entry, are used for both portfolios. Signals update while a trade is open; crossings while open are discarded. After closing, a fresh crossing may schedule the next entry.',
        '- The 100% target is the price five minutes before the signal. Example: a move from 100 to 102 targets 100. Fix this price at the signal; do not trail it.',
        '- For the target portfolio, skip entry when its observed entry price has already reached or fallen below the target; no transaction cost is charged. The fixed-hold portfolio has no target eligibility filter.',
        '- Only one position can be open. Target crossing is observed at a minute close after entry and filled at the next minute close, even if price rebounds. Exit no later than 120 minutes after entry; fixed-hold exits are pre-scheduled at that same deadline. Force remaining positions closed at end of data.',
        '- This is a portfolio simulation with its own entry schedule for each exit policy. It does not sum overlapping matched-entry outcomes. Earlier target exits can permit more trades. Changes reflect both exits and the resulting entry selection.',
        '- Each completed trade uses fixed 10,000 entry notional and 5 quote units total costs, split at entry/exit. Positions do not compound. After losses this notional can slightly exceed current equity. No funding, margin/liquidation, stop loss, or liquidity model is included.',
        '- BTC/ETH amounts are USDT; HYPE uses USD-labeled samples. No USDT conversion is applied. Drawdowns use minute closes and exclude unseen intraminute extremes.',
        '- These dates and parameters have already been explored repeatedly. Results are in-sample and do not establish a live edge. The target portfolios and fixed portfolios are separate alternatives, not a combined allocation.',
        '', '## Exit counts','', '| Asset | Threshold | Target exits | Time exits | End-of-data exits | Target-entry skips | Mean target hold |','|---|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        if s['rule']=='retrace100':
            text.append(f'| {s["asset"]} | {s["threshold"]}σ | {s["target_exits"]} | {s["trades"]-s["target_exits"]-s["forced_final_exits"]} | {s["forced_final_exits"]} | {s["target_skipped_entries"]} | {s["mean_hold_minutes"]:.1f} min |')
    text+=['','Reproduce: `.venv/bin/python research/retrace_portfolio.py`. Summary, daily realized P&L, trade ledgers, marked equity and input hashes are saved alongside this report.','']
    (out/'REPORT.md').write_text('\n'.join(text))
    print('\n'.join(text[:12]))

if __name__=='__main__':
    main()
