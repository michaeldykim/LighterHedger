"""Send-only Telegram status updates and retryable alerts."""
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
