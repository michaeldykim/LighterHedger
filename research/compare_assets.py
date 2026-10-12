"""Verify downloaded Binance candles and compare the same short rules by asset."""
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hedger.sim_input import observations
from research.reversal_study import minute_prices, write_csv
from research.short_backtest import signals, backtest, plot

ROOT=Path(__file__).resolve().parent.parent


def read_archive(path, day):
    expected=path.with_suffix('.zip.CHECKSUM').read_text().split()[0]
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=expected:
        raise ValueError(f'Checksum mismatch: {path}')
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=1 or not names[0].endswith('.csv'):
            raise ValueError(f'Unexpected archive members: {path}')
        with archive.open(names[0]) as f:
            reader=csv.DictReader(io.TextIOWrapper(f))
            rows=list(reader)
    if len(rows)!=1440:
        raise ValueError(f'Expected 1440 minute candles: {path}')
    result=[]
    base=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    for i,row in enumerate(rows):
        opened=datetime.fromtimestamp(int(row['open_time'])/1000,timezone.utc)
        if opened!=base+timedelta(minutes=i):
            raise ValueError(f'Unexpected minute ordering: {path}:{i}')
        if int(row['close_time'])!=int(row['open_time'])+59999:
            raise ValueError(f'Unexpected candle duration: {path}:{i}')
        price=float(row['close'])
        if not 0<float(row['low'])<=price<=float(row['high']):
            raise ValueError(f'Invalid candle: {path}:{i}')
        closed=opened+timedelta(milliseconds=59999)
        result.append((closed.isoformat().replace('+00:00','Z'),row['close']))
    return result,digest


def prepare(asset):
    target=ROOT/'research/data'/asset
    target.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for d in range(2,9):
        day=f'2026-10-{d:02}'
        name=f'{asset}USDT-1m-{day}.zip'
        raw=ROOT/'research/data/binance_raw'/name
        rows,digest=read_archive(raw,day)
        source=f'binance_usdm_{asset}USDT_1m_close_USDT'
        stream=io.StringIO(newline='')
        writer=csv.writer(stream,lineterminator='\n')
        writer.writerow(['timestamp_utc','price_usd','source'])
        writer.writerows((t,p,source) for t,p in rows)
        output=target/f'{day}_{asset}.csv.zip'
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f'{day}_{asset}.csv',stream.getvalue())
        manifest.append(dict(asset=asset,day=day,rows=len(rows),sha256=digest,
            url=f'https://data.binance.vision/data/futures/um/daily/klines/{asset}USDT/1m/{name}',
            checksum_verified=True,normalized_path=str(output.relative_to(ROOT)),
            quote_currency='USDT',legacy_price_column='price_usd; numeric values remain USDT, not converted'))
    return minute_prices(observations(sorted(target.glob('*.zip')))),manifest


def main():
    output=ROOT/'research/asset_comparison'
    output.mkdir(parents=True,exist_ok=True)
    meta=json.loads((ROOT/'research/short_results/metadata.json').read_text())
    start=datetime.fromisoformat(meta['primary_segment_start'])
    end=datetime.fromisoformat(meta['primary_segment_end'])
    manifests=[]; summaries=[]; daily=[]
    for asset in ('BTC','ETH'):
        all_prices,manifest=prepare(asset)
        manifests.extend(manifest)
        prices={t:p for t,p in all_prices.items() if start<=t<=end}
        expected=int((end-start).total_seconds()/60)+1
        if len(prices)!=expected or min(prices)!=start or max(prices)!=end:
            raise ValueError('Incomplete common window')
        scores=signals(prices)
        folder=output/asset
        folder.mkdir(exist_ok=True)
        curves={}
        for k in (2,3):
            for cost in (0,2,5,10):
                summary,trades,equity=backtest(prices,scores,k,cost)
                summary.update(asset=asset,quote_currency='USDT',primary_start=start.isoformat(),primary_end=end.isoformat())
                summaries.append(summary)
                if cost==5:
                    curves[k]=equity
                    write_csv(folder/f'trades_{k}sigma.csv',trades)
                    write_csv(folder/f'equity_{k}sigma.csv',equity)
                    if any(t['held_minutes']!=60 or t['exit_reason']!='time_exit' for t in trades):
                        raise ValueError('Incomplete hold: examine end of sample or gaps')
                    for a,b in zip(trades,trades[1:]):
                        if a['exit_time']>b['entry_time']:
                            raise ValueError('Overlapping trades')
                    if abs(sum(t['net_pnl'] for t in trades)-summary['net_pnl'])>1e-7:
                        raise ValueError('P&L reconciliation failed')
                    for day in sorted(set(t['exit_time'][:10] for t in trades)):
                        selected=[t for t in trades if t['exit_time'][:10]==day]
                        daily.append(dict(asset=asset,threshold=k,exit_day_utc=day,trades=len(selected),net_pnl=sum(t['net_pnl'] for t in selected)))
        plot(curves,folder/'equity.svg')
    write_csv(output/'comparison.csv',summaries)
    write_csv(output/'daily.csv',daily)
    (output/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    (output/'sources.json').write_text(json.dumps(manifests,indent=2)+'\n')
    baseline=json.loads((ROOT/'research/short_results/summary.json').read_text())
    selected=[r for r in summaries if r['round_trip_cost_bps']==5]
    text=['# BTC and ETH: upward 2σ versus 3σ shorts','',
        'Same rules as the HYPE test: five-minute shock, 360 historical five-minute returns ending no later than the shock start, next-minute entry, 60-minute hold, one short at a time, no stop or take-profit. Starting capital and fixed entry notional are each 10,000 quote units; no compounding.','',
        f'Common sample: **{start.isoformat()} to {end.isoformat()}**, including a fresh volatility warmup. All primary trades completed their full 60-minute hold.','',
        '## Main results: 5 bps assumed round-trip costs','',
        '| Asset | Threshold | Trades | Net P&L | Return | Mean net bps/trade | Median net bps | Win rate | Max drawdown | Profit factor |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in selected:
        text.append(f'| {r["asset"]} | {r["threshold"]}σ | {r["trades"]} | {r["net_pnl"]:+.2f} | {r["return_pct"]:+.2f}% | {r["average_net_bps"]:+.2f} | {r["median_net_bps"]:+.2f} | {r["win_pct"]:.1f}% | {r["max_drawdown_pct"]:.2f}% | {r["profit_factor"]:.2f} |')
    text+=['','P&L for BTC/ETH is in USDT. No USDT/USD conversion is applied. The equity charts use a dollar symbol as a quote-unit shorthand.','',
        '## Cost sensitivity: net P&L in USDT','', '| Asset / threshold | 0 bps | 2 bps | 5 bps | 10 bps |','|---|---:|---:|---:|---:|']
    for asset in ('BTC','ETH'):
        for k in (2,3):
            text.append(f'| {asset} {k}σ | '+' | '.join(f'{next(r["net_pnl"] for r in summaries if r["asset"]==asset and r["threshold"]==k and r["round_trip_cost_bps"]==cost):+.2f}' for cost in (0,2,5,10))+' |')
    text+=['','## HYPE reference (previous run, same window)','', '| Threshold | Trades | Net P&L | Mean net bps/trade | Max drawdown |','|---|---:|---:|---:|---:|']
    for r in baseline:
        if r['round_trip_cost_bps']==5:
            text.append(f'| {r["threshold"]}σ | {r["trades"]} | {r["net_pnl"]:+.2f} | {r["average_net_bps"]:+.2f} | {r["max_drawdown_pct"]:.2f}% |')
    text+=['','## Equity curves','','### BTC','','![BTC equity](BTC/equity.svg)','','### ETH','','![ETH equity](ETH/equity.svg)','',
        '## Sources and limits','',
        '- [Binance public data documentation](https://github.com/binance/binance-public-data). Fourteen daily USD-M perpetual BTCUSDT/ETHUSDT one-minute candle ZIPs from October 2–8, 2026 were downloaded and verified against their published SHA-256 checksums. Each contains 1,440 ordered minute candles. Full URLs and hashes are in `sources.json`.',
        '- The BTC/ETH inputs are exchange candle closes in USDT. HYPE uses the last 10-second observation in each minute, labeled Binance, with its exact instrument type unverified. This is the same strategy and time window, but not identical source sampling or a guaranteed identical venue/instrument definition.',
        '- The window starts at HYPE’s uninterrupted segment on October 2 at 21:13 UTC. BTC/ETH data outside it are downloaded and retained, but excluded from these primary runs for comparability.',
        '- Costs are hypothetical combined fee/spread/slippage charges, split equally at entry and exit on entry notional. No funding, liquidation, order-book or market-impact model is included. Drawdown uses minute-close marks.',
        '- Tests use historical information for volatility and entry scheduling; all trades reconcile to final cash and do not overlap within a strategy. Data conversion preserves candle close availability and never assigns a close price to the candle open timestamp.',
        '- Only about six days of trading outcomes, with parameters selected after inspecting HYPE. No confidence claim, annualized return, or live-execution conclusion is warranted. No market-drift benchmark is included.',
        '', 'Reproduce after downloading the recorded archives: `.venv/bin/python research/compare_assets.py`.','']
    (output/'REPORT.md').write_text('\n'.join(text))
    print(json.dumps(selected,indent=2))

if __name__=='__main__':
    main()
