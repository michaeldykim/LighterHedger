"""Offline replay CLI: python -m hedger.simulate simulation_test."""
import argparse
import asyncio
import csv
from datetime import datetime, timezone
from decimal import Context, ROUND_HALF_EVEN, localcontext
import hashlib
import itertools
import json
import logging
from pathlib import Path
import zipfile

from .engine import Engine
from .sim_exchange import ReplayRuntime, SimulatedExchange, SimulationState
from .sim_input import Settings, SimulationPlan, observations
from .strategy import ACTIVE, decimal

MODEL_VERSION = "sampled-price-v2"
SIMULATIONS = Path(__file__).resolve().parent.parent / "simulations"


def json_text(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


class ReplaySession:
    """One engine/account advanced by the historical stream."""

    def __init__(self, settings, first, actions, equity_file):
        self.settings, self.first, self.last = settings, first, first
        self.runtime = ReplayRuntime(first.timestamp)
        self.actions = actions
        self.sequence = 0
        self.exchange = SimulatedExchange(settings, self.runtime, first.price, self.emit)
        self.initial_equity = self.exchange.equity
        self.initial_unrealized = self.exchange.unrealized
        if self.initial_equity <= 0:
            raise ValueError("Starting cash plus initial unrealized P&L must be positive")
        self.state = SimulationState(self.emit)
        self.engine = Engine(settings.strategy, settings.market, self.state, self.exchange, lambda: True,
                             live=True, runtime=self.runtime)
        self.writer = csv.writer(equity_file, lineterminator="\n")
        self.writer.writerow(("timestamp_utc", "event", "price_usd", "position", "entry_price",
                              "cash", "realized_pnl", "unrealized_pnl", "fees", "equity",
                              "drawdown", "drawdown_pct", "paused"))
        self.peak = self.initial_equity
        self.max_drawdown = self.max_drawdown_pct = decimal(0)
        self.last_status = None
        self.strategy_ticks = self.count = 0
        self.sources = set()
        self.digest = hashlib.sha256()
        self.emit("initialized", model_version=MODEL_VERSION, configuration=settings.raw,
                  initial_price=str(first.price), initial_equity=str(self.initial_equity),
                  initial_position=str(self.exchange.position),
                  entry_price=str(self.exchange.entry_price) if self.exchange.entry_price is not None else None)
        self.record_equity("initial")

    def emit(self, kind, **fields):
        self.sequence += 1
        self.actions.write(json_text({"sequence": self.sequence, "timestamp_utc": self.runtime.label,
                                      "kind": kind, **fields}) + "\n")

    def record_equity(self, event):
        exchange = self.exchange
        self.peak = max(self.peak, exchange.equity)
        drawdown = self.peak - exchange.equity
        drawdown_pct = drawdown / self.peak * 100
        self.max_drawdown = max(self.max_drawdown, drawdown)
        self.max_drawdown_pct = max(self.max_drawdown_pct, drawdown_pct)
        self.writer.writerow((self.runtime.label, event, exchange.mark, exchange.position,
                              exchange.entry_price if exchange.entry_price is not None else "",
                              exchange.cash, exchange.realized, exchange.unrealized, exchange.fees,
                              exchange.equity, drawdown, drawdown_pct, self.state.data["paused"] or ""))

    async def tick(self):
        await self.engine.tick()
        self.strategy_ticks += 1
        if self.engine.status != self.last_status:
            self.emit("strategy_status", message=self.engine.status, paused=self.state.data["paused"])
            self.last_status = self.engine.status
        self.record_equity("strategy_tick")

    async def advance(self, observation):
        # Exactly one strategy tick per row, after existing orders see its price.
        self.runtime.now = observation.timestamp
        self.exchange.advance(observation.price)
        self.record_equity("price")
        await self.tick()
        self.count += 1
        self.sources.add(observation.source)
        self.digest.update(json_text([observation.label, str(observation.price), observation.source]).encode("utf-8") + b"\n")
        self.last = observation

    def finish(self):
        exchange = self.exchange
        net_pnl = exchange.equity - self.initial_equity
        summary = {
            "model_version": MODEL_VERSION, "configuration": self.settings.raw,
            "observations_sha256": self.digest.hexdigest(),
            "sources": sorted(self.sources), "observations": self.count, "strategy_ticks": self.strategy_ticks,
            "start_utc": self.first.label, "end_utc": self.last.label,
            "initial_price": str(self.first.price), "final_price": str(self.last.price),
            "starting_cash": str(self.settings.starting_cash),
            "initial_unrealized_pnl": str(self.initial_unrealized), "initial_equity": str(self.initial_equity),
            "final_cash": str(exchange.cash), "final_equity": str(exchange.equity),
            "realized_pnl": str(exchange.realized), "unrealized_pnl": str(exchange.unrealized),
            "fees": str(exchange.fees), "net_pnl": str(net_pnl),
            "return_pct": str(net_pnl / self.initial_equity * 100),
            "max_drawdown": str(self.max_drawdown), "max_drawdown_pct": str(self.max_drawdown_pct),
            "trade_count": exchange.fill_count, "closed_trade_count": exchange.closed_trades,
            "orders_submitted": len(exchange.orders), "orders_canceled": exchange.canceled_count,
            "final_position": str(exchange.position),
            "final_entry_price": str(exchange.entry_price) if exchange.entry_price is not None else None,
            "open_orders": [o for o in exchange.orders.values() if o["status"] in ACTIVE],
            "unreconciled_order": self.state.data["watch"],
            "paused": self.state.data["paused"], "strategy_status": self.engine.status,
            "assumptions": [
                "Recorded prices serve as both mark and executable prices; no interpolation or liquidity model.",
                "Full fills at observed price within bound; otherwise IOC cancellation and strategy pause.",
                "Exactly one strategy tick per recorded price; no ticks between rows or wall-clock delays.",
                "Existing orders match before each strategy tick; newly submitted crossed orders match immediately.",
                "Initial position is pre-existing; no initial entry trade or entry fee is simulated.",
                "Cash is perpetual collateral balance; short sale notional is not credited to cash.",
                "No funding, margin requirements, liquidation, network latency or partial fills.",
                "No forced final close or extra post-data tick; positions valued at the last recorded price.",
                "Market precision and minimums are supplied by configuration, never fetched online.",
            ],
        }
        self.emit("completed", net_pnl=summary["net_pnl"], final_equity=summary["final_equity"],
                  trade_count=exchange.fill_count, paused=summary["paused"])
        return summary


async def replay(settings, output):
    """Legacy single-case API; fresh state, fixed arithmetic and no networking."""
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        stream = observations(settings.data_files)
        try:
            first = next(stream)
            output = Path(output)
            output.mkdir(parents=True, exist_ok=False)
            with (output / "actions.jsonl").open("x", encoding="utf-8", newline="\n") as actions, \
                    (output / "equity.csv").open("x", encoding="utf-8", newline="") as equity:
                session = ReplaySession(settings, first, actions, equity)
                for observation in itertools.chain((first,), stream):
                    await session.advance(observation)
                summary = session.finish()
            write_json(output / "summary.json", summary)
            return summary
        finally:
            stream.close()


async def run_simulation(folder, *, started_at=None):
    """Replay one folder's configuration; timestamp filenames only."""
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        plan = SimulationPlan.load(folder)
        # Validate the entire input before writing outputs, then replay this
        # immutable snapshot even if files subsequently change on disk.
        prices = tuple(observations(plan.data_files))
        settings = plan.settings
        initial_pnl = (settings.strategy.quantity * (settings.entry_price - prices[0].price)
                       if settings.initial_position == "short" else decimal(0))
        if settings.starting_cash + initial_pnl <= 0:
            raise ValueError("Starting equity must be positive")
        instant = started_at if started_at is not None else datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ValueError("Run timestamp must have a timezone")
        stamp = instant.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        result_path = plan.folder / f"results-{stamp}.json"
        actions_path = plan.folder / f"actions-{stamp}.jsonl"
        equity_path = plan.folder / f"equity-{stamp}.csv"
        all_paths = [result_path, actions_path, equity_path]
        if any(p.exists() for p in all_paths):
            raise FileExistsError(f"Results already exist for timestamp {stamp}; refusing to overwrite")
        with actions_path.open("x", encoding="utf-8", newline="\n") as actions, \
                equity_path.open("x", encoding="utf-8", newline="") as equity:
            session = ReplaySession(settings, prices[0], actions, equity)
            for observation in prices:
                await session.advance(observation)
            summary = session.finish()
        report = {
            **summary, "simulation": plan.folder.name,
            "data_files": [p.name for p in plan.data_files],
        }
        # A complete results file is written only after replay and logs finish.
        write_json(result_path, report)
        return result_path, report


def main():
    parser = argparse.ArgumentParser(description="Deterministic offline strategy replay")
    parser.add_argument("simulation", nargs="?", help="Folder name under simulations/, or a simulation folder path")
    parser.add_argument("--config", type=Path, help="Legacy single-case config (requires --output)")
    parser.add_argument("--output", type=Path, help="Legacy single-case output directory")
    args = parser.parse_args()
    if args.simulation and (args.config or args.output):
        parser.error("Use a simulation folder OR --config with --output")
    if not args.simulation and not (args.config and args.output):
        parser.error("Specify a simulation folder, or both --config and --output")
    logging.basicConfig(level=logging.ERROR)
    try:
        if args.simulation:
            supplied = Path(args.simulation)
            folder = SIMULATIONS / supplied if len(supplied.parts) == 1 and not supplied.is_absolute() else supplied
            result_path, report = asyncio.run(run_simulation(folder))
            print(f"{report['simulation']}: {len(report['data_files'])} ZIPs, "
                  f"{report['observations']} prices")
            print(f"{report['trade_count']} fills; P&L ${report['net_pnl']}; "
                  f"equity ${report['final_equity']}; return {decimal(report['return_pct']):.4f}%")
            print(f"Results: {result_path}")
        else:
            summary = asyncio.run(replay(Settings.load(args.config), args.output))
            print(f"Replayed {summary['observations']} prices; {summary['trade_count']} fills. "
                  f"Net P&L: ${summary['net_pnl']}; final equity: ${summary['final_equity']}; "
                  f"return: {summary['return_pct']}%")
            print(f"Results: {args.output.resolve()}")
    except (ValueError, OSError, csv.Error, zipfile.BadZipFile) as error:
        parser.exit(2, f"Simulation failed: {error}\n")


if __name__ == "__main__":
    main()
