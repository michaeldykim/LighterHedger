import asyncio
import copy
import json
from decimal import Decimal as D
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from hedger.engine import Engine
from hedger.exchange import Exchange
from hedger.state import State
from hedger.strategy import Config, specs
from test_hedger import BUY, SELL, CONFIG, MARKET, order

OLD = {"network": "test", "account": 42, "symbol": "BTC", "strike": "1E+5",
       "quantity": "0.001", "slippage_pct": "1", "telegram_chat": 55}
NEW = dict(OLD, strike="105000")
NEW_CONFIG = Config("BTC", D("105000"), CONFIG.quantity, D("1"))
NEW_BUY, NEW_SELL = specs(NEW_CONFIG, MARKET)


class StrikeChangeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.state = State(self.path, OLD)
        self.exchange = AsyncMock()
        self.exchange.lookup.return_value = None
        self.snapshot = {"position": -CONFIG.quantity, "orders": [],
                         "mark": D("100000"), "read_at": time.monotonic()}
        self.exchange.snapshot.side_effect = lambda: copy.deepcopy(self.snapshot)
        self.engine = Engine(CONFIG, MARKET, self.state, self.exchange, live=True)

    async def asyncTearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def request_change(self):
        self.state.close()
        self.state = State(self.path, NEW, allow_strike_change=True)
        self.state.data.update(stopped=False, paused=None)  # --resume behavior
        self.state.save()
        self.engine = Engine(NEW_CONFIG, MARKET, self.state, self.exchange, live=True)

    def tracked(self, spec=BUY):
        self.engine.track(spec, row=order(spec))
        self.snapshot["position"] = D(0) if spec.is_ask else -CONFIG.quantity
        self.snapshot["orders"] = [order(spec)]

    async def test_cancel_confirm_then_replace(self):
        self.tracked()
        self.request_change()

        async def cancel(index):
            saved = json.loads(self.state.db.execute("SELECT body FROM state").fetchone()[0])
            self.assertTrue(saved["strike_change"]["cancel_requested"])
            self.assertEqual(saved["identity"], OLD)
            self.assertEqual(saved["watch"]["order_index"], index)
        self.exchange.cancel.side_effect = cancel

        await self.engine.tick()
        self.exchange.cancel.assert_awaited_once_with(123)
        self.exchange.create.assert_not_awaited()
        await self.engine.tick()  # Still active, no duplicate cancel or replacement.
        self.exchange.cancel.assert_awaited_once()
        self.exchange.create.assert_not_awaited()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="canceled")
        await self.engine.tick()
        self.assertIsNone(self.state.data["watch"])
        self.assertEqual(self.state.data["identity"], OLD)
        await self.engine.tick()
        self.assertEqual(self.state.data["identity"], NEW)
        self.exchange.create.assert_not_awaited()
        await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], NEW_BUY)

    async def test_previously_canceled_order_accepts_new_strike(self):
        self.state.data.update(established=True, stopped=True,
                               paused="Tracked order ended as canceled (filled 0/0.001); review locally")
        self.state.save()
        self.request_change()
        await self.engine.tick()
        await self.engine.tick()
        self.assertEqual(self.state.data["identity"], NEW)
        self.assertEqual(self.exchange.create.call_args.args[0], NEW_BUY)
        self.exchange.cancel.assert_not_awaited()

    async def test_manual_cancellation_before_restart_is_reconciled(self):
        self.tracked()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="canceled")
        self.request_change()
        for _ in range(3):
            await self.engine.tick()
        self.assertEqual(self.state.data["identity"], NEW)
        self.exchange.cancel.assert_not_awaited()
        self.exchange.create.assert_awaited_once()

    async def test_cancel_timeout_survives_restart(self):
        self.tracked()
        self.request_change()
        self.exchange.cancel.side_effect = TimeoutError()
        await self.engine.tick()
        self.request_change()
        await self.engine.tick()
        self.exchange.cancel.assert_awaited_once()
        self.exchange.create.assert_not_awaited()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="canceled")
        for _ in range(3):
            await self.engine.tick()
        self.exchange.create.assert_awaited_once()

    async def test_crash_after_cancel_intent_does_not_repeat_cancel(self):
        self.tracked()
        self.request_change()
        self.exchange.cancel.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.engine.tick()
        self.request_change()
        await self.engine.tick()
        self.exchange.cancel.assert_awaited_once()
        self.exchange.create.assert_not_awaited()

    async def test_partial_fill_stops_change_and_survives_resume(self):
        self.tracked()
        self.snapshot["orders"] = [order(filled="0.0005")]
        self.request_change()
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.assertEqual(self.state.data["identity"], OLD)
        self.exchange.cancel.assert_not_awaited()
        self.exchange.create.assert_not_awaited()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="canceled", filled="0.0005")
        self.request_change()
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.assertIsNotNone(self.state.data["watch"])
        self.assertEqual(self.state.data["identity"], OLD)

    async def test_unexpected_position_blocks_change(self):
        self.request_change()
        self.snapshot["position"] = D("-0.0005")
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.assertEqual(self.state.data["identity"], OLD)
        self.exchange.cancel.assert_not_awaited()
        self.exchange.create.assert_not_awaited()

    async def test_full_fill_during_cancel_uses_confirmed_position(self):
        self.tracked()
        self.request_change()
        await self.engine.tick()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="filled", filled="0.001")
        await self.engine.tick()  # Position has not caught up yet.
        self.assertIsNotNone(self.state.data["watch"])
        self.exchange.create.assert_not_awaited()
        self.snapshot["position"] = D(0)
        for _ in range(3):
            await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], NEW_SELL)
        self.assertTrue(any(e.startswith("FILL") for e in self.state.data["outbox"]))

    async def test_missing_history_never_allows_replacement(self):
        self.tracked()
        self.snapshot["orders"] = []
        self.request_change()
        for _ in range(3):
            await self.engine.tick()
        self.assertEqual(self.state.data["identity"], OLD)
        self.exchange.cancel.assert_not_awaited()
        self.exchange.create.assert_not_awaited()

    async def test_untracked_exact_old_order_is_adopted_before_cancel(self):
        self.snapshot["orders"] = [order()]
        self.request_change()
        await self.engine.tick()
        self.assertEqual(self.state.data["watch"]["order_index"], 123)
        self.exchange.cancel.assert_not_awaited()
        await self.engine.tick()
        self.exchange.cancel.assert_awaited_once_with(123)

    async def test_conflicting_orders_are_never_canceled(self):
        self.tracked()
        self.snapshot["orders"].append(order(index=124))
        self.request_change()
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.exchange.cancel.assert_not_awaited()
        self.exchange.create.assert_not_awaited()

    async def test_canceled_status_still_active_does_not_clear_watch(self):
        self.tracked()
        self.snapshot["orders"] = [order(status="canceled")]
        self.request_change()
        await self.engine.tick()
        self.assertIsNotNone(self.state.data["watch"])
        self.assertEqual(self.state.data["identity"], OLD)

    async def test_stale_snapshot_does_not_cancel_or_commit(self):
        self.request_change()
        self.snapshot["read_at"] = time.monotonic() - 30
        await self.engine.tick()
        self.assertEqual(self.state.data["identity"], OLD)
        self.engine.track(BUY, row=order())
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.exchange.cancel.assert_not_awaited()
        self.exchange.create.assert_not_awaited()

    async def test_read_only_does_not_cancel_or_commit(self):
        self.tracked()
        self.request_change()
        self.engine.live = False
        await self.engine.tick()
        self.assertEqual(self.state.data["identity"], OLD)
        self.exchange.cancel.assert_not_awaited()

    async def test_paused_change_keeps_reporting_fills_without_replacement(self):
        self.tracked()
        self.request_change()
        self.state.data["paused"] = "Local review required"
        await self.engine.tick()
        self.exchange.cancel.assert_not_awaited()
        self.snapshot.update(orders=[], position=D(0))
        self.exchange.lookup.return_value = order(status="filled", filled="0.001")
        await self.engine.tick()
        await self.engine.tick()
        self.assertTrue(any(e.startswith("FILL") for e in self.state.data["outbox"]))
        self.assertEqual(self.state.data["identity"], OLD)
        self.exchange.create.assert_not_awaited()

    async def test_unexpected_position_after_full_fill_pauses_change(self):
        self.tracked()
        self.request_change()
        self.snapshot.update(orders=[], position=D("-0.0005"))
        self.exchange.lookup.return_value = order(status="filled", filled="0.001")
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.assertEqual(self.state.data["identity"], OLD)
        self.exchange.create.assert_not_awaited()

    async def test_replacement_submission_timeout_is_not_repeated_after_restart(self):
        self.state.data["established"] = True
        self.state.save()
        self.request_change()
        await self.engine.tick()
        self.exchange.create.side_effect = TimeoutError()
        await self.engine.tick()
        self.state.close()
        self.state = State(self.path, NEW)
        self.engine = Engine(NEW_CONFIG, MARKET, self.state, self.exchange, live=True)
        await self.engine.tick()
        self.exchange.create.assert_awaited_once()
        self.assertIsNotNone(self.state.data["watch"])

    async def test_sell_order_replacement_while_flat(self):
        self.tracked(SELL)
        self.request_change()
        await self.engine.tick()
        self.exchange.cancel.assert_awaited_once_with(123)
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(SELL, status="canceled")
        for _ in range(3):
            await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], NEW_SELL)

    async def test_resume_requires_same_pending_target(self):
        self.request_change()
        self.state.close()
        for identity, allow in [(NEW, False), (OLD, True), (dict(NEW, strike="106000"), True)]:
            with self.assertRaises(ValueError):
                State(self.path, identity, allow_strike_change=allow)
        self.state = State(self.path, NEW, allow_strike_change=True)
        self.assertEqual(self.state.data["identity"], OLD)

    async def test_only_strike_change_with_explicit_resume_is_allowed(self):
        self.state.close()
        for identity, allow in [(NEW, False), (dict(NEW, quantity="0.002"), True),
                                (dict(NEW, symbol="HYPE"), True), (dict(NEW, slippage_pct="2"), True)]:
            with self.assertRaises(ValueError):
                State(self.path, identity, allow_strike_change=allow)
        self.state = State(self.path, OLD)
        self.assertNotIn("strike_change", self.state.data)

    async def test_cancel_adapter_signs_only_the_selected_order(self):
        signer = AsyncMock()
        signer.cancel_order.return_value = (None, type("Response", (), {"code": 200})(), None)
        exchange = Exchange(None, signer, 42, 3, MARKET)
        await exchange.cancel(123)
        signer.cancel_order.assert_awaited_once_with(market_index=1, order_index=123)
        signer.cancel_order.return_value = (None, None, "rejected")
        with self.assertRaises(RuntimeError):
            await exchange.cancel(123)
