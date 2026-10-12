from datetime import datetime, timedelta, timezone
import math
import statistics
import unittest
from research.short_backtest import backtest, signals, longest_segment


class ShortBacktestTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,1,1,tzinfo=timezone.utc)

    def t(self,k):
        return self.start+timedelta(minutes=k)

    def test_delay_quantity_costs_and_marked_drawdown(self):
        prices={self.t(k):v for k,v in enumerate([100,110,121,99])}
        s,trades,equity=backtest(prices,{self.t(0):(3.5,.01)},3,5,1000,1000,2)
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]['entry_price'],110)
        self.assertEqual(trades[0]['exit_price'],99)
        self.assertAlmostEqual(s['gross_pnl'],100)
        self.assertAlmostEqual(s['net_pnl'],99.5)
        self.assertAlmostEqual(s['max_drawdown'],100.25)
        self.assertAlmostEqual(equity[-1]['equity'],1099.5)
        self.assertAlmostEqual(sum(r['net_pnl'] for r in trades),s['net_pnl'])

    def test_negative_shocks_do_not_block_and_open_crossings_are_not_queued(self):
        prices={self.t(k):100 for k in range(10)}
        scores={self.t(k):(z,.01 if z>0 else -.01) for k,z in enumerate([-4,3,0,3,3,3,3,0,3,0])}
        s,trades,_=backtest(prices,scores,2,hold=3)
        self.assertEqual([r['entry_time'] for r in trades],[self.t(2).isoformat(),self.t(9).isoformat()])
        self.assertEqual(s['skipped_crossings_while_short'],1)
        self.assertEqual(trades[-1]['exit_reason'],'end_of_data')

    def test_missing_entry_cancels_and_missing_exit_delays(self):
        prices={self.t(k):100 for k in [0,2,3,4,8,9]}
        scores={self.t(0):(3,.01),self.t(2):(0,0),self.t(3):(3,.01)}
        s,trades,_=backtest(prices,scores,2,hold=2)
        self.assertEqual(s['canceled_missing_entries'],1)
        self.assertEqual(trades[0]['entry_time'],self.t(4).isoformat())
        self.assertEqual(trades[0]['exit_time'],self.t(8).isoformat())
        self.assertEqual(s['delayed_exits'],1)

    def test_primary_segment_uses_continuity_not_returns(self):
        prices={self.t(k):100 for k in [0,1,2,10,11,12,13]}
        self.assertEqual(list(longest_segment(prices)),[self.t(k) for k in [10,11,12,13]])

    def test_target_execution_delay_and_reentry(self):
        prices={self.t(k):102 for k in range(16)}
        prices[self.t(0)]=100
        prices[self.t(4)]=99
        prices[self.t(8)]=100
        prices[self.t(9)]=101
        scores={self.t(5):(3,.02),self.t(6):(0,0),self.t(9):(3,.02)}
        summary,trades,_=backtest(prices,scores,2,hold=6,target_fraction=1)
        self.assertEqual(trades[0]['entry_time'],self.t(6).isoformat())
        self.assertEqual(trades[0]['target_price'],100)
        self.assertEqual(trades[0]['target_trigger_time'],self.t(8).isoformat())
        self.assertEqual(trades[0]['exit_time'],self.t(9).isoformat())
        self.assertEqual(trades[0]['exit_price'],101)
        self.assertEqual(trades[0]['exit_reason'],'target_exit')
        self.assertEqual(trades[1]['entry_time'],self.t(10).isoformat())
        self.assertEqual(summary['target_exits'],1)

    def test_preentry_target_hit_skips_without_cost(self):
        prices={self.t(k):102 for k in range(10)}
        prices[self.t(0)]=100
        prices[self.t(6)]=99
        summary,trades,_=backtest(prices,{self.t(5):(3,.02)},2,target_fraction=1)
        self.assertEqual(trades,[])
        self.assertEqual(summary['target_skipped_entries'],1)
        self.assertEqual(summary['final_equity'],10000)

    def test_target_timeout_and_final_close(self):
        prices={self.t(k):102 for k in range(12)}
        prices[self.t(0)]=100
        scores={self.t(5):(3,.02)}
        _,trades,_=backtest(prices,scores,2,hold=3,target_fraction=1)
        self.assertEqual(trades[0]['exit_time'],self.t(9).isoformat())
        self.assertEqual(trades[0]['exit_reason'],'time_exit')
        _,trades,_=backtest(prices,scores,2,hold=120,target_fraction=1)
        self.assertEqual(trades[0]['exit_reason'],'end_of_data')

    def test_capital_and_notional_scale_without_changing_trades(self):
        prices={self.t(k):102 for k in range(16)}
        prices[self.t(0)]=100
        prices[self.t(8)]=100
        scores={self.t(5):(3,.02)}
        for target in (None,1):
            small,small_trades,_=backtest(prices,scores,2,capital=1000,notional=1000,
                                         hold=120,target_fraction=target)
            large,large_trades,_=backtest(prices,scores,2,capital=10000,notional=10000,
                                         hold=120,target_fraction=target)
            self.assertEqual(small['trades'],large['trades'])
            self.assertEqual(small_trades[0]['exit_time'],large_trades[0]['exit_time'])
            for field in ('final_equity','net_pnl','costs','max_drawdown'):
                self.assertAlmostEqual(large[field],10*small[field])
            self.assertAlmostEqual(large['return_pct'],small['return_pct'])

    def test_extended_retracement_targets_below_original_price(self):
        for fraction,target in ((1.5,99),(2,98),(2.5,97),(3,96)):
            prices={self.t(k):102 for k in range(15)}
            prices[self.t(0)]=100
            prices[self.t(7)]=100
            prices[self.t(8)]=target
            prices[self.t(9)]=target+.5
            _,trades,_=backtest(prices,{self.t(5):(3,.02)},2,hold=240,
                                target_fraction=fraction)
            self.assertEqual(trades[0]['target_price'],target)
            self.assertEqual(trades[0]['target_trigger_time'],self.t(8).isoformat())
            self.assertEqual(trades[0]['exit_time'],self.t(9).isoformat())
            self.assertEqual(trades[0]['exit_price'],target+.5)

    def test_longer_holding_deadlines_and_invalid_targets(self):
        prices={self.t(k):102 for k in range(250)}
        prices[self.t(0)]=100
        for hold in (180,240):
            _,trades,_=backtest(prices,{self.t(5):(3,.02)},2,hold=hold,
                                target_fraction=2)
            self.assertEqual(trades[0]['held_minutes'],hold)
            self.assertEqual(trades[0]['exit_reason'],'time_exit')
        for invalid in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                backtest(prices,{},2,target_fraction=invalid)

    def test_hour_signal_warmup_and_exclusion_of_current_hour(self):
        prices={self.t(k):100+(k%7)*.01 for k in range(480)}
        prices[self.t(479)]=102
        scores=signals(prices,move=60)
        self.assertEqual(list(scores),[self.t(479)])
        history=[math.log(prices[self.t(k)]/prices[self.t(k-60)])
                 for k in range(60,420)]
        shock=math.log(prices[self.t(479)]/prices[self.t(419)])
        expected=(shock-statistics.mean(history))/statistics.stdev(history)
        self.assertAlmostEqual(scores[self.t(479)][0],expected)

    def test_hour_target_uses_hour_start_not_five_minute_start(self):
        prices={self.t(k):102 for k in range(70)}
        prices[self.t(0)]=100
        prices[self.t(63)]=100
        _,trades,_=backtest(prices,{self.t(60):(3,.02)},2,
                            hold=240,target_fraction=1,move=60)
        self.assertEqual(trades[0]['target_price'],100)
        self.assertEqual(trades[0]['exit_time'],self.t(64).isoformat())

    def test_four_sigma_requires_its_own_upward_crossing(self):
        prices={self.t(k):102 for k in range(15)}
        scores={self.t(5):(3.9,.01),self.t(6):(4,.02),self.t(7):(4.2,.02)}
        _,trades,_=backtest(prices,scores,4,hold=3)
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]['signal_time'],self.t(6).isoformat())
        self.assertEqual(trades[0]['entry_time'],self.t(7).isoformat())
        self.assertEqual(trades[0]['exit_time'],self.t(10).isoformat())

    def test_signal_prefix_is_unchanged_by_future_data(self):
        prices={self.t(k):100+(k%3)*.01+(1 if k==40 else 0) for k in range(100)}
        full=signals(prices,window=20)
        prefix={t:p for t,p in prices.items() if t<=self.t(50)}
        self.assertEqual(signals(prefix,window=20),{t:s for t,s in full.items() if t<=self.t(50)})
        del prices[self.t(45)]
        after_gap=signals(prices,window=20)
        self.assertFalse(any(self.t(45)<t<self.t(75) for t in after_gap))


if __name__=='__main__':
    unittest.main()
