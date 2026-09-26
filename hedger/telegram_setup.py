"""Discover private-chat IDs without putting a bot token in a URL or shell history."""
import asyncio
import os

from .__main__ import ROOT


async def main():
    import aiohttp
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Set TELEGRAM_BOT_TOKEN in .env first")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.post(f"https://api.telegram.org/bot{token}/getUpdates",
                                json={"timeout": 0, "allowed_updates": ["message"]}) as response:
            if response.status != 200:
                raise ValueError(f"Telegram HTTP {response.status}; check token and stop any other bot process")
            data = await response.json()
        if not data.get("ok"):
            raise ValueError("Telegram request failed")
    ids = {u["message"]["chat"]["id"] for u in data["result"]
           if u.get("message", {}).get("chat", {}).get("type") == "private"
           and u["message"].get("from", {}).get("id") == u["message"]["chat"]["id"]}
    if not ids:
        print("Send start to your bot in Telegram, then run this command again.")
    else:
        for chat_id in sorted(ids):
            print(f"Private chat ID: {chat_id}")
        print("Put your own ID in TELEGRAM_CHAT_ID in .env. Stop this helper before running the bot.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as error:
        print(str(error))
        raise SystemExit(2) from None
    except Exception as error:
        print(f"Telegram setup failed ({type(error).__name__}); check connectivity.")
        raise SystemExit(1) from None
