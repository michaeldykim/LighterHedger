"""Offline, dependency-free price reversal event study. Run from repo root."""
import argparse
from collections import deque
import csv
from datetime import timedelta
import html
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hedger.sim_input import observations

HORIZONS = (1, 5, 15, 30, 60)
BUCKETS = ('1–1.5', '1.5–2', '2–2.5', '2.5–3', '≥3')


def bucket(z):
    return BUCKETS[min(4, int((abs(z) - 1) / .5))]


def minute_prices(rows):
    """Last sampled price in each minute, timestamped at minute close.

    Missing minutes remain missing. Never interpolate across a data outage.
    """
    result = {}
    for row in rows:
        close = row.timestamp.replace(second=0, microsecond=0) + timedelta(minutes=1)
        result[close] = float(row.price)
    return result


def study(prices, move=5, window=360, cooldown=60, threshold=1):
    times = sorted(prices)
    events = []
    history = deque(maxlen=window)
    segment = []
    previous = None
    last_event = None
    previous_z = None
    for t in times:
        if previous is not None and t - previous != timedelta(minutes=1):
            history.clear()
            segment = []
            previous_z = None
        previous = t
        segment.append(prices[t])
        # At time t, the newest baseline return ends at t-move.
        if len(segment) >= 2 * move + 1:
            history.append(math.log(segment[-1-move] / segment[-1-2*move]))
        if len(history) < window:
            continue
        mean = statistics.mean(history)
        sigma = statistics.stdev(history)
        if sigma <= 0:
            previous_z = None
            continue
        shock = math.log(segment[-1] / segment[-1-move])
        z = (shock - mean) / sigma
        crossing = abs(z) >= threshold and (previous_z is None or abs(previous_z) < threshold or z * previous_z < 0)
        previous_z = z
        if not crossing or (last_event is not None and t-last_event < timedelta(minutes=cooldown)):
            continue
        last_event = t
        # Missing future data excludes scoring, but must not alter the cooldown.
        if any(t + timedelta(minutes=k) not in prices for k in range(1, max(HORIZONS)+2)):
            continue
        direction = -1 if z > 0 else 1
        entry_t = t + timedelta(minutes=1)
        entry = prices[entry_t]
        event = dict(threshold=threshold, timestamp=t.isoformat(), day=t.date().isoformat(), direction='up' if z > 0 else 'down',
                     sigma_bucket=bucket(z), z=z, shock_bps=shock*10000,
                     baseline_sigma_bps=sigma*10000, signal_price=prices[t], entry_time=entry_t.isoformat(), entry_price=entry)
        for h in HORIZONS:
            path = [direction * (prices[entry_t+timedelta(minutes=k)] / entry - 1)*10000 for k in range(h+1)]
            event[f'return_{h}m_bps'] = path[-1]
            event[f'favorable_{h}m_bps'] = max(path)
            event[f'adverse_{h}m_bps'] = min(path)
        start = prices[t-timedelta(minutes=move)]
        for fraction in (.25, .5, 1):
            target = prices[t] + fraction * (start-prices[t])
            hits = [k for k in range(1,61) if direction*(prices[t+timedelta(minutes=k)]-target) >= 0]
            event[f'retrace_{int(fraction*100)}_minutes'] = min(hits) if hits else ''
        events.append(event)
    return events


def summarize(events, daily=False):
    result = []
    groups = sorted(set(e['day'] for e in events)) if daily else BUCKETS
    for group in groups:
        for direction in ('up', 'down'):
            selected = [e for e in events if e['direction']==direction and e['day' if daily else 'sigma_bucket']==group]
            for h in HORIZONS:
                values = [e[f'return_{h}m_bps'] for e in selected]
                row = {'day' if daily else 'sigma_bucket': group, 'direction': direction, 'horizon_minutes': h, 'events': len(values)}
                if values:
                    row.update(mean_bps=statistics.mean(values), median_bps=statistics.median(values),
                               win_pct=100*sum(v>0 for v in values)/len(values),
                               mean_favorable_bps=statistics.mean(e[f'favorable_{h}m_bps'] for e in selected),
                               mean_adverse_bps=statistics.mean(e[f'adverse_{h}m_bps'] for e in selected))
                    for cost in (2,5,10):
                        row[f'net_{cost}bps_cost'] = statistics.mean(values)-cost
                result.append(row)
    return result


def threshold_summary(events):
    result = []
    for threshold in (1, 1.5, 2, 2.5, 3):
        for direction in ('up', 'down', 'both'):
            selected = [e for e in events if e['threshold']==threshold and (direction=='both' or e['direction']==direction)]
            for h in HORIZONS:
                values = [e[f'return_{h}m_bps'] for e in selected]
                row = dict(threshold=threshold, direction=direction, horizon_minutes=h, events=len(values))
                if values:
                    row.update(mean_bps=statistics.mean(values), median_bps=statistics.median(values),
                               win_pct=100*sum(v>0 for v in values)/len(values),
                               mean_favorable_bps=statistics.mean(e[f'favorable_{h}m_bps'] for e in selected),
                               mean_adverse_bps=statistics.mean(e[f'adverse_{h}m_bps'] for e in selected))
                    for cost in (2,5,10):
                        row[f'net_{cost}bps_cost'] = statistics.mean(values)-cost
                    for fraction in (25,50,100):
                        hits=[e[f'retrace_{fraction}_minutes'] for e in selected if e[f'retrace_{fraction}_minutes']!='']
                        row[f'retrace_{fraction}_pct_within_60m']=100*len(hits)/len(selected)
                        row[f'median_retrace_{fraction}_minutes_if_hit']=statistics.median(hits) if hits else ''
                result.append(row)
    return result


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('simulations/simulation_test'))
    parser.add_argument('--output', type=Path, default=Path('research/results'))
    args = parser.parse_args()
    paths = sorted(args.data.glob('*_HYPE.csv.zip'))
    rows = list(observations(paths))
    prices = minute_prices(rows)
    events = study(prices)
    summary = summarize(events)
    threshold_events = events + [e for threshold in (1.5,2,2.5,3) for e in study(prices, threshold=threshold)]
    thresholds = threshold_summary(threshold_events)
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output/'events.csv', events)
    write_csv(args.output/'summary.csv', summary)
    write_csv(args.output/'daily.csv', summarize(events, daily=True))
    write_csv(args.output/'threshold_events.csv', threshold_events)
    write_csv(args.output/'threshold_summary.csv', thresholds)
    write_csv(args.output/'threshold_daily.csv', [dict(threshold=k, **r) for k in (1,1.5,2,2.5,3)
              for r in summarize([e for e in threshold_events if e['threshold']==k], daily=True)])
    metadata = dict(observations=len(rows), minute_closes=len(prices), start=rows[0].label, end=rows[-1].label,
                    sources=sorted(set(r.source for r in rows)), events=len(events), move_minutes=5,
                    baseline_returns=360, cooldown_minutes=60, files=[str(p) for p in paths],
                    input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    thresholds=[1,1.5,2,2.5,3], horizons_minutes=HORIZONS,
                    assumed_round_trip_costs_bps=[2,5,10], entry_delay_minutes=1,
                    independent_threshold_event_counts={str(k):sum(e['threshold']==k for e in threshold_events) for k in (1,1.5,2,2.5,3)})
    (args.output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    body = ['<h1>HYPE reversal event study</h1>', f'<p>{len(events)} distinct events · {html.escape(rows[0].label)} to {html.escape(rows[-1].label)}</p>',
            '<p>Mean gross reversal return in basis points. Each cell includes event count. Red is negative; green is positive. Blank cells have no events.</p>']
    body.append('<h2>Independent threshold experiments</h2><p>Each row tests a separate entry threshold with its own cooldown. Rows share some events and must not be pooled. Returns combine buy and short events; direction details are in threshold_summary.csv. Subtract 5 bps from a cell to see the average after a hypothetical 5 bps round-trip cost.</p><p>These are descriptive event returns, not a portfolio equity curve. The 60-minute cooldown is shared across directions within each experiment, even for shorter holding periods. The results have not been adjusted for market drift or compared against matched random entry times.</p>')
    body.append('<table><tr><th>Entry threshold</th>'+''.join(f'<th>{h} min</th>' for h in HORIZONS)+'</tr>')
    for threshold in (1,1.5,2,2.5,3):
        body.append(f'<tr><th>±{threshold}σ</th>')
        for h in HORIZONS:
            r=next(r for r in thresholds if r['threshold']==threshold and r['direction']=='both' and r['horizon_minutes']==h)
            if r['events']:
                v=r['mean_bps']; color='#d2ece3' if v>=0 else '#f6d8d8'
                body.append(f'<td style="background:{color}">{v:+.1f}<small>n = {r["events"]}</small></td>')
            else:
                body.append('<td>—<small>n = 0</small></td>')
        body.append('</tr>')
    body.append('</table><p><a href="threshold_summary.csv">Threshold statistics</a> · <a href="threshold_events.csv">Threshold events</a> · <a href="threshold_daily.csv">Threshold results by day</a></p><h2>Magnitude at the first 1σ crossing</h2>')
    for direction in ('up','down'):
        body.append(f'<h2>{"Short after an upward move" if direction=="up" else "Buy after a downward move"}</h2><table><tr><th>Move size</th>'+''.join(f'<th>{h} min</th>' for h in HORIZONS)+'</tr>')
        for b in BUCKETS:
            body.append(f'<tr><th>{b}σ</th>')
            for h in HORIZONS:
                r = next(r for r in summary if r['sigma_bucket']==b and r['direction']==direction and r['horizon_minutes']==h)
                if r['events']:
                    v=r['mean_bps']; color='#d2ece3' if v>=0 else '#f6d8d8'
                    body.append(f'<td style="background:{color}">{v:+.1f}<small>n = {r["events"]}</small></td>')
                else:
                    body.append('<td>—<small>n = 0</small></td>')
            body.append('</tr>')
        body.append('</table>')
    body.append('<h2>Interpretation and assumptions</h2><p>Events are first crossings of ±1σ, bucketed by magnitude at that crossing, with a 60-minute global cooldown. This deliberately avoids repeated signals from one shock, but does not test independent 2σ or 3σ threshold strategies: gradual moves may cross 1σ first. Larger threshold strategies need a separate run per threshold.</p><p>Prices are last observations within each minute. Entry uses the following minute close. Five-minute log returns are standardized against 360 preceding five-minute returns, with the newest baseline return ending at the start of the shock. These overlapping baseline returns are not 360 independent samples. Warmup restarts after missing minutes. All events require a complete 61-minute future path.</p><p>Returns are unlevered, fixed-entry-notional price returns. Favorable/adverse excursions use minute samples and may miss intraminute extremes. Retracements are measured from signal price toward the pre-shock price, within 60 minutes of the signal. The CSV summaries subtract hypothetical 2, 5, and 10 basis-point round-trip costs; these are sensitivity assumptions, not verified exchange fees. No funding or liquidity model is included.</p><p>This is descriptive exploration of seven days, not an out-of-sample strategy result. No confidence intervals or annualized Sharpe are reported. Review daily.csv for day concentration and collect additional weeks before selecting a strategy.</p><p><a href="summary.csv">Summary CSV</a> · <a href="events.csv">Event details</a> · <a href="daily.csv">By day</a> · <a href="metadata.json">Run metadata</a></p>')
    (args.output/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>HYPE reversal research</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#203040;background:#fafbfc}table{border-collapse:collapse;width:100%;margin-bottom:30px}th,td{padding:14px;text-align:center;border:4px solid #fafbfc}th{background:#e9edf2}small{display:block;font-size:11px;margin-top:5px}p{line-height:1.6}</style>'+''.join(body))
    print(json.dumps(metadata, indent=2))
    for h in HORIZONS:
        vals=[e[f'return_{h}m_bps'] for e in events]
        if vals: print(f'{h}m: mean {statistics.mean(vals):+.2f} bps, median {statistics.median(vals):+.2f} bps, n={len(vals)}')


if __name__ == '__main__':
    main()
