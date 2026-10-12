"""Causal, short-only comparison of upward 2/3 sigma crossings."""
import argparse
from collections import deque
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hedger.sim_input import observations
from research.reversal_study import minute_prices, write_csv


def signals(prices, move=5, window=360):
    history = deque(maxlen=window)
    segment = []
    previous = None
    result = {}
    for t, price in sorted(prices.items()):
        if previous is not None and t-previous != timedelta(minutes=1):
            history.clear()
            segment.clear()
        previous = t
        segment.append(price)
        if len(segment) >= 2*move+1:
            history.append(math.log(segment[-1-move]/segment[-1-2*move]))
        if len(history) == window:
            sigma = statistics.stdev(history)
            shock = math.log(price/segment[-1-move])
            if sigma > 0:
                result[t] = ((shock-statistics.mean(history))/sigma, shock)
    return result


def longest_segment(prices):
    segments = [[]]
    previous = None
    for t in sorted(prices):
        if previous is not None and t-previous != timedelta(minutes=1):
            segments.append([])
        segments[-1].append(t)
        previous = t
    return {t:prices[t] for t in max(segments,key=len)}


def backtest(prices, scores, threshold, cost_bps=5, capital=10000, notional=10000, hold=60,
             target_fraction=None):
    if target_fraction is not None and not 0 < target_fraction <= 1:
        raise ValueError('target_fraction must be in (0, 1]')
    cash = capital
    position = pending = None
    previous_z = None
    trades, equity = [], []
    peak = capital
    max_dd = 0
    max_dd_pct = 0
    skipped = canceled = target_skips = 0
    times = sorted(prices)
    half_cost = notional*cost_bps/20000

    def close(t, price, reason):
        nonlocal cash, position
        gross = position['quantity']*(position['entry_price']-price)
        cash += gross-half_cost
        net = gross-2*half_cost
        trades.append(dict(threshold=threshold, cost_bps=cost_bps,
            signal_time=position['signal_time'].isoformat(), z=position['z'],
            entry_time=position['entry_time'].isoformat(), exit_time=t.isoformat(),
            entry_price=position['entry_price'], exit_price=price, quantity=position['quantity'],
            gross_pnl=gross, costs=2*half_cost, net_pnl=net,
            net_bps=net/notional*10000, exit_reason=reason,
            target_price=position.get('target', ''),
            target_trigger_time=position['target_trigger'].isoformat() if position.get('target_trigger') else '',
            held_minutes=(t-position['entry_time']).total_seconds()/60))
        position = None

    for t in times:
        price = prices[t]
        if position and position.get('target_due') and t >= position['target_due']:
            close(t, price, 'target_exit')
        if position and t >= position['due']:
            close(t, price, 'time_exit' if t == position['due'] else 'delayed_gap_exit')
        if pending:
            if t == pending['entry_time']:
                if target_fraction is not None and price <= pending['target']:
                    target_skips += 1
                else:
                    position = dict(pending, entry_price=price, quantity=notional/price,
                                    due=t+timedelta(minutes=hold))
                    cash -= half_cost
            else:
                canceled += 1
            pending = None
        if t == times[-1] and position:
            close(t, price, 'end_of_data')
        if (position and target_fraction is not None and t > position['entry_time']
                and not position.get('target_due') and price <= position['target']):
            position['target_trigger'] = t
            position['target_due'] = t+timedelta(minutes=1)
        value = cash+(position['quantity']*(position['entry_price']-price) if position else 0)
        peak = max(peak, value)
        dd = peak-value
        max_dd = max(max_dd, dd)
        max_dd_pct = max(max_dd_pct, dd/peak*100)
        equity.append(dict(timestamp=t.isoformat(), equity=value, drawdown=dd,
                           price=price, position='short' if position else 'flat'))
        score = scores.get(t)
        if score is None:
            previous_z = None
            continue
        z, shock = score
        crossed = z >= threshold and shock > 0 and (previous_z is None or previous_z < threshold)
        previous_z = z
        if crossed:
            if position:
                skipped += 1
            elif t != times[-1]:
                pending = dict(signal_time=t, z=z, entry_time=t+timedelta(minutes=1))
                if target_fraction is not None:
                    pending['target'] = price-target_fraction*(price-prices[t-timedelta(minutes=5)])
    if pending:
        canceled += 1
    pnl = [r['net_pnl'] for r in trades]
    profits = sum(v for v in pnl if v > 0)
    losses = -sum(v for v in pnl if v < 0)
    summary = dict(threshold=threshold, round_trip_cost_bps=cost_bps, initial_capital=capital,
        fixed_entry_notional=notional, trades=len(trades), gross_pnl=sum(r['gross_pnl'] for r in trades),
        costs=sum(r['costs'] for r in trades), net_pnl=cash-capital, final_equity=cash,
        return_pct=(cash/capital-1)*100, max_drawdown=max_dd, max_drawdown_pct=max_dd_pct,
        win_pct=100*sum(v>0 for v in pnl)/len(pnl) if pnl else None,
        average_net_bps=statistics.mean(pnl)/notional*10000 if pnl else None,
        median_net_bps=statistics.median(pnl)/notional*10000 if pnl else None,
        profit_factor=profits/losses if losses else None,
        best_trade=min(trades, key=lambda r:-r['net_pnl'])['net_pnl'] if trades else None,
        worst_trade=min(pnl) if pnl else None, skipped_crossings_while_short=skipped,
        canceled_missing_entries=canceled, forced_final_exits=sum(r['exit_reason']=='end_of_data' for r in trades),
        delayed_exits=sum(r['exit_reason']=='delayed_gap_exit' for r in trades))
    summary.update(target_fraction=target_fraction, target_skipped_entries=target_skips,
                   target_exits=sum(r['exit_reason']=='target_exit' for r in trades),
                   mean_hold_minutes=statistics.mean(r['held_minutes'] for r in trades) if trades else None)
    return summary, trades, equity


def plot(curves, path):
    width, height = 1000, 360
    vals = [r['equity']-10000 for rows in curves.values() for r in rows]
    lo, hi = min(vals)-15, max(vals)+15
    start = datetime.fromisoformat(next(iter(curves.values()))[0]['timestamp'])
    end = datetime.fromisoformat(next(iter(curves.values()))[-1]['timestamp'])
    def x(t): return 85+860*(datetime.fromisoformat(t)-start).total_seconds()/(end-start).total_seconds()
    def y(v): return 290-220*(v-lo)/(hi-lo)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fafbfc"/><g font-family="Arial" fill="#172b40"><text x="35" y="32" font-size="21">Short reversal: cumulative P&amp;L after 5 bps round-trip costs</text>']
    for i in range(5):
        v = lo+(hi-lo)*i/4
        parts.append(f'<path d="M85 {y(v):.1f} H945" stroke="#dce3e9"/><text x="20" y="{y(v)+5:.1f}" font-size="13">${v:.0f}</text>')
    for k, color in [(2,'#147ca8'),(3,'#a6541e')]:
        points=' '.join(f'{x(r["timestamp"]):.1f},{y(r["equity"]-10000):.1f}' for r in curves[k])
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.7"/><text x="{650+(k-2)*150}" y="55" fill="{color}" font-size="15">{k} sigma</text>')
    parts.extend([f'<text x="85" y="320" font-size="13">{start:%b %d %H:%M} UTC</text>',f'<text x="790" y="320" font-size="13">{end:%b %d %H:%M} UTC</text>','<text x="85" y="345" font-size="12">$10,000 starting capital · $10,000 fixed entry notional · minute-close marks</text></g></svg>'])
    path.write_text(''.join(parts))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=Path('simulations/simulation_test'))
    p.add_argument('--asset', choices=('BTC','ETH','HYPE'), default='HYPE')
    p.add_argument('--output',type=Path,default=Path('research/short_results'))
    args=p.parse_args()
    paths=sorted(args.data.glob(f'*_{args.asset}.csv.zip'))
    rows=list(observations(paths))
    all_prices=minute_prices(rows)
    prices=longest_segment(all_prices)
    scores=signals(prices)
    args.output.mkdir(parents=True,exist_ok=True)
    full_scores=signals(all_prices)
    gap_sensitivity=[backtest(all_prices,full_scores,k,5)[0] for k in (2,3)]
    write_csv(args.output/'gap_affected_sensitivity.csv',gap_sensitivity)
    summaries=[]; curves={}; daily=[]
    for k in (2,3):
        for cost in (0,2,5,10):
            summary,trades,equity=backtest(prices,scores,k,cost)
            summaries.append(summary)
            if cost==5:
                curves[k]=equity
                write_csv(args.output/f'trades_{k}sigma.csv',trades)
                write_csv(args.output/f'equity_{k}sigma.csv',equity)
                for day in sorted(set(r['exit_time'][:10] for r in trades)):
                    selected=[r for r in trades if r['exit_time'][:10]==day]
                    daily.append(dict(threshold=k,exit_day_utc=day,trades=len(selected),
                        gross_pnl=sum(r['gross_pnl'] for r in selected),net_pnl=sum(r['net_pnl'] for r in selected)))
    write_csv(args.output/'comparison.csv',summaries)
    write_csv(args.output/'daily.csv',daily)
    (args.output/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    meta=dict(start=rows[0].label,end=rows[-1].label,rows=len(rows),sources=sorted(set(r.source for r in rows)),
        hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        primary_segment_start=min(prices).isoformat(), primary_segment_end=max(prices).isoformat(),
        primary_minute_closes=len(prices),segment_rule='longest uninterrupted minute-close segment',
        move_minutes=5,baseline_returns=360,entry_delay_minutes=1,holding_minutes=60,
        baseline_excludes_shock=True,price_basis='last observation in each minute',
        costs='fixed basis points of entry notional, half deducted at entry and half at exit',
        starting_capital=10000,fixed_entry_notional=10000,compounding=False,
        strategy='short positive-return upward z crossings only; one position; no stop or target')
    (args.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    plot(curves,args.output/'equity.svg')
    selected=[r for r in summaries if r['round_trip_cost_bps']==5]
    text=['# Upward-move short backtest: 2σ versus 3σ','',
        'Five-minute shocks, six-hour volatility baseline, next-minute entry, 60-minute hold. $10,000 starting capital and fixed $10,000 entry notional. Results below include an assumed 5 bps round-trip cost.','',
        f'Primary sample: {min(prices).isoformat()} through {max(prices).isoformat()}. The longest uninterrupted minute-close segment is used, with a fresh volatility warmup. The early October 2 segment is excluded because its subsequent outage prevents reliable timed exits.','',
        '| Metric | 2σ short | 3σ short |','|---|---:|---:|']
    for label,key,fmt in [('Trades','trades',',.0f'),('Gross P&L ($)','gross_pnl',',.2f'),('Costs ($)','costs',',.2f'),('Net P&L ($)','net_pnl',',.2f'),('Return (%)','return_pct','.2f'),('Average net trade (bps)','average_net_bps','.2f'),('Median net trade (bps)','median_net_bps','.2f'),('Net win rate (%)','win_pct','.1f'),('Profit factor','profit_factor','.2f'),('Max marked drawdown ($)','max_drawdown',',.2f'),('Max marked drawdown (%)','max_drawdown_pct','.2f'),('Best net trade ($)','best_trade','.2f'),('Worst net trade ($)','worst_trade','.2f')]:
        text.append('| '+label+' | '+' | '.join(format(r[key],fmt) if r[key] is not None else 'N/A' for r in selected)+' |')
    text+=['','![Marked equity curves](equity.svg)','','## Cost sensitivity','','| Round-trip cost | 2σ net P&L | 3σ net P&L |','|---|---:|---:|']
    for cost in (0,2,5,10):
        text.append(f'| {cost} bps | '+' | '.join(f'${next(r["net_pnl"] for r in summaries if r["threshold"]==k and r["round_trip_cost_bps"]==cost):,.2f}' for k in (2,3))+' |')
    text+=['','## Daily realized P&L at 5 bps','','| Exit date UTC | 2σ P&L | 3σ P&L |','|---|---:|---:|']
    for day in sorted(set(r['exit_day_utc'] for r in daily)):
        text.append('| '+day+' | '+' | '.join(f'${sum(r["net_pnl"] for r in daily if r["threshold"]==k and r["exit_day_utc"]==day):,.2f}' for k in (2,3))+' |')
    text+=['','## Gap sensitivity','',
        'Using all data and delaying exits until prices resume produces one roughly 15-hour trade in each strategy. These violate the intended 60-minute holding period and are excluded from the primary sample by selecting the uninterrupted segment. The gap-affected full-data net P&L is '+', '.join(f'{r["threshold"]}σ: ${r["net_pnl"]:,.2f}' for r in gap_sensitivity)+'. These inflated figures are not the headline result. See `gap_affected_sensitivity.csv`.','',
        '## Execution and interpretation','',
        '- Only upward positive-return shocks trigger trades. Negative shocks never block short entries. Counts therefore differ from the earlier event study, whose cooldown was shared across both directions.',
        '- Signals update every minute, including while short. Crossings during a trade are skipped, not queued. Close first when due; a fresh crossing at that close can schedule entry one minute later.',
        '- Volatility uses 360 preceding overlapping five-minute returns, all ending before or at the shock start. Reset warmup at missing minutes. No future-path filter is used to select trades.',
        '- Cancel an entry if the next minute is missing. An open position exits at the first available close at or after its deadline. Force any remaining position closed at the final available price. See exit reasons in trade logs.',
        '- Costs are a fixed charge on entry notional, split between entry and exit. They are hypothetical combined fee/spread/slippage assumptions, not verified exchange fees. Fixed notional does not compound and can exceed current equity slightly after losses.',
        '- Drawdown is marked at minute closes and includes entry/exit costs; intraminute extremes are unavailable. No stop loss, take profit, funding, liquidation or order-book simulation.',
        '- Seven days of Binance-labeled prices do not establish Lighter execution performance. Both candidates were chosen after inspecting this same dataset: results are in-sample and selection-biased. No market-drift benchmark or statistical significance claim is made.',
        '', 'Files: `comparison.csv`, `daily.csv`, `trades_2sigma.csv`, `trades_3sigma.csv`, minute equity files, `summary.json`, and `metadata.json`.','']
    (args.output/'REPORT.md').write_text('\n'.join(text))
    print(json.dumps(selected,indent=2))

if __name__=='__main__':
    main()
