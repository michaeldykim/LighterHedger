"""Private-chat Telegram control with durable stop and retryable alerts."""
import asyncio
import logging
import time

log = logging.getLogger(__name__)
STATUS_INTERVAL_SECONDS = 15 * 60


class Telegram:
    def __init__(self, session, token, chat_id, state, engine):
        self.session, self.token, self.chat_id = session, token, int(chat_id)
        if self.chat_id <= 0:
            raise ValueError("Use a positive private Telegram chat ID; groups are not supported")
        self.state, self.engine = state, engine
        self.last_poll = 0.0
        self.ready = False

    def healthy(self):
        return self.ready and time.monotonic() - self.last_poll < 30

    async def call(self, method, payload):
        # Never log URLs/exceptions: Telegram URLs contain the secret bot token.
        async with self.session.post(f"https://api.telegram.org/bot{self.token}/{method}",
                                     json=payload) as response:
            if response.status != 200:
                raise RuntimeError(f"Telegram HTTP {response.status}")
            data = await response.json()
        if not data.get("ok"):
            raise RuntimeError("Telegram returned an unsuccessful response")
        return data["result"]

    def handle(self, update):
        message = update.get("message", {})
        chat = message.get("chat", {})
        sender = message.get("from", {})
        if (chat.get("type") != "private" or chat.get("id") != self.chat_id
                or sender.get("id") != self.chat_id or sender.get("is_bot")):
            return
        command = message.get("text", "").strip().split(maxsplit=1)
        command = command[0].split("@")[0].lower() if command else ""
        if command == "stop":
            self.engine.stop()
        elif command == "status":
            self.state.event(self.engine.summary())
        elif command in {"start", "help"}:
            self.state.event("status reports state. stop persistently disables new orders. "
                             "Status is sent every 15 minutes. "
                             "Existing orders can still execute. Resume is local only.")

    async def poll(self):
        failure_logged = False
        while True:
            try:
                updates = await self.call("getUpdates", {
                    "offset": self.state.data["telegram_offset"],
                    "timeout": 10 if self.ready else 0,
                    "limit": 100, "allowed_updates": ["message"],
                })
                for update in updates:
                    self.handle(update)
                    self.state.data["telegram_offset"] = int(update["update_id"]) + 1
                    self.state.save()
                # Drain ALL queued commands before permitting any initial trade.
                if not updates:
                    self.ready = True
                self.last_poll = time.monotonic()
                failure_logged = False
            except asyncio.CancelledError:
                raise
            except Exception:
                self.ready = False
                if not failure_logged:
                    log.warning("Telegram control unavailable; new submissions disabled")
                    failure_logged = True
                await asyncio.sleep(5)

    async def deliver(self):
        next_status = time.monotonic() + STATUS_INTERVAL_SECONDS
        while True:
            try:
                if time.monotonic() >= next_status:
                    self.state.event(self.engine.summary())
                    next_status = time.monotonic() + STATUS_INTERVAL_SECONDS
                outbox = self.state.data["outbox"]
                if outbox:
                    await self.call("sendMessage", {"chat_id": self.chat_id, "text": outbox[0][:4000]})
                    outbox.pop(0)
                    self.state.save()
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Telegram alert delivery failed; queued for retry")
                await asyncio.sleep(5)
