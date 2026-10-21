from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import statistics
import unittest

from hedger.sim_input import Observation
from research.reversal_study import minute_prices, study, threshold_summary


class ReversalStudyTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Quiet alternating returns, then one large rally followed by a reversal.
        self.prices = {}
        p = 100
        for k in range(160):
            p *= math.exp(.0001 if k % 2 else -.0001)
            if k == 50:
                p *= 1.02
            if k == 52:
                p /= 1.01
            self.prices[self.start+timedelta(minutes=k)] = p

    def test_minute_close_uses_last_sample_and_preserves_gap(self):
        rows = [Observation(self.start+timedelta(seconds=s), Decimal(p), 'test')
                for s,p in [(0,'100'),(50,'101'),(120,'103')]]
        prices = minute_prices(rows)
        self.assertEqual(prices[self.start+timedelta(minutes=1)],101)
        self.assertNotIn(self.start+timedelta(minutes=2),prices)

    def test_baseline_excludes_shock_and_entry_is_delayed(self):
        events = study(self.prices, move=5, window=20, threshold=3)
        e = next(e for e in events if e['timestamp']==(self.start+timedelta(minutes=50)).isoformat())
        p=list(self.prices.values())
        baseline=[math.log(p[k]/p[k-5]) for k in range(26,46)]
        expected=(math.log(p[50]/p[45])-statistics.mean(baseline))/statistics.stdev(baseline)
        self.assertAlmostEqual(e['z'],expected)
        self.assertEqual(e['entry_price'],p[51])
        self.assertAlmostEqual(e['return_1m_bps'],-(p[52]/p[51]-1)*10000)
        self.assertGreater(e['return_1m_bps'],0)
        changed=dict(self.prices)
        changed[self.start+timedelta(minutes=52)]*=1.1
        other=study(changed,move=5,window=20,threshold=3)[0]
        self.assertEqual(e['z'],other['z'])

    def test_gaps_invalidate_outcomes_and_restart_warmup(self):
        prices=dict(self.prices)
        del prices[self.start+timedelta(minutes=55)]
        events=study(prices,move=5,window=20,threshold=3)
        self.assertFalse(any(e['timestamp']==(self.start+timedelta(minutes=50)).isoformat() for e in events))
        self.assertFalse(any(55 < (datetime.fromisoformat(e['timestamp'])-self.start).total_seconds()/60 < 85 for e in events))

    def test_costs_and_cooldown(self):
        events=study(self.prices,move=5,window=20,threshold=3)
        for a,b in zip(events,events[1:]):
            self.assertGreaterEqual(datetime.fromisoformat(b['timestamp'])-datetime.fromisoformat(a['timestamp']),timedelta(minutes=60))
        row=next(r for r in threshold_summary(events) if r['threshold']==3 and r['direction']=='both' and r['horizon_minutes']==1)
        self.assertAlmostEqual(row['net_5bps_cost'],row['mean_bps']-5)


if __name__ == '__main__':
    unittest.main()
