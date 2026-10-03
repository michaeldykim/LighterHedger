import logging

from .ports import ExchangePort, LiveRuntime, Runtime
from .strategy import ACTIVE, Conflict, Spec, decimal, initial_spec, matches, specs

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, config, market, state, exchange: ExchangePort, can_submit,
                 live=False, *, runtime: Runtime | None = None):
        self.config, self.market, self.state = config, market, state
        self.exchange, self.can_submit, self.live = exchange, can_submit, live
        self.runtime = runtime if runtime is not None else LiveRuntime()
        self.status = "Starting"
        self.last_warning = None
        self.last_mark = None
        self.last_mark_read_at = None

    def warn(self, message, pause=False):
        self.status = "WARNING: " + message
        if pause:
            self.state.data["paused"] = message
        if message != self.last_warning:
            log.warning(message)
            self.state.event("WARNING: " + message)
            self.last_warning = message
        elif pause:
            self.state.save()

    def stop(self):
        self.state.data["stopped"] = True
        self.state.save()  # Persist before acknowledging the remote command.
        self.state.event("STOPPED: no new orders. Existing orders remain live; fill monitoring continues.")
        log.warning("Remote stop latched; existing exchange orders remain live")

    def summary(self):
        price_status = "Mark price: unavailable | Distance to strike: unavailable\n"
        if self.last_mark is not None:
            distance = self.last_mark - self.config.strike
            percentage = distance / self.config.strike * 100
            precision = max(2, self.market.price_decimals)
            age = max(0, int(self.runtime.monotonic() - self.last_mark_read_at))
            sign = "+" if distance >= 0 else "-"
            price_status = (
                f"Mark price: ${self.last_mark:,.{precision}f} (last poll {age}s ago)\n"
                f"Distance to strike: {sign}${abs(distance):,.{precision}f} "
                f"({percentage:+.2f}%)\n"
            )
        return (f"{self.config.symbol} | strike {self.config.strike} | quantity {self.config.quantity}\n"
                f"{price_status}"
                f"Mode: {'LIVE MAINNET' if self.live else 'READ ONLY'}\n"
                f"Stopped: {self.state.data['stopped']} | paused: {self.state.data['paused'] or 'no'}\n"
                f"{self.status}")

    def track(self, spec, row=None, client_id=None):
        self.state.data["watch"] = {
            "spec": spec.dump(), "order_index": int(row["order_index"]) if row else None,
            "client_order_index": int(row["client_order_index"]) if row else client_id,
            "lookup_by_client": row is None,
            "seen_fill": "0", "created_at": self.runtime.time(),
        }
        self.state.data["established"] = True
        self.state.save()

    async def reconcile(self, snapshot):
        watch = self.state.data["watch"]
        spec = Spec.load(watch["spec"])
        active = snapshot["orders"]
        if watch["order_index"] is None:
            found = [o for o in active if int(o["client_order_index"]) == watch["client_order_index"]]
        else:
            found = [o for o in active if int(o["order_index"]) == watch["order_index"]]
        if len(found) > 1:
            raise Conflict("Multiple orders share the tracked identity")
        row = found[0] if found else await self.exchange.lookup(watch)
        if row is None:
            self.warn("Tracked order is not yet visible in active orders or history; no replacement will be sent")
            return False
        if not matches(row, spec, self.market.id, unfilled=False):
            raise Conflict("Tracked order parameters changed or do not match the strategy")
        if watch["order_index"] is None:
            watch["order_index"] = int(row["order_index"])
            self.state.save()
        filled = decimal(row["filled_base_amount"])
        seen = decimal(watch["seen_fill"])
        if filled < seen or filled < 0 or filled > spec.quantity:
            raise Conflict("Invalid or regressing cumulative fill quantity")
        if filled > seen:
            watch["seen_fill"] = str(filled)
            quote = decimal(row["filled_quote_amount"])
            average = quote / filled
            self.state.event(f"FILL {self.config.symbol}: {spec.label}, cumulative {filled}/{spec.quantity}, "
                             f"average price {average}, order {row['order_index']}")
        others = [o for o in active if int(o["order_index"]) != int(row["order_index"])]
        if others:
            raise Conflict("Additional active orders exist in the strategy market")
        if row["status"] in ACTIVE:
            if filled:
                raise Conflict("Partial fill detected; no further orders until locally reviewed")
            expected = decimal(0) if spec.is_ask else -spec.quantity
            if snapshot["position"] != expected:
                raise Conflict("Position changed while the tracked order is active")
            self.status = f"Monitoring order {row['order_index']}: {spec.label} at {spec.trigger}"
            return False
        if row["status"] == "filled" and filled == spec.quantity:
            expected = -spec.quantity if spec.is_ask else decimal(0)
            if snapshot["position"] != expected:
                # History can update ahead of account state. Keep identity and wait.
                self.warn("Filled order is awaiting the expected position; no next order will be sent")
                return False
            if found:
                return False  # Wait until the terminal order leaves active orders.
            self.state.data["watch"] = None
            self.state.save()
            self.status = "Full fill reconciled; next trigger will be checked on the next poll"
            return False
        if row["status"].startswith("canceled"):
            self.state.data["watch"] = None
            # The catch below commits cleared tracking and the pause latch together.
            raise Conflict(f"Tracked order ended as {row['status']} (filled {filled}/{spec.quantity}); review locally")
        raise Conflict("Unrecognized terminal order state")

    async def tick(self):
        snapshot = await self.exchange.snapshot()
        if snapshot is None:
            self.status = "Exchange state changed during reads; waiting for a consistent snapshot"
            return
        self.last_mark = snapshot["mark"]
        self.last_mark_read_at = snapshot["read_at"]
        try:
            if self.state.data["watch"]:
                await self.reconcile(snapshot)
                return
            if self.state.data["stopped"] or self.state.data["paused"]:
                self.status = "New orders disabled; monitoring remains active"
                return
            buy, sell = specs(self.config, self.market)
            if self.state.data["established"]:
                if snapshot["position"] == 0:
                    desired = sell
                elif snapshot["position"] == -self.config.quantity:
                    desired = buy
                else:
                    raise Conflict(f"Unexpected position {snapshot['position']}; expected flat or full short")
            else:
                desired = initial_spec(self.config, self.market, snapshot["position"], snapshot["mark"])
            orders = snapshot["orders"]
            if desired is None:
                if orders:
                    raise Conflict("Flat below the buy trigger with active orders; initial short must be established manually")
                self.warn("Flat below the buy trigger: waiting for you to establish the initial short")
                return
            if orders:
                if len(orders) != 1 or not matches(orders[0], desired, self.market.id):
                    raise Conflict("Existing orders conflict: require one independent trigger-market order matching "
                                   "side, quantity, trigger, execution bound and reduce-only flag")
                self.track(desired, row=orders[0])
                self.state.event(f"Adopted {self.config.symbol} order {orders[0]['order_index']}: {desired.label}")
                self.status = "Matching order adopted"
                return
            self.status = (f"Next: {desired.label}, quantity {desired.quantity}, "
                           f"trigger {desired.trigger}, execution bound {desired.price}")
            if not self.live:
                log.info("READ ONLY: %s", self.status)
                return
            # Telegram stop can run during any awaited read. Recheck immediately before submission.
            if (self.state.data["stopped"] or self.state.data["paused"] or not self.can_submit()
                    or self.runtime.monotonic() - snapshot["read_at"] > 15):
                self.status += " | submission disabled or remote control unavailable"
                return
            client_id = self.runtime.next_client_id()
            self.track(desired, client_id=client_id)  # Durable BEFORE any network write.
            try:
                await self.exchange.create(desired, client_id)
            except Exception:
                self.warn("Submission outcome is uncertain; retaining order intent and reconciling without retry")
                return
            self.state.event(f"SUBMITTED {self.config.symbol}: {self.status}; client order {client_id}")
        except Conflict as error:
            self.warn(str(error), pause=True)
