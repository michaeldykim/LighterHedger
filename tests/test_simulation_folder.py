import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from hedger.sim_input import SimulationPlan
from hedger.simulate import replay, run_simulation

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def folder_config():
    return {
        "strategy": {"symbol": "HYPE", "strike": "100", "quantity": "2", "slippage_pct": "1"},
        "market": {"id": 0, "size_decimals": 2, "price_decimals": 4,
                   "min_quantity": "0", "min_notional": "0"},
        "account": {"starting_cash": "500", "initial_position": "short", "entry_price": "100", "fee_pct": "0"},
    }


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "simulation_test"
        self.folder.mkdir()
        # Both creation order and filename order differ from timestamp order.
        self.archive("a-last.ZIP", [(30, "99.75"), (40, "99.8")])
        self.archive("z-first.zip", [(0, "100"), (10, "100.5")])
        self.archive("m-middle.zip", [(20, "100.6")])
        self.raw = folder_config()
        self.save_config()

    def tearDown(self):
        self.tmp.cleanup()

    def save_config(self):
        (self.folder / "config.json").write_text(json.dumps(self.raw), encoding="utf-8")

    def archive(self, name, prices):
        start = datetime(2026, 9, 30, tzinfo=timezone.utc)
        rows = ["timestamp_utc,price_usd,source"]
        for second, price in prices:
            timestamp = (start + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")
            rows.append(f"{timestamp},{price},test")
        with zipfile.ZipFile(self.folder / name, "w") as archive:
            archive.writestr("prices.csv", "\n".join(rows) + "\n")

    def run_folder(self, instant=NOW):
        async def isolated():
            with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
                    patch("asyncio.sleep", side_effect=AssertionError("Sleep forbidden")), \
                    patch("time.sleep", side_effect=AssertionError("Sleep forbidden")):
                return await run_simulation(self.folder, started_at=instant)
        return asyncio.run(isolated())

    def test_all_zips_are_sorted_by_content_and_non_zip_results_ignored(self):
        (self.folder / "comparison-old.csv").write_text("not market data")
        result_path, report = self.run_folder()
        self.assertEqual(report["data_files"], ["z-first.zip", "m-middle.zip", "a-last.ZIP"])
        self.assertEqual(report["observations"], 5)
        self.assertEqual(report["simulation"], self.folder.name)
        self.assertEqual(result_path.parent, self.folder)
        self.assertEqual(result_path.name, "results-20261002T120000000000Z.json")
        self.assertEqual(len(list(self.folder.glob("actions-*.jsonl"))), 1)
        self.assertEqual(len(list(self.folder.glob("equity-*.csv"))), 1)
        self.assertFalse(list(self.folder.glob("comparison-2026*.csv")))
        self.assertNotIn("cases", report)
        self.assertNotIn("comparison", report)
        self.assertEqual(D(report["final_equity"]), D("498.90"))
        self.assertEqual(report["trade_count"], 2)

    def test_folder_results_match_standalone_replay(self):
        _, report = self.run_folder()
        plan = SimulationPlan.load(self.folder)
        standalone = asyncio.run(replay(plan.settings, Path(self.tmp.name) / "standalone"))
        self.assertEqual({k: v for k, v in report.items() if k not in ("simulation", "data_files")}, standalone)

    def test_different_run_timestamps_change_only_filenames(self):
        first, _ = self.run_folder()
        first_stamp = first.stem.removeprefix("results-")
        second, _ = self.run_folder(NOW + timedelta(seconds=1))
        second_stamp = second.stem.removeprefix("results-")
        for path in self.folder.glob(f"*-{first_stamp}*"):
            other = self.folder / path.name.replace(first_stamp, second_stamp)
            self.assertTrue(other.exists())
            self.assertEqual(path.read_bytes(), other.read_bytes())

    def test_flat_start_uses_single_account_configuration(self):
        self.raw["account"].update(initial_position="flat", entry_price=None)
        self.save_config()
        _, report = self.run_folder()
        self.assertEqual(D(report["final_equity"]), D("499.90"))
        self.assertEqual(report["trade_count"], 1)

    def test_quantity_is_read_from_config(self):
        self.raw["strategy"]["quantity"] = "1"
        self.save_config()
        _, report = self.run_folder()
        self.assertEqual(report["strategy_ticks"], 5)
        self.assertEqual(report["configuration"]["strategy"]["quantity"], "1")
        self.assertEqual(D(report["final_equity"]), D("499.45"))

    def test_old_multi_case_config_is_rejected(self):
        self.raw["initial_conditions"] = [{"name": "baseline"}]
        self.save_config()
        with self.assertRaisesRegex(ValueError, "initial_conditions"):
            self.run_folder()
        self.assertFalse(list(self.folder.glob("actions-*")))

    def test_invalid_account_rejected_before_results_are_created(self):
        for changes in ({"starting_cash": "-1"}, {"initial_position": "flat"},
                        {"starting_cash": "1", "entry_price": "1"}):
            self.raw = folder_config()
            self.raw["account"].update(changes)
            self.save_config()
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_folder()
            self.assertFalse(list(self.folder.glob("results-*")))
            self.assertFalse(list(self.folder.glob("actions-*")))

    def test_overlaps_and_malformed_later_files_reject_run_before_output(self):
        for rows in [[(10, "100")], [(50, "NaN")]]:
            self.archive("bad.zip", rows)
            with self.assertRaises(ValueError):
                self.run_folder()
            self.assertFalse(list(self.folder.glob("results-*")))
            self.assertFalse(list(self.folder.glob("actions-*")))

    def test_existing_timestamp_is_never_overwritten(self):
        self.run_folder()
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        with self.assertRaises(FileExistsError):
            self.run_folder()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_no_zip_files_is_an_error(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        (empty / "config.json").write_text(json.dumps(self.raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no daily ZIP"):
            SimulationPlan.load(empty)


class ThreeDayTests(unittest.TestCase):
    def test_real_three_day_folder_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "simulation_test"
            folder.mkdir()
            original = ROOT / "simulations" / "simulation_test"
            for path in original.iterdir():
                if path.suffix.lower() == ".zip" or path.name == "config.json":
                    shutil.copyfile(path, folder / path.name)
            process = subprocess.run([sys.executable, "-m", "hedger.simulate", str(folder)],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            result_path, = folder.glob("results-*.json")
            report = json.loads(result_path.read_text())
            self.assertEqual(report["data_files"], ["2026-09-29_HYPE.csv.zip", "2026-09-30_HYPE.csv.zip", "2026-10-01_HYPE.csv.zip"])
            self.assertEqual(report["observations"], 25035)
            self.assertEqual(report["strategy_ticks"], 25035)
            self.assertEqual(report["start_utc"], "2026-09-29T02:27:38Z")
            self.assertEqual(report["end_utc"], "2026-10-01T23:59:50Z")
            self.assertNotIn("cases", report)
            self.assertEqual(D(report["initial_equity"]), D("497.25"))
            self.assertEqual(D(report["final_equity"]), D("459.25"))
            self.assertEqual(D(report["net_pnl"]), D("-38.00"))
