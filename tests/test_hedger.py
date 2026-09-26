import asyncio
import copy
from decimal import Decimal as D
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from hedger.engine import Engine
from hedger.exchange import Exchange
from hedger.state import State
from hedger.strategy import Config, Conflict, Market, initial_spec, matches, specs
from hedger.telegram import Telegram


CONFIG = Config("BTC", D("100000"), D("0.001"), D("1"))
MARKET = Market(1, "BTC", 5, 1, D("0.00007"), D("10"))
BUY, SELL = specs(CONFIG, MARKET)


def order(spec=BUY, index=123, client=0, status="open", filled="0"):
    return {
        "market_index": 1, "owner_account_index": 42,
        "order_index": index, "client_order_index": client,
        "is_ask": spec.is_ask, "type": "stop-loss", "time_in_force": "immediate-or-cancel",
        "reduce_only": spec.reduce_only, "initial_base_amount": str(spec.quantity),
        "remaining_base_amount": str(spec.quantity - D(filled)),
        "filled_base_amount": filled, "filled_quote_amount": str(D(filled) * spec.trigger),
        "trigger_price": str(spec.trigger), "price": str(spec.price),
        "status": status, "trigger_status": "mark-price",
    }


class RulesTests(unittest.TestCase):
    def test_exact_triggers_and_caps(self):
        self.assertEqual((BUY.trigger, BUY.price), (D("100500"), D("101505")))
        self.assertEqual((SELL.trigger, SELL.price), (D("99750"), D("98752.5")))
        self.assertTrue(BUY.reduce_only)
        self.assertFalse(SELL.reduce_only)

    def test_rounding_never_widens_cap(self):
        for symbol, decimals, qty in [("BTC", 1, "1"), ("ETH", 2, "1"), ("HYPE", 4, "1")]:
            market = Market(1, symbol, 5, decimals, D("0.00001"), D("1"))
            c = Config(symbol, D("123.4567"), D(qty), D("1"))
            b, s = specs(c, market)
            self.assertGreaterEqual(b.trigger, c.strike * D("1.005"))
            self.assertLessEqual(s.trigger, c.strike * D("0.9975"))
            self.assertLessEqual(b.price, b.trigger * D("1.01"))
            self.assertGreaterEqual(s.price, s.trigger * D("0.99"))

    def test_invalid_sizes_and_inputs(self):
        for quantity in ["0.000001", "0.00001"]:
            with self.assertRaises(ValueError):
                specs(Config("BTC", D("100000"), D(quantity), D("1")), MARKET)
        for strike in ["NaN", "Infinity", "-1", "0"]:
            with self.assertRaises(ValueError):
                Config("BTC", D(strike), D("1"), D("1"))

    def test_initial_state_rules(self):
        self.assertEqual(initial_spec(CONFIG, MARKET, -CONFIG.quantity, D("100000")), BUY)
        self.assertEqual(initial_spec(CONFIG, MARKET, D(0), D("100500")), SELL)
        self.assertIsNone(initial_spec(CONFIG, MARKET, D(0), D("99000")))
        for position, mark in [(D("0.001"), D("100000")), (-CONFIG.quantity, D("101000")),
                               (D("-0.0005"), D("100000"))]:
            with self.assertRaises(Conflict):
                initial_spec(CONFIG, MARKET, position, mark)

    def test_manual_order_must_match_all_controls(self):
        self.assertTrue(matches(order(), BUY, 1))
        for field, value in [("reduce_only", False), ("price", "999999"),
                             ("trigger_price", "100501"), ("type", "stop-loss-limit"),
                             ("initial_base_amount", "0.002"), ("parent_order_index", 10),
                             ("to_cancel_order_id_0", "123")]:
            with self.subTest(field=field):
                row = order()
                row[field] = value
                self.assertFalse(matches(row, BUY, 1))


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.state = State(self.path, {"test": True})
        self.snapshot = {"position": -CONFIG.quantity, "orders": [], "mark": D("100000"),
                         "read_at": time.monotonic()}
        self.exchange = AsyncMock()
        self.exchange.snapshot.side_effect = lambda: copy.deepcopy(self.snapshot)
        self.exchange.lookup.return_value = None
        self.engine = Engine(CONFIG, MARKET, self.state, self.exchange, lambda: True, live=True)

    async def asyncTearDown(self):
        self.state.close()
        self.tmp.cleanup()

    async def test_short_buy_fill_sell_fill_buy_cycle(self):
        await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], BUY)
        client = self.state.data["watch"]["client_order_index"]
        self.snapshot["orders"] = [order(client=client)]
        await self.engine.tick()
        self.assertEqual(self.exchange.create.call_count, 1)
        self.snapshot.update(position=D(0), orders=[])
        self.exchange.lookup.return_value = order(client=client, status="filled", filled="0.001")
        await self.engine.tick()
        await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], SELL)
        client = self.state.data["watch"]["client_order_index"]
        self.snapshot.update(position=-CONFIG.quantity, orders=[])
        self.exchange.lookup.return_value = order(SELL, index=124, client=client,
                                                status="filled", filled="0.001")
        await self.engine.tick()
        await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], BUY)
        self.assertEqual(self.exchange.create.call_count, 3)
        self.assertEqual(sum(e.startswith("FILL") for e in self.state.data["outbox"]), 2)

    async def test_telegram_status_reports_price_and_signed_strike_distance(self):
        self.state.data["stopped"] = True
        telegram = Telegram(None, "unused", 55, self.state, self.engine)
        for mark, distance in [("101000", "+$1,000.00 (+1.00%)"),
                               ("99000", "-$1,000.00 (-1.00%)"),
                               ("100000", "+$0.00 (+0.00%)")]:
            with self.subTest(mark=mark):
                self.snapshot["mark"] = D(mark)
                await self.engine.tick()
                telegram.handle({"message": {"chat": {"id": 55, "type": "private"},
                                             "from": {"id": 55}, "text": "/status"}})
                message = self.state.data["outbox"][-1]
                self.assertIn(f"Current mark price: ${D(mark):,.2f}", message)
                self.assertIn(distance, message)
                self.assertIn("last poll", message)
        self.exchange.create.assert_not_called()

    async def test_status_before_first_quote_and_after_failed_read(self):
        self.assertIn("Current mark price: unavailable", self.engine.summary())
        self.engine.live = False
        self.snapshot["read_at"] = time.monotonic() - 120
        await self.engine.tick()
        self.exchange.snapshot.side_effect = None
        self.exchange.snapshot.return_value = None
        await self.engine.tick()
        self.assertIn("$100,000.00 (last poll 120s ago)", self.engine.summary())

    async def test_adopt_manual_order_without_submission(self):
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.exchange.create.assert_not_called()
        self.assertEqual(self.state.data["watch"]["order_index"], 123)

    async def test_flat_above_buy_places_sell(self):
        self.snapshot.update(position=D(0), mark=D("101000"))
        await self.engine.tick()
        self.assertEqual(self.exchange.create.call_args.args[0], SELL)

    async def test_flat_below_buy_waits_then_recovers_when_short_established(self):
        self.snapshot["position"] = D(0)
        await self.engine.tick()
        self.exchange.create.assert_not_called()
        self.assertIsNone(self.state.data["paused"])
        self.snapshot["position"] = -CONFIG.quantity
        await self.engine.tick()
        self.exchange.create.assert_called_once()

    async def test_conflict_latches_without_cancelling_or_submitting(self):
        self.snapshot["orders"] = [order(), order(index=124)]
        await self.engine.tick()
        self.snapshot["orders"] = []
        await self.engine.tick()
        self.exchange.create.assert_not_called()
        self.assertTrue(self.state.data["paused"])

    async def test_timeout_and_restart_never_duplicate(self):
        self.exchange.create.side_effect = TimeoutError
        await self.engine.tick()
        self.state.close()
        self.state = State(self.path, {"test": True})
        self.engine.state = self.state
        for _ in range(3):
            await self.engine.tick()
        self.exchange.create.assert_called_once()
        self.assertIsNotNone(self.state.data["watch"])

    async def test_disappeared_order_is_not_assumed_filled(self):
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.snapshot.update(orders=[], position=D(0))
        await self.engine.tick()
        self.exchange.create.assert_not_called()
        self.assertIsNotNone(self.state.data["watch"])

    async def test_partial_fill_alerts_once_and_pauses(self):
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.snapshot.update(orders=[order(filled="0.0005")], position=D("-0.0005"))
        await self.engine.tick()
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.exchange.create.assert_not_called()
        self.assertEqual(sum(e.startswith("FILL") for e in self.state.data["outbox"]), 1)

    async def test_cancelled_order_pauses(self):
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="canceled-too-much-slippage")
        await self.engine.tick()
        self.assertTrue(self.state.data["paused"])
        self.exchange.create.assert_not_called()

    async def test_stop_during_read_prevents_submission(self):
        async def snapshot():
            self.engine.stop()
            return self.snapshot
        self.exchange.snapshot.side_effect = snapshot
        await self.engine.tick()
        self.exchange.create.assert_not_called()
        self.state.close()
        self.state = State(self.path, {"test": True})
        self.assertTrue(self.state.data["stopped"])

    async def test_stop_still_reports_existing_order_fill(self):
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.engine.stop()
        self.snapshot.update(orders=[], position=D(0))
        self.exchange.lookup.return_value = order(status="filled", filled="0.001")
        await self.engine.tick()
        await self.engine.tick()
        self.exchange.create.assert_not_called()
        self.assertTrue(any(e.startswith("FILL") for e in self.state.data["outbox"]))

    async def test_remote_unavailable_blocks_submission(self):
        self.engine.can_submit = lambda: False
        await self.engine.tick()
        self.exchange.create.assert_not_called()

    async def test_read_only_never_submits(self):
        self.engine.live = False
        await self.engine.tick()
        self.exchange.create.assert_not_called()

    async def test_inconsistent_snapshot_does_nothing(self):
        self.exchange.snapshot.side_effect = None
        self.exchange.snapshot.return_value = None
        await self.engine.tick()
        self.exchange.create.assert_not_called()

    async def test_filled_order_waits_for_account_position(self):
        self.snapshot["orders"] = [order()]
        await self.engine.tick()
        self.snapshot["orders"] = []
        self.exchange.lookup.return_value = order(status="filled", filled="0.001")
        await self.engine.tick()
        self.assertIsNotNone(self.state.data["watch"])
        self.exchange.create.assert_not_called()

    async def test_order_intent_saved_before_network_submission(self):
        async def create(spec, client):
            self.assertEqual(self.state.data["watch"]["client_order_index"], client)
            body = self.state.db.execute("SELECT body FROM state").fetchone()[0]
            self.assertIn(str(client), body)
        self.exchange.create.side_effect = create
        await self.engine.tick()

    async def test_local_lock_and_configuration_guard(self):
        with self.assertRaises(RuntimeError):
            State(self.path, {"test": True})
        self.state.close()
        with self.assertRaises(ValueError):
            State(self.path, {"different": True})
        self.state = State(self.path, {"test": True})

    async def test_telegram_auth_and_durable_stop(self):
        telegram = Telegram(None, "unused", 55, self.state, self.engine)
        for chat, sender, kind in [(56, 56, "private"), (55, 56, "private"), (55, 55, "group")]:
            telegram.handle({"message": {"chat": {"id": chat, "type": kind},
                                         "from": {"id": sender}, "text": "/stop"}})
            self.assertFalse(self.state.data["stopped"])
        telegram.handle({"message": {"chat": {"id": 55, "type": "private"},
                                     "from": {"id": 55}, "text": "/stop"}})
        self.assertTrue(self.state.data["stopped"])

    async def test_queued_stop_processed_before_remote_ready(self):
        telegram = Telegram(None, "unused", 55, self.state, self.engine)
        update = {"update_id": 7, "message": {"chat": {"id": 55, "type": "private"},
                                              "from": {"id": 55}, "text": "/stop"}}
        calls = 0
        async def call(method, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.assertFalse(telegram.healthy())
                return [update]
            if calls == 2:
                self.assertTrue(self.state.data["stopped"])
                self.assertFalse(telegram.healthy())
                return []
            raise asyncio.CancelledError
        telegram.call = call
        with self.assertRaises(asyncio.CancelledError):
            await telegram.poll()
        self.assertEqual(self.state.data["telegram_offset"], 8)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_history_still_uses_client_lookup_after_order_id_known(self):
        exchange = Exchange(None, None, 42, 3, MARKET)
        exchange.read = AsyncMock(return_value={"orders": [order(client=999)]})
        await exchange.lookup({"order_index": 123, "client_order_index": 999, "lookup_by_client": True})
        self.assertEqual(exchange.read.call_args.args[0], "accountOrders")

    async def test_client_id_collision_blocks_reconciliation(self):
        exchange = Exchange(None, None, 42, 3, MARKET)
        exchange.read = AsyncMock(return_value={"orders": [order(index=124, client=999)]})
        with self.assertRaises(Conflict):
            await exchange.lookup({"order_index": 123, "client_order_index": 999, "lookup_by_client": True})

    async def test_signer_arguments_match_official_stop_market_api(self):
        signer = AsyncMock()
        signer.create_sl_order.return_value = (None, type("Response", (), {"code": 200})(), None)
        exchange = Exchange(None, signer, 42, 3, MARKET)
        await exchange.create(BUY, 100)
        signer.create_sl_order.assert_awaited_once_with(
            market_index=1, client_order_index=100, base_amount=100,
            trigger_price=1005000, price=1015050, is_ask=False, reduce_only=True)

    async def test_manual_history_uses_order_id_and_pagination(self):
        exchange = Exchange(None, None, 42, 3, MARKET)
        exchange.read = AsyncMock(side_effect=[
            {"orders": [order(index=111)], "next_cursor": "next"},
            {"orders": [order(status="filled", filled="0.001")], "next_cursor": ""},
        ])
        result = await exchange.lookup({"order_index": 123, "client_order_index": 0})
        self.assertEqual(result["order_index"], 123)
        self.assertEqual(exchange.read.call_args.args[1]["cursor"], "next")


if __name__ == "__main__":
    unittest.main()
