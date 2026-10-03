import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, localcontext
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from hedger.sim_input import Settings, observations
from hedger.simulate import replay

ROOT = Path(__file__).resolve().parent.parent


def config():
    return {
        "strategy": {"symbol": "HYPE", "strike": "100", "quantity": "2", "slippage_pct": "1"},
        "market": {"id": 0, "size_decimals": 2, "price_decimals": 4,
                   "min_quantity": "0", "min_notional": "0"},
        "account": {"starting_cash": "500", "initial_position": "short", "entry_price": "100", "fee_pct": "0"},
        "data_files": ["prices.csv"],
    }


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_count = 0

    def tearDown(self):
        self.tmp.cleanup()

    def write_prices(self, prices):
        start = datetime(2026, 9, 30, tzinfo=timezone.utc)
        rows = ["timestamp_utc,price_usd,source"]
        for i, item in enumerate(prices):
            second, price = item if isinstance(item, tuple) else (i * 10, item)
            timestamp = (start + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")
            rows.append(f"{timestamp},{price},test")
        (self.root / "prices.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def run_replay(self, prices, raw=None):
        self.write_prices(prices)
        raw = raw or config()
        self.run_count += 1
        output = self.root / f"run-{self.run_count}"
        async def isolated_replay():
            # Windows asyncio creates its own local socket pair before replay starts.
            with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
                    patch("asyncio.sleep", side_effect=AssertionError("Sleep forbidden")), \
                    patch("time.sleep", side_effect=AssertionError("Sleep forbidden")), \
                    patch("hedger.ports.secrets.randbelow", side_effect=AssertionError("Randomness forbidden")):
                return await replay(Settings.parse(raw, self.root), output)
        result = asyncio.run(isolated_replay())
        events = [json.loads(line) for line in (output / "actions.jsonl").read_text().splitlines()]
        return result, events, output

    def test_cycle_preserves_next_row_delay_and_accounting(self):
        result, events, _ = self.run_replay(["100", "100.5", "100.6", "99.75", "99.8"])
        submissions = [e for e in events if e["kind"] == "order_submitted"]
        self.assertEqual([e["timestamp_utc"][-9:] for e in submissions], ["00:00:00Z", "00:00:20Z", "00:00:40Z"])
        self.assertEqual([e["is_ask"] for e in submissions], [False, True, False])
        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["closed_trade_count"], 1)
        self.assertEqual(D(result["realized_pnl"]), D("-1"))
        self.assertEqual(D(result["unrealized_pnl"]), D("-0.10"))
        self.assertEqual(D(result["final_equity"]), D("498.90"))
        self.assertEqual(D(result["return_pct"]), D("-0.22"))
        self.assertEqual(D(result["max_drawdown"]), D("1.10"))
        self.assertIsNone(result["paused"])

    def test_fee_on_each_fill_and_perpetual_cash_not_sale_proceeds(self):
        raw = config()
        raw["account"]["fee_pct"] = "0.1"
        result, _, _ = self.run_replay(["100", "100.5", "100.6", "99.75"], raw)
        self.assertEqual(D(result["fees"]), D("0.4005"))
        self.assertEqual(D(result["final_cash"]), D("498.5995"))
        self.assertEqual(D(result["net_pnl"]), D("-1.4005"))

    def test_buy_gap_cancels_and_latches_pause(self):
        result, events, _ = self.run_replay(["100", "102", "100", "100.5"])
        self.assertEqual(result["orders_canceled"], 1)
        self.assertEqual(result["orders_submitted"], 1)
        self.assertEqual(result["trade_count"], 0)
        self.assertIn("canceled-too-much-slippage", result["paused"])
        self.assertTrue(any(e["kind"] == "order_canceled" for e in events))

    def test_sell_gap_cancels(self):
        raw = config()
        raw["account"].update(initial_position="flat", entry_price=None)
        result, _, _ = self.run_replay(["101", "98", "101"], raw)
        self.assertEqual(result["orders_canceled"], 1)
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(D(result["final_equity"]), D("500"))

    def test_crossed_new_order_executes_immediately(self):
        result, events, _ = self.run_replay(["100", "100.5", "99.75"])
        fills = [e for e in events if e["kind"] == "order_filled"]
        self.assertEqual(len(fills), 2)
        self.assertEqual(fills[-1]["timestamp_utc"], "2026-09-30T00:00:20Z")
        self.assertEqual(result["unreconciled_order"]["client_order_index"], 2)

    def test_equal_execution_bound_is_fillable(self):
        result, _, _ = self.run_replay(["100", "101.5050"])
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["orders_canceled"], 0)

    def test_flat_below_trigger_waits_without_forced_initial_trade(self):
        raw = config()
        raw["account"].update(initial_position="flat", entry_price=None)
        result, _, _ = self.run_replay(["99", "100", "99"], raw)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(D(result["net_pnl"]), 0)
        self.assertIsNone(result["paused"])

    def test_conflicting_starting_short_preserves_strategy_pause(self):
        result, _, _ = self.run_replay(["101", "100"])
        self.assertIsNotNone(result["paused"])
        self.assertEqual(result["orders_submitted"], 0)

    def test_preexisting_pnl_is_excluded_from_replay_return(self):
        raw = config()
        raw["account"]["entry_price"] = "110"
        result, _, _ = self.run_replay(["100", "100.5"], raw)
        self.assertEqual(D(result["initial_equity"]), D("520"))
        self.assertEqual(D(result["realized_pnl"]), D("19"))
        self.assertEqual(D(result["net_pnl"]), D("-1"))

    def test_irregular_rows_each_tick_once_without_scheduled_polls(self):
        result, events, _ = self.run_replay([(0, "100"), (11, "100.5"), (20, "100.6"), (30, "99.75")])
        self.assertEqual(result["strategy_ticks"], 4)
        fills = [e for e in events if e["kind"] == "order_filled"]
        self.assertEqual(fills[0]["timestamp_utc"], "2026-09-30T00:00:11Z")
        sells = [e for e in events if e["kind"] == "order_submitted" and e["is_ask"]]
        self.assertEqual(sells[0]["timestamp_utc"], "2026-09-30T00:00:20Z")

    def test_dense_rows_and_long_gap_do_not_add_or_skip_ticks(self):
        result, events, output = self.run_replay([(0, "100"), (1, "100.5"),
                                                 (86400, "100.6"), (86401, "99.75")])
        self.assertEqual(result["strategy_ticks"], 4)
        self.assertEqual(result["observations"], 4)
        self.assertEqual(result["trade_count"], 2)
        submitted = [e for e in events if e["kind"] == "order_submitted"]
        self.assertEqual([e["timestamp_utc"] for e in submitted],
                         ["2026-09-30T00:00:00Z", "2026-10-01T00:00:00Z"])
        # Header, initial equity, and pre/post-strategy marks for each input row.
        self.assertEqual(len((output / "equity.csv").read_text().splitlines()), 10)

    def test_identical_runs_have_byte_identical_artifacts(self):
        prices = ["100", "100.5", "100.6", "99.75", "99.8"]
        _, _, first = self.run_replay(prices)
        with localcontext() as ctx:
            ctx.prec = 12
            _, _, second = self.run_replay(prices)
        for name in ("actions.jsonl", "equity.csv", "summary.json"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_no_future_rows_affect_action_prefix(self):
        _, short_events, _ = self.run_replay(["100", "100.5"])
        _, long_events, _ = self.run_replay(["100", "100.5", "99.75"])
        prefix = [e for e in short_events if e["kind"] != "completed"]
        self.assertEqual(prefix, long_events[:len(prefix)])

    def test_existing_output_is_not_overwritten(self):
        _, _, output = self.run_replay(["100"])
        before = (output / "summary.json").read_bytes()
        with self.assertRaises(FileExistsError):
            asyncio.run(replay(Settings.parse(config(), self.root), output))
        self.assertEqual(before, (output / "summary.json").read_bytes())

    def test_invalid_input_never_gets_success_summary(self):
        self.write_prices(["100", "NaN"])
        output = self.root / "invalid"
        with self.assertRaises(ValueError):
            asyncio.run(replay(Settings.parse(config(), self.root), output))
        self.assertFalse((output / "summary.json").exists())

    def test_actual_sample_and_cli_reproducibility(self):
        raw = json.loads((ROOT / "sim_config.example.json").read_text())
        raw["data_files"] = [str(ROOT / "simulations" / "simulation_test" / "2026-09-30_HYPE.csv.zip")]
        settings = Settings.parse(raw)
        first = self.root / "sample"
        result = asyncio.run(replay(settings, first))
        self.assertEqual(result["observations"], 8640)
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["orders_submitted"], 1)
        self.assertEqual(D(result["final_equity"]), D("378"))
        self.assertEqual(D(result["net_pnl"]), D("-122"))
        self.assertEqual(D(result["return_pct"]), D("-24.4"))
        self.assertEqual(result["final_position"], "-25")
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(raw), encoding="utf-8")
        second = self.root / "cli"
        process = subprocess.run([sys.executable, "-m", "hedger.simulate", "--config", str(config_path),
                                  "--output", str(second)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        for name in ("actions.jsonl", "equity.csv", "summary.json"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())


class InputTests(unittest.TestCase):
    def test_config_rejects_missing_ambiguous_and_invalid_settings(self):
        for section, field, value in [("account", "initial_position", None), ("account", "entry_price", None),
                                      ("account", "fee_pct", "-1"), ("account", "starting_cash", "NaN"),
                                      ("market", "size_decimals", True), ("market", "min_quantity", "-1"),
                                      ("strategy", "quantity", "0.001"), ("strategy", "strike", "0")]:
            raw = config()
            raw[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings.parse(raw)
        raw = config()
        raw["poll_seconds"] = 10
        with self.assertRaisesRegex(ValueError, "poll_seconds"):
            Settings.parse(raw)
        raw = config()
        raw["strategy"]["strkie"] = "100"
        with self.assertRaises(ValueError):
            Settings.parse(raw)

    def test_csv_validation_and_zip_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            header = "timestamp_utc,price_usd,source\n"
            valid = "2026-09-30T00:00:00Z,100,test\n"
            for body in [valid + valid, "2026-09-30T00:00:00,100,test\n",
                         "2026-09-30T00:00:00Z,0,test\n", "2026-09-30T00:00:00Z,Infinity,test\n",
                         "2026-09-30T00:00:00Z,100,\n", "2026-09-30T00:00:00Z,100\n", ""]:
                path.write_text(header + body, encoding="utf-8")
                with self.subTest(body=body), self.assertRaises(ValueError):
                    list(observations([path]))
            path.write_text(header + valid, encoding="utf-8")
            archive = path.with_suffix(".zip")
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("prices.csv", header + valid)
            self.assertEqual(list(observations([path])), list(observations([archive])))
            with self.assertRaises(ValueError):
                list(observations([path, archive]))
            with zipfile.ZipFile(archive, "a") as z:
                z.writestr("another.csv", header + valid)
            with self.assertRaises(ValueError):
                list(observations([archive]))


if __name__ == "__main__":
    unittest.main()
