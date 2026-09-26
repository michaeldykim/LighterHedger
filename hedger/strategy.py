"""Pure trading rules. No networking or secret material."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

D = Decimal
ACTIVE = {"pending", "open", "in-progress"}


class Conflict(ValueError):
    pass


def decimal(value):
    result = D(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite numeric value")
    return result


@dataclass(frozen=True)
class Config:
    symbol: str
    strike: Decimal
    quantity: Decimal
    slippage_pct: Decimal

    def __post_init__(self):
        if self.symbol not in {"BTC", "ETH", "HYPE"}:
            raise ValueError("Supported markets: BTC, ETH, HYPE")
        for value in (self.strike, self.quantity, self.slippage_pct):
            if not value.is_finite() or value <= 0:
                raise ValueError("Strike, quantity and slippage must be finite and positive")
        if self.slippage_pct >= 100:
            raise ValueError("Slippage must be less than 100 percent")


@dataclass(frozen=True)
class Market:
    id: int
    symbol: str
    size_decimals: int
    price_decimals: int
    min_quantity: Decimal
    min_notional: Decimal

    @classmethod
    def parse(cls, row):
        if row["market_type"] != "perp" or row["status"] != "active" or row.get("is_frozen"):
            raise Conflict("Market is not an active perpetual market")
        if row.get("market_config", {}).get("force_reduce_only"):
            raise Conflict("Market is restricted to reduce-only orders")
        return cls(int(row["market_id"]), row["symbol"], int(row["supported_size_decimals"]),
                   int(row["supported_price_decimals"]), decimal(row["min_base_amount"]),
                   decimal(row["min_quote_amount"]))

    def price(self, value, rounding):
        return value.quantize(D(1).scaleb(-self.price_decimals), rounding=rounding)


@dataclass(frozen=True)
class Spec:
    is_ask: bool
    quantity: Decimal
    trigger: Decimal
    price: Decimal
    reduce_only: bool

    def dump(self):
        return {"is_ask": self.is_ask, "quantity": str(self.quantity),
                "trigger": str(self.trigger), "price": str(self.price),
                "reduce_only": self.reduce_only}

    @classmethod
    def load(cls, obj):
        return cls(obj["is_ask"], decimal(obj["quantity"]), decimal(obj["trigger"]),
                   decimal(obj["price"]), obj["reduce_only"])

    @property
    def label(self):
        return "SELL to open short" if self.is_ask else "BUY to close short"


def specs(config, market):
    scaled = config.quantity * 10 ** market.size_decimals
    if scaled != scaled.to_integral_value() or scaled <= 0 or scaled >= 2**63:
        raise ValueError(f"Quantity must have at most {market.size_decimals} decimal places")
    if config.quantity < market.min_quantity:
        raise ValueError(f"Quantity is below market minimum {market.min_quantity}")
    buy = market.price(config.strike * D("1.005"), ROUND_CEILING)
    sell = market.price(config.strike * D("0.9975"), ROUND_FLOOR)
    slip = config.slippage_pct / 100
    # Round execution bounds inward so the specified cap is never widened.
    buy_cap = market.price(buy * (1 + slip), ROUND_FLOOR)
    sell_cap = market.price(sell * (1 - slip), ROUND_CEILING)
    for price in (buy, sell, buy_cap, sell_cap):
        if not 0 < price * 10 ** market.price_decimals < 2**32:
            raise ValueError("Trigger or execution bound is outside the exchange price range")
    if config.quantity * sell_cap < market.min_notional:
        raise ValueError(f"Order value is below market minimum {market.min_notional}")
    return (Spec(False, config.quantity, buy, buy_cap, True),
            Spec(True, config.quantity, sell, sell_cap, False))


def matches(order, spec, market_id, *, unfilled=True):
    """Only independent, fixed-size trigger-market orders may be adopted."""
    required = (
        int(order["market_index"]) == market_id,
        order["is_ask"] is spec.is_ask,
        order["type"] == "stop-loss",
        order["time_in_force"] == "immediate-or-cancel",
        order["reduce_only"] is spec.reduce_only,
        decimal(order["initial_base_amount"]) == spec.quantity,
        decimal(order["trigger_price"]) == spec.trigger,
        decimal(order["price"]) == spec.price,
        str(order.get("parent_order_index", 0)) == "0",
        str(order.get("parent_order_id", "0")) in {"0", ""},
        str(order.get("to_trigger_order_id_0", "0")) in {"0", ""},
        str(order.get("to_trigger_order_id_1", "0")) in {"0", ""},
        str(order.get("to_cancel_order_id_0", "0")) in {"0", ""},
    )
    if not all(required):
        return False
    return not unfilled or (
        decimal(order["filled_base_amount"]) == 0
        and decimal(order["remaining_base_amount"]) == spec.quantity
        and order["status"] in ACTIVE
        and order["trigger_status"] in {"mark-price", "ready"}
    )


def initial_spec(config, market, position, mark):
    buy, sell = specs(config, market)
    if position not in (D(0), -config.quantity):
        raise Conflict(f"Expected flat or short {config.quantity}; actual position is {position}")
    if mark >= buy.trigger:
        if position != 0:
            raise Conflict("Price is at/above the buy trigger, but the account is not flat")
        return sell
    if position == 0:
        return None  # User must establish the initial short below the buy trigger.
    return buy
