"""Offline checks for the engine's deterministic dependency boundary."""
import copy
from decimal import Decimal as D
import unittest
from unittest.mock import AsyncMock, patch

from hedger.engine import Engine
from hedger.ports import LiveRuntime
from hedger.strategy import Config, Market


class MemoryState:
    def __init__(self):
        self.data = {"watch": None, "established": False, "stopped": False,
                     "paused": None, "outbox": []}

    def save(self):
        pass

    def event(self, text):
        self.data["outbox"].append(text)


class FixedRuntime:
    def monotonic(self):
        return 100.0

    def time(self):
        return 1790726400.0

    def next_client_id(self):
        return 1


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def make_engine(self, read_at=100.0):
        config = Config("BTC", D("100000"), D("0.001"), D("1"))
        market = Market(1, "BTC", 5, 1, D("0.00007"), D("10"))
        exchange = AsyncMock()
        exchange.snapshot.return_value = {
            "position": -config.quantity, "orders": [],
            "mark": D("100000"), "read_at": read_at,
        }
        return Engine(config, market, MemoryState(), exchange,
                      live=True, runtime=FixedRuntime())

    async def test_identical_inputs_produce_identical_intents_and_events(self):
        runs = []
        with patch("hedger.ports.time.time", side_effect=AssertionError("real clock")), \
                patch("hedger.ports.time.monotonic", side_effect=AssertionError("real clock")), \
                patch("hedger.ports.secrets.randbelow", side_effect=AssertionError("random ID")):
            # Calling the coroutine directly avoids affecting asyncio's own clock.
            for _ in range(2):
                engine = self.make_engine()
                await engine.tick()
                engine.exchange.create.assert_awaited_once()
                self.assertEqual(engine.exchange.create.call_args.args[1], 1)
                self.assertEqual(engine.state.data["watch"]["created_at"], 1790726400.0)
                self.assertIn("last poll 0s ago", engine.summary())
                runs.append(copy.deepcopy(engine.state.data))
        self.assertEqual(runs[0], runs[1])

    async def test_staleness_guard_uses_injected_clock(self):
        engine = self.make_engine(read_at=84.0)
        await engine.tick()
        engine.exchange.create.assert_not_awaited()
        self.assertIsNone(engine.state.data["watch"])

    async def test_strike_change_uses_injected_clock_for_freshness(self):
        for read_at, applied in [(100.0, True), (84.0, False)]:
            engine = self.make_engine(read_at=read_at)
            engine.state.data.update(identity={"strike": "99000"},
                                     strike_change={"identity": {"strike": "100000"},
                                                    "cancel_requested": False})
            await engine.tick()
            self.assertEqual("strike_change" not in engine.state.data, applied)
            engine.exchange.create.assert_not_awaited()

    async def test_strike_change_cancellation_uses_injected_clock(self):
        from hedger.sim_exchange import ReplayRuntime, SimulatedExchange
        from hedger.strategy import specs
        from types import SimpleNamespace
        from datetime import datetime, timezone

        for read_at, expected_cancels in [(100.0, 1), (84.0, 0)]:
            engine = self.make_engine(read_at=read_at)
            spec, _ = specs(engine.config, engine.market)
            settings = SimpleNamespace(market=engine.market, strategy=engine.config,
                                       initial_position="short",
                                       starting_cash=D("500"), fee_pct=D("0"))
            exchange = SimulatedExchange(settings, ReplayRuntime(datetime(2026, 10, 2, tzinfo=timezone.utc)),
                                         D("100000"), lambda *args, **kwargs: None)
            await exchange.create(spec, 1)
            row = (await exchange.snapshot())["orders"][0]
            engine.track(spec, row=row)
            engine.exchange.snapshot.return_value["orders"] = [row]
            engine.state.data["strike_change"] = {"cancel_requested": False}
            await engine.tick()
            self.assertEqual(engine.exchange.cancel.await_count, expected_cancels)

    def test_live_runtime_preserves_production_sources(self):
        runtime = LiveRuntime()
        with patch("hedger.ports.time.monotonic", return_value=12), \
                patch("hedger.ports.time.time", return_value=34), \
                patch("hedger.ports.secrets.randbelow", return_value=55) as randbelow:
            self.assertEqual(runtime.monotonic(), 12)
            self.assertEqual(runtime.time(), 34)
            self.assertEqual(runtime.next_client_id(), 56)
            randbelow.assert_called_once_with(2**48 - 1)
