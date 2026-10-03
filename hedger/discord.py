"""Send-only Discord webhook delivery with a durable, independent queue."""
import asyncio
import logging
import math
import re
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


def validate_webhook_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "discord.com"
            or not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("DISCORD_WEBHOOK_URL must be a Discord HTTPS webhook URL")


class RateLimited(Exception):
    def __init__(self, seconds):
        self.seconds = seconds


class Discord:
    def __init__(self, session, url, state):
        validate_webhook_url(url)
        self.session, self.url, self.state = session, url, state

    async def send(self, text):
        # Never log the URL or exception text: the URL contains credentials.
        async with self.session.post(
            self.url, params={"wait": "true"}, allow_redirects=False,
            json={"content": text, "allowed_mentions": {"parse": []}},
        ) as response:
            if response.status == 429:
                data = await response.json()
                seconds = float(data["retry_after"])
                if not math.isfinite(seconds) or seconds < 0:
                    raise RuntimeError("Invalid rate limit delay")
                raise RateLimited(max(1, seconds))
            if response.status != 200:
                raise RuntimeError(f"Discord HTTP {response.status}")
            data = await response.json()
            if not data.get("id"):
                raise RuntimeError("Discord did not confirm delivery")

    async def deliver(self):
        while True:
            try:
                outbox = self.state.data["discord_outbox"]
                if outbox:
                    await self.send(outbox[0])
                    outbox.pop(0)
                    self.state.save()
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except RateLimited as error:
                await asyncio.sleep(error.seconds)
            except Exception:
                log.warning("Discord alert delivery failed; queued for retry")
                await asyncio.sleep(5)
