"""Strict, offline simulation configuration and streaming CSV/ZIP input."""
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import zipfile

from .strategy import Config, Market, decimal, specs


def keys(obj, required, optional=()):
    if not isinstance(obj, dict):
        raise ValueError("Configuration sections must be JSON objects")
    missing, extra = set(required) - obj.keys(), obj.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"Configuration keys: missing {sorted(missing)}, unknown {sorted(extra)}")


def integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")
    return value


@dataclass(frozen=True)
class Settings:
    strategy: Config
    market: Market
    starting_cash: Decimal
    initial_position: str
    fee_pct: Decimal
    data_files: tuple[Path, ...]
    raw: dict

    @classmethod
    def load(cls, path):
        path = Path(path)
        with path.open(encoding="utf-8") as source:
            raw = json.load(source)
        return cls.parse(raw, path.parent)

    @classmethod
    def parse(cls, raw, base=Path(".")):
        keys(raw, ("strategy", "market", "account", "data_files"))
        s, m, a = raw["strategy"], raw["market"], raw["account"]
        keys(s, ("symbol", "strike", "quantity", "slippage_pct"))
        keys(m, ("id", "size_decimals", "price_decimals", "min_quantity", "min_notional"))
        keys(a, ("starting_cash", "initial_position", "fee_pct"))
        try:
            strategy = Config(s["symbol"], *(decimal(s[k]) for k in
                              ("strike", "quantity", "slippage_pct")))
            market = Market(integer(m["id"], "market.id", 0, 2**31 - 1), s["symbol"],
                            integer(m["size_decimals"], "size_decimals", 0, 12),
                            integer(m["price_decimals"], "price_decimals", 0, 12),
                            decimal(m["min_quantity"]), decimal(m["min_notional"]))
            cash, fee = decimal(a["starting_cash"]), decimal(a["fee_pct"])
            position = a["initial_position"]
            if position not in ("flat", "short"):
                raise ValueError("initial_position must explicitly be 'flat' or 'short'")
            if cash <= 0 or not 0 <= fee < 100:
                raise ValueError("starting_cash must be positive; fee_pct must be in [0, 100)")
            if market.min_quantity < 0 or market.min_notional < 0:
                raise ValueError("Market minimums cannot be negative")
            specs(strategy, market)
        except (InvalidOperation, TypeError) as error:
            raise ValueError("Invalid numeric configuration value") from error
        files = raw["data_files"]
        if not isinstance(files, list) or not files or any(not isinstance(p, str) or not p for p in files):
            raise ValueError("data_files must be a nonempty list of CSV/ZIP paths in time order")
        return cls(strategy, market, cash, position, fee,
                   tuple((Path(base) / p).resolve() for p in files), raw)


@dataclass(frozen=True)
class Observation:
    timestamp: datetime
    price: Decimal
    source: str

    @property
    def label(self):
        return self.timestamp.isoformat().replace("+00:00", "Z")


@contextmanager
def csv_source(path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".csv") and not n.endswith("/")]
            if len(members) != 1:
                raise ValueError(f"{path.name}: ZIP must contain exactly one CSV")
            with archive.open(members[0]) as binary, io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
                yield stream
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield stream
    else:
        raise ValueError(f"Unsupported data file: {path.name}; expected .csv or .zip")


def observations(paths):
    previous = None
    for path in paths:
        count = 0
        with csv_source(path) as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["timestamp_utc", "price_usd", "source"]:
                raise ValueError(f"{path.name}: expected timestamp_utc,price_usd,source headers")
            for line, row in enumerate(reader, 2):
                try:
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError("incorrect column count")
                    timestamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
                    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
                        raise ValueError("timestamp must explicitly use UTC")
                    timestamp = timestamp.astimezone(timezone.utc)
                    price = decimal(row["price_usd"])
                    if price <= 0:
                        raise ValueError("price must be positive")
                    if previous is not None and timestamp <= previous:
                        raise ValueError("timestamps must be strictly increasing across all files")
                    if not row["source"].strip():
                        raise ValueError("source must not be empty")
                except (ValueError, InvalidOperation, AttributeError) as error:
                    raise ValueError(f"{path.name}:{line}: {error}") from error
                previous = timestamp
                count += 1
                yield Observation(timestamp, price, row["source"])
        if not count:
            raise ValueError(f"{path.name}: no price observations")


def daily_archives(folder):
    """Discover all top-level ZIPs and order by recorded time, not directory order."""
    dated = []
    for path in Path(folder).iterdir():
        if path.is_file() and path.suffix.lower() == ".zip":
            stream = observations((path,))
            try:
                first = next(stream)
                dated.append((first.timestamp, path.name, path.resolve()))
            finally:
                stream.close()
    if not dated:
        raise ValueError(f"{folder}: no daily ZIP files found")
    return tuple(item[2] for item in sorted(dated))


@dataclass(frozen=True)
class SimulationPlan:
    folder: Path
    settings: Settings
    data_files: tuple[Path, ...]

    @classmethod
    def load(cls, folder):
        folder = Path(folder).resolve()
        with (folder / "config.json").open(encoding="utf-8") as source:
            raw = json.load(source)
        keys(raw, ("strategy", "market", "account"))
        paths = daily_archives(folder)
        effective = {**raw, "data_files": [p.name for p in paths]}
        return cls(folder, Settings.parse(effective, folder), paths)
