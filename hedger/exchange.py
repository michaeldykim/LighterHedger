"""Read-only REST reconciliation plus the pinned official SDK for signing."""
import asyncio
import time

from .strategy import Conflict, Market, decimal

MAINNET = "https://mainnet.zklighter.elliot.ai"


class Exchange:
    def __init__(self, session, signer, account, key_index, market):
        self.session = session
        self.signer = signer
        self.account = account
        self.key_index = key_index
        self.market = market

    def auth(self):
        token, error = self.signer.create_auth_token_with_expiry(api_key_index=self.key_index)
        if error or not token:
            raise RuntimeError("Lighter authorization failed")
        return token

    @staticmethod
    async def public(session, endpoint, params=None, headers=None):
        async with session.get(MAINNET + "/api/v1/" + endpoint,
                               params=params, headers=headers) as response:
            if response.status != 200:
                raise RuntimeError(f"Lighter {endpoint}: HTTP {response.status}")
            data = await response.json()
        if data.get("code") != 200:
            raise RuntimeError(f"Lighter {endpoint}: unsuccessful response")
        return data

    async def read(self, endpoint, params=None):
        return await self.public(self.session, endpoint, params, {"Authorization": self.auth()})

    @classmethod
    async def market_row(cls, session, symbol):
        data = await cls.public(session, "orderBookDetails")
        rows = [r for r in data["order_book_details"]
                if r["symbol"] == symbol and r["market_type"] == "perp"]
        if len(rows) != 1:
            raise Conflict("Could not identify exactly one perpetual market")
        return rows[0]

    async def view(self):
        account, orders = await asyncio.gather(
            self.read("account", {"by": "index", "value": str(self.account)}),
            self.read("accountActiveOrders", {"account_index": self.account,
                                             "market_id": self.market.id}),
        )
        accounts = account["accounts"]
        if len(accounts) != 1 or int(accounts[0]["index"]) != self.account:
            raise Conflict("Account response does not identify the configured account")
        positions = [p for p in accounts[0]["positions"] if int(p["market_id"]) == self.market.id]
        if len(positions) > 1:
            raise Conflict("Multiple position records for one market")
        position = decimal(0)
        if positions:
            p = positions[0]
            amount = decimal(p["position"])
            sign = int(p["sign"])
            if amount < 0 or sign not in {-1, 0, 1} or (amount and not sign):
                raise Conflict("Invalid position sign or amount")
            position = amount * sign
        rows = orders["orders"]
        if not isinstance(rows, list):
            raise Conflict("Incomplete active-order response")
        if any(int(o["owner_account_index"]) != self.account or
               int(o["market_index"]) != self.market.id for o in rows):
            raise Conflict("Active-order response contains an unexpected account or market")
        return position, sorted(rows, key=lambda o: int(o["order_index"]))

    async def snapshot(self):
        # REST endpoints are not atomic. A changing snapshot must not place an order.
        first = await self.view()
        row = await self.market_row(self.session, self.market.symbol)
        if Market.parse(row) != self.market:
            raise Conflict("Market specifications changed; restart to validate them")
        second = await self.view()
        if first != second:
            return None
        mark = decimal(row["mark_price"])
        if mark <= 0:
            raise Conflict("Invalid mark price")
        return {"position": second[0], "orders": second[1], "mark": mark,
                "read_at": time.monotonic()}

    async def lookup(self, watch):
        if watch.get("lookup_by_client", watch["order_index"] is None):
            data = await self.read("accountOrders", {
                "account_index": self.account,
                "client_order_indexes": str(watch["client_order_index"]),
            })
            rows = [o for o in data["orders"]
                    if int(o["client_order_index"]) == watch["client_order_index"]]
        else:
            # Manual orders may all have client index zero. Use the exchange order ID.
            rows = []
            cursor = None
            for _ in range(10):
                params = {"account_index": self.account, "market_id": self.market.id, "limit": 100}
                if cursor:
                    params["cursor"] = cursor
                data = await self.read("accountInactiveOrders", params)
                rows = [o for o in data["orders"] if int(o["order_index"]) == watch["order_index"]]
                next_cursor = data.get("next_cursor")
                if rows or not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
        if len(rows) > 1:
            raise Conflict("Order lookup is ambiguous")
        if rows and watch["order_index"] is not None and int(rows[0]["order_index"]) != watch["order_index"]:
            raise Conflict("Client order index resolved to a different exchange order")
        if rows and (int(rows[0]["market_index"]) != self.market.id or
                     int(rows[0]["owner_account_index"]) != self.account):
            raise Conflict("Order lookup returned the wrong market/account")
        return rows[0] if rows else None

    async def create(self, spec, client_id):
        # No retry here: a timeout is an unknown outcome, not proof of rejection.
        async with asyncio.timeout(20):
            _, response, error = await self.signer.create_sl_order(
                market_index=self.market.id, client_order_index=client_id,
                base_amount=int(spec.quantity * 10 ** self.market.size_decimals),
                trigger_price=int(spec.trigger * 10 ** self.market.price_decimals),
                price=int(spec.price * 10 ** self.market.price_decimals),
                is_ask=spec.is_ask, reduce_only=spec.reduce_only,
            )
        if error or response is None or response.code != 200:
            # Keep the journal even for an error: the exchange remains the authority.
            raise RuntimeError("Order submission was not confirmed; reconciliation required")
