import argparse
import asyncio
import logging
import os
from pathlib import Path
import signal

from .strategy import Config, Conflict, Market, decimal, specs
from .state import State

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("hedger")


def parser():
    p = argparse.ArgumentParser(description="Lighter mainnet short/flat hedge bot (read-only unless --live)")
    p.add_argument("--symbol", choices=["BTC", "ETH", "HYPE"], required=True)
    p.add_argument("--strike", type=decimal, required=True)
    p.add_argument("--quantity", type=decimal, required=True, help="Fixed asset quantity, not USD")
    p.add_argument("--slippage-pct", type=decimal, default=decimal("1"), help="Percent from trigger; default 1")
    p.add_argument("--poll-seconds", type=float, default=10, help="Exchange polling interval, minimum 5")
    p.add_argument("--live", action="store_true", help="Enable real mainnet order submission")
    p.add_argument("--once", action="store_true", help="One read-only reconciliation, then exit")
    p.add_argument("--resume", action="store_true", help="Resume after local review; reconcile and replace an old strike")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    p.add_argument("--markets", action="store_true", help="Show public market precision/limits only; no credentials")
    return p


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in your local .env file")
    return value


async def run(args):
    import aiohttp
    from dotenv import load_dotenv
    from .engine import Engine
    from .exchange import Exchange, MAINNET
    from .telegram import Telegram

    load_dotenv(args.env_file)
    config = Config(args.symbol, args.strike, args.quantity, args.slippage_pct)
    if not 5 <= args.poll_seconds <= 3600:
        raise ValueError("Poll interval must be between 5 and 3600 seconds")
    if args.live and args.once:
        raise ValueError("--once is read-only; omit --live")
    if args.resume and not args.live:
        raise ValueError("--resume requires --live and local review")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        row = await Exchange.market_row(session, args.symbol)
        market = Market.parse(row)
        buy, sell = specs(config, market)
        log.info("MAINNET %s: quantity %s; buy-close %s (bound %s); sell-open %s (bound %s)",
                 args.symbol, args.quantity, buy.trigger, buy.price, sell.trigger, sell.price)
        if args.markets:
            log.info("%s; current mark %s", market, row["mark_price"])
            return
        account = int(required("LIGHTER_ACCOUNT_INDEX"))
        key_index = int(required("LIGHTER_API_KEY_INDEX"))
        private_key = required("LIGHTER_API_PRIVATE_KEY")
        token, chat = required("TELEGRAM_BOT_TOKEN"), int(required("TELEGRAM_CHAT_ID"))
        if account < 0 or not 3 <= key_index <= 254 or chat <= 0:
            raise ValueError("Invalid account, API key index (3–254), or private Telegram chat ID")
        identity = {"network": MAINNET, "account": account, "symbol": args.symbol,
                    "strike": str(config.strike.normalize()), "quantity": str(config.quantity.normalize()),
                    "slippage_pct": str(config.slippage_pct.normalize()), "telegram_chat": chat}
        # One strategy per account, to avoid competing orders.
        suffix = "live" if args.live else "preview"
        state = State(ROOT / ".state" / f"mainnet-{account}-{suffix}.sqlite3", identity,
                      allow_strike_change=args.live and args.resume)
        signer = None
        tasks = []
        try:
            import lighter
            signer = lighter.SignerClient(url=MAINNET, account_index=account,
                                          api_private_keys={key_index: private_key})
            if signer.check_client():
                raise ValueError("Lighter API key validation failed")
            exchange = Exchange(session, signer, account, key_index, market)
            engine = Engine(config, market, state, exchange, live=args.live)
            telegram = Telegram(session, token, chat, state, engine)
            if args.resume:
                state.data["stopped"] = False
                state.data["paused"] = None
                state.save()
                state.event("Local resume requested; saved order intent will still be reconciled before any submission")
                if state.data.get("strike_change"):
                    state.event(f"Strike change requested: {state.data['identity']['strike']} to {config.strike}. "
                                "Reconciling the old order before replacement.")
            if args.once:
                await engine.tick()
                print(engine.summary())
                return
            shutdown = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, shutdown.set)
            try:
                tasks = [asyncio.create_task(telegram.deliver())]
                state.event(f"Started {'LIVE MAINNET' if args.live else 'READ ONLY'} {args.symbol}. "
                            f"Quantity {args.quantity}; buy {buy.trigger}; sell {sell.trigger}; "
                            f"slippage {args.slippage_pct}%.")
                while not shutdown.is_set():
                    try:
                        await engine.tick()
                    except Conflict as error:
                        engine.warn(str(error), pause=True)
                    except Exception as error:
                        # Exception messages from SDK/network libraries may contain credentials.
                        engine.warn(f"Exchange read failed ({type(error).__name__}); no order submitted this poll")
                    log.info("%s", engine.summary().replace("\n", " | "))
                    try:
                        await asyncio.wait_for(shutdown.wait(), timeout=args.poll_seconds)
                    except asyncio.TimeoutError:
                        pass
                state.data["stopped"] = True
                state.save()
                log.warning("Local shutdown: existing orders remain live; use --resume on next live start")
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if signer is not None:
                await signer.close()
            state.close()


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # The SDK logs signed transaction/auth material at DEBUG: never enable it here.
    logging.getLogger("lighter").setLevel(logging.WARNING)
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, Conflict) as error:
        log.error("%s", error)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        pass
    except Exception as error:
        log.error("Startup failed (%s). Check credentials, connectivity and configuration.", type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
