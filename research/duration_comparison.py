"""Summarize 5/10/15-minute runs with matched exit configurations."""
import argparse
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',type=Path,default=ROOT/'research/runs')
    parser.add_argument('--output',type=Path,default=ROOT/'research/baselines')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    rows={}; meta={}
    for move in (5,10,15):
        folder=args.runs/f'compare-duration-{move}'
        rows[move]=json.loads((folder/'summary.json').read_text())
        meta[move]=json.loads((folder/'manifest.json').read_text())
        assert meta[move]['move_minutes']==move
        assert meta[move]['capital_per_strategy']==meta[move]['fixed_entry_notional']==10000
        assert meta[move]['cost_bps']==5
        assert len(rows[move])==108
        for name in ('manifest.json','summary.csv'):
            (args.output/f'duration-{move}-{name}').write_text((folder/name).read_text())
    for move in (10,15):
        for key in ('primary_start','primary_end','minute_closes','exit_rules','assets'):
            if meta[move][key]!=meta[5][key]:
                raise ValueError('Runs do not share data and exit configurations')
    def lookup(move,asset,k,rule):
        return next(r for r in rows[move] if (r['asset'],r['threshold'],r['rule'])==(asset,k,rule))
    text=['# Log-return duration comparison: 5, 10 and 15 minutes','',
          'Same repository sampled-price data through October 11, UTC. Common uninterrupted segment October 2 21:13 through October 12 00:00 (the last minute close of October 11). Each independent alternative starts with 10,000 and fixed 10,000 entry notional, without compounding, after 5 bps round-trip costs.','',
          'Every duration uses 360 overlapping historical returns of that SAME duration, with the newest return ending at the current move start. Targets reference the start of the selected-duration move. Hence this compares complete strategy definitions, including target distances and signal frequency; entries are not held fixed. Warmup requires 370, 380, or 390 closes, respectively. Different earliest eligibility is explicitly retained. No trading or liquidation assumptions were changed.','',
          '## Fixed-hold ending balances (identical exit rules across durations)','',
          '| Strategy | Hold | 5-minute signal | 10-minute signal | 15-minute signal |','|---|---:|---:|---:|---:|']
    for asset in ('BTC','ETH','HYPE'):
        for k in (2,3):
            for cap in (120,180,240):
                text.append(f'| {asset} {k}σ | {cap} min | '+' | '.join(f'{lookup(move,asset,k,f"fixed{cap}")["final_equity"]:,.2f}' for move in (5,10,15))+' |')
    text+=['','## Breadth across the 108 exit/strategy combinations','',
           'This is a descriptive sensitivity grid, not 108 independent observations or a portfolio recommendation. Median ending equity treats all six asset/threshold identities and all 18 exits equally; alternatives share many underlying trades.','',
           '| Duration | Profitable combinations | Median ending equity | Configurations beating the same 5-minute rule |','|---|---:|---:|---:|']
    for move in (5,10,15):
        profitable=sum(r['final_equity']>10000 for r in rows[move])
        better=sum(r['final_equity']>lookup(5,r['asset'],r['threshold'],r['rule'])['final_equity'] for r in rows[move])
        text.append(f'| {move} min | {profitable}/108 | {statistics.median(r["final_equity"] for r in rows[move]):,.2f} | {str(better)+"/108" if move!=5 else "reference"} |')
    text+=['','## Median ending equity across all 18 exits, by strategy','',
           '| Strategy | 5 min | 10 min | 15 min |','|---|---:|---:|---:|']
    for asset in ('BTC','ETH','HYPE'):
        for k in (2,3):
            text.append(f'| {asset} {k}σ | '+' | '.join(f'{statistics.median(r["final_equity"] for r in rows[m] if r["asset"]==asset and r["threshold"]==k):,.2f}' for m in (5,10,15))+' |')
    for move in (5,10,15):
        text+=[f'','## {move}-minute signal: all exit configurations','']
        for cap in (120,180,240):
            text += [f'### {cap}-minute exit limit','', '| Strategy | Fixed hold | 100% | 150% | 200% | 250% | 300% |','|---|---:|---:|---:|---:|---:|---:|']
            for asset in ('BTC','ETH','HYPE'):
                for k in (2,3):
                    rules=[f'fixed{cap}']+[f'retrace{f}_cap{cap}' for f in (100,150,200,250,300)]
                    text.append(f'| {asset} {k}σ | '+' | '.join(f'{lookup(move,asset,k,rule)["final_equity"]:,.2f}' for rule in rules)+' |')
            text+=['']
    text+=['## Interpretation and reproduction','',
           'Performance by duration and exit is highly variable. Comparing all exits reduces emphasis on a selected best cell but does not remove repeated-search bias. No duration is established as reliably profitable from these repeatedly explored dates. A new time interval and a fixed configuration are needed for validation.',
           'Returns are in unverified quote units from prices labeled Binance. No funding, exchange constraints, actual spread/depth, liquidation or intraminute target detection is modeled. Targets execute one minute after an observed crossing. One position per strategy; different exits change subsequent entries. End-of-data positions close at the final observed price.',
           'Run each duration, then this report builder:', '', '```sh',
           'python3 research/repo_baseline.py --move-minutes 5 --capital 10000 --notional 10000 --rules expanded --output research/runs/compare-duration-5',
           'python3 research/repo_baseline.py --move-minutes 10 --capital 10000 --notional 10000 --rules expanded --output research/runs/compare-duration-10',
           'python3 research/repo_baseline.py --move-minutes 15 --capital 10000 --notional 10000 --rules expanded --output research/runs/compare-duration-15',
           'python3 research/duration_comparison.py', '```','',
           'Input and calculation-source hashes are preserved in duration-{5,10,15}-manifest.json. Full metrics are in the corresponding summary CSVs. Large generated trades/equity are ignored by Git.','']
    (args.output/'DURATION_COMPARISON.md').write_text('\n'.join(text))
    print('\n'.join(text[:42]))

if __name__=='__main__':
    main()
