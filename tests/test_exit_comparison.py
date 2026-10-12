from datetime import datetime, timedelta, timezone
import unittest
from research.exit_comparison import evaluate

class ExitComparisonTests(unittest.TestCase):
    def setUp(self):
        self.signal=datetime(2026,1,1,0,5,tzinfo=timezone.utc)
        self.entry=self.signal+timedelta(minutes=1)
        self.prices={self.signal+timedelta(minutes=k):102 for k in range(-5,123)}
        self.prices[self.signal-timedelta(minutes=5)]=100

    def target(self,prices=None):
        status,rows=evaluate(prices or self.prices,self.signal,self.entry)
        self.assertEqual(status,'included')
        return next(r for r in rows if r['rule']=='target_50pct_60m')

    def test_target_executes_next_price_not_trigger_price(self):
        self.prices[self.entry+timedelta(minutes=3)]=100.9
        self.prices[self.entry+timedelta(minutes=4)]=101.5
        row=self.target()
        self.assertEqual(row['target_price'],101)
        self.assertEqual(row['held_minutes'],4)
        self.assertEqual(row['exit_price'],101.5)
        self.assertAlmostEqual(row['net_bps'],(1-101.5/102)*10000-5)

    def test_target_already_hit_excludes_all_rules(self):
        self.prices[self.entry]=101
        self.assertEqual(evaluate(self.prices,self.signal,self.entry),('target_reached_before_entry',[]))

    def test_timeout_and_last_minute_target(self):
        self.assertEqual(self.target()['exit_reason'],'time')
        self.assertEqual(self.target()['held_minutes'],60)
        self.prices[self.entry+timedelta(minutes=59)]=101
        self.assertEqual(self.target()['exit_reason'],'target')
        self.assertEqual(self.target()['held_minutes'],60)

    def test_common_path_and_fixed_120_exit(self):
        self.prices[self.entry+timedelta(minutes=120)]=99
        status,rows=evaluate(self.prices,self.signal,self.entry)
        self.assertEqual(status,'included')
        row=next(r for r in rows if r['rule']=='fixed_120m')
        self.assertEqual(row['exit_price'],99)
        del self.prices[self.entry+timedelta(minutes=100)]
        self.assertEqual(evaluate(self.prices,self.signal,self.entry),('incomplete_120m_path',[]))

    def test_75pct_target_can_trigger_after_60_minutes(self):
        self.prices[self.entry+timedelta(minutes=20)]=100.8
        self.prices[self.entry+timedelta(minutes=80)]=100.5
        self.prices[self.entry+timedelta(minutes=81)]=100.7
        status,rows=evaluate(self.prices,self.signal,self.entry,fraction=.75,cap=120)
        self.assertEqual(status,'included')
        row=next(r for r in rows if r['rule']=='target_75pct_120m')
        self.assertEqual(row['target_price'],100.5)
        self.assertEqual(row['trigger_minutes'],80)
        self.assertEqual(row['held_minutes'],81)
        self.assertEqual(row['exit_price'],100.7)

    def test_120_minute_deadline_and_last_trigger(self):
        def target():
            _,rows=evaluate(self.prices,self.signal,self.entry,fraction=.75,cap=120)
            return rows[-1]
        self.assertEqual(target()['exit_reason'],'time')
        self.assertEqual(target()['held_minutes'],120)
        self.prices[self.entry+timedelta(minutes=119)]=100.5
        self.assertEqual(target()['exit_reason'],'target')
        self.assertEqual(target()['held_minutes'],120)
        self.assertEqual(target()['exit_price'],102)

    def test_target_eligibility_changes_with_fraction(self):
        self.prices[self.entry]=100.8
        self.assertEqual(evaluate(self.prices,self.signal,self.entry)[0],
                         'target_reached_before_entry')
        self.assertEqual(evaluate(self.prices,self.signal,self.entry,fraction=.75,cap=120)[0],
                         'included')

if __name__=='__main__':
    unittest.main()
