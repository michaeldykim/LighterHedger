"""Deterministic exchange adapter: sampled-price triggers and full IOC fills."""
import copy
from .strategy import ACTIVE, Conflict, decimal


class ReplayRuntime:
    def __init__(self, start):
        self.start = self.now = start
        self.client_id = 0

    def monotonic(self):
        return (self.now - self.start).total_seconds()

    def time(self):
        return self.now.timestamp()

    def next_client_id(self):
        self.client_id += 1
        return self.client_id

    @property
    def label(self):
        return self.now.isoformat().replace("+00:00", "Z")


class SimulationState:
    """Fresh, isolated engine state. The action log replaces the Telegram outbox."""

    def __init__(self, emit):
        self.data = {"watch": None, "stopped": False, "paused": None,
                     "established": False, "outbox": [], "telegram_offset": 0}
        self.emit = emit

    def save(self):
        pass

    def event(self, text):
        self.emit("strategy_event", message=text)


class SimulatedExchange:
    def __init__(self, settings, runtime, first_price, emit):
        self.market = settings.market
        self.runtime, self.emit = runtime, emit
        self.position = (-settings.strategy.quantity if settings.initial_position == "short" else decimal(0))
        self.entry_price = first_price if self.position else None
        self.cash = settings.starting_cash
        self.fee_rate = settings.fee_pct / 100
        self.mark = first_price
        self.orders = {}
        self.realized = decimal(0)
        self.fees = decimal(0)
        self.fill_count = self.closed_trades = self.canceled_count = 0

    @property
    def unrealized(self):
        return self.position * (self.mark - self.entry_price) if self.position else decimal(0)

    @property
    def equity(self):
        return self.cash + self.unrealized

    async def snapshot(self):
        return {"position": self.position, "mark": self.mark,
                "orders": copy.deepcopy([o for o in self.orders.values() if o["status"] in ACTIVE]),
                "read_at": self.runtime.monotonic()}

    async def lookup(self, watch):
        if watch.get("lookup_by_client", watch["order_index"] is None):
            row = next((o for o in self.orders.values()
                        if o["client_order_index"] == watch["client_order_index"]), None)
        else:
            row = self.orders.get(watch["order_index"])
        return copy.deepcopy(row)

    async def create(self, spec, client_id):
        if any(o["client_order_index"] == client_id for o in self.orders.values()):
            raise Conflict("Duplicate simulated client order ID")
        index = len(self.orders) + 1
        row = {
            "market_index": self.market.id, "owner_account_index": 0,
            "order_index": index, "client_order_index": client_id,
            "is_ask": spec.is_ask, "type": "stop-loss", "time_in_force": "immediate-or-cancel",
            "reduce_only": spec.reduce_only, "initial_base_amount": str(spec.quantity),
            "remaining_base_amount": str(spec.quantity), "filled_base_amount": "0",
            "filled_quote_amount": "0", "trigger_price": str(spec.trigger), "price": str(spec.price),
            "status": "open", "trigger_status": "mark-price",
        }
        self.orders[index] = row
        self.emit("order_submitted", order_id=index, client_id=client_id, **spec.dump())
        # An already crossed trigger executes immediately at the last observed price.
        self.match(row)

    def advance(self, price):
        self.mark = price
        for row in self.orders.values():
            if row["status"] in ACTIVE:
                self.match(row)

    def match(self, row):
        ask = row["is_ask"]
        trigger, bound = decimal(row["trigger_price"]), decimal(row["price"])
        if (ask and self.mark > trigger) or (not ask and self.mark < trigger):
            return
        self.emit("order_triggered", order_id=row["order_index"], price=str(self.mark))
        quantity = decimal(row["initial_base_amount"])
        if (ask and self.mark < bound) or (not ask and self.mark > bound):
            self.cancel(row, "canceled-too-much-slippage")
            return
        # The strategy supports only one full short or a flat account.
        if (ask and (self.position != 0 or row["reduce_only"])) or (
                not ask and (self.position != -quantity or not row["reduce_only"])):
            self.cancel(row, "canceled-position-conflict")
            return
        realized = decimal(0)
        if ask:
            self.position, self.entry_price = -quantity, self.mark
        else:
            realized = quantity * (self.entry_price - self.mark)
            self.position, self.entry_price = decimal(0), None
            self.closed_trades += 1
        quote = quantity * self.mark
        fee = quote * self.fee_rate
        self.realized += realized
        self.fees += fee
        self.cash += realized - fee
        self.fill_count += 1
        row.update(status="filled", remaining_base_amount="0", filled_base_amount=str(quantity),
                   filled_quote_amount=str(quote))
        self.emit("order_filled", order_id=row["order_index"], side="sell" if ask else "buy",
                  quantity=str(quantity), price=str(self.mark), fee=str(fee), realized_pnl=str(realized),
                  position=str(self.position), cash=str(self.cash), equity=str(self.equity))

    def cancel(self, row, reason):
        row["status"] = reason
        self.canceled_count += 1
        self.emit("order_canceled", order_id=row["order_index"], reason=reason, price=str(self.mark))
