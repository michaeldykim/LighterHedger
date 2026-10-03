# Lighter Hedger

Local Python bot for one BTC, ETH or HYPE perpetual market on **Lighter mainnet**.
The size input is a fixed asset quantity. It alternates between **short that quantity**
and **flat**, never intentionally opening a long.

| Account state | Next order |
| --- | --- |
| Short the configured quantity | Buy to close at strike × 1.0001, reduce-only |
| Flat after a confirmed buy fill | Sell to open at strike × 0.9999 |
| Flat at startup, mark at/above buy trigger | Sell to open at strike × 0.9999 |
| Flat at startup, mark below buy trigger | Warn and wait for you to establish the initial short |
| Conflicting position or orders | Warn and pause new submissions |

Both legs are native exchange trigger-market orders (`stop-loss`, immediate-or-cancel).
Default slippage is **1% relative to the trigger**, as selected for this bot:
buy execution bound = buy trigger × 1.01; sell execution bound = sell trigger × 0.99.
This bounds the exchange's market-order execution price; it does not guarantee a fill.
Triggers use Lighter's **mark price**, not the last traded price.

Buy triggers round upward and sell triggers downward to the market tick. Execution
bounds round inward to avoid widening the slippage cap. Asset quantity is never
silently rounded. Precision and minimum size/value are fetched from the exchange.

## Setup

Requires Python **3.11+**, macOS or Linux. A Python 3.12 environment is already installed
in this checkout's `.venv`. To create one on another machine:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Fill in `.env` locally:

- `LIGHTER_ACCOUNT_INDEX`: the account/subaccount that owns the position.
- `LIGHTER_API_KEY_INDEX`: the index of your registered trading API key (3–254).
- `LIGHTER_API_PRIVATE_KEY`: that **Lighter API key's** private key, not a wallet key.
- `TELEGRAM_BOT_TOKEN`: token for a dedicated bot created through Telegram's [BotFather](https://t.me/BotFather).
- `TELEGRAM_CHAT_ID`: your positive numeric **private chat** ID.

For Telegram, create the bot, set its token in `.env`, open a private chat with it,
and send `start`. Discover the chat ID without putting the token into a browser URL:

```sh
.venv/bin/python -m hedger.telegram_setup
```

Set the resulting ID in `.env`. Use your own private chat; groups are intentionally
unsupported. Only messages whose chat ID **and sender ID** match your configured ID
can control the bot. Do not share the token or run another consumer of this bot's updates.

## Run

The values below are **examples**, not a selected live trade. Replace the symbol,
strike and quantity with your intended parameters. `--quantity 0.001` means 0.001 BTC
when `--symbol BTC` is used, 0.001 ETH for ETH, etc.

Public market/precision check, without credentials or order submission:

```sh
.venv/bin/python -m hedger --symbol BTC --strike 100000 --quantity 0.001 --markets
```

One read-only account reconciliation (requires Lighter and Telegram settings, but does
not send Telegram messages or place orders):

```sh
.venv/bin/python -m hedger --symbol BTC --strike 100000 --quantity 0.001 --once
```

Continuous read-only monitoring and Telegram control: omit `--once`.
To enable **real mainnet trading**, add `--live`:

```sh
.venv/bin/python -m hedger --symbol BTC --strike 100000 --quantity 0.001 --slippage-pct 1 --live
```

On macOS, optionally prefix the command with `caffeinate -i` to prevent idle sleep.
The computer and network must remain available to detect fills, place subsequent
orders and receive Telegram commands. Native orders already on Lighter can execute
even while the computer is offline.

The bot leaves leverage and margin settings as configured on Lighter. Ensure the
account has enough collateral for the selected size. This version runs **one market
per account** and one consumer per Telegram bot; use separate subaccounts/bots for
independent simultaneous strategies.

## Alerts and shutoff

Send `status`, `stop`, or `help` in Telegram.
While running continuously, the bot also sends a status message every 15 minutes,
including when stopped or paused. The first automatic status is 15 minutes after
startup; restarting resets the timer. Delivery failures are queued for retry.

- `status`: show configuration, latest polled mark price and quote age, distance to
  strike in dollars and percent, read-only/live mode, stop/pause flags and latest status.
  Distance is mark price minus strike; the percentage is relative to strike.
- `stop`: durably disable **new orders only**. It does not cancel pending orders or
  close the position. Monitoring and fill alerts continue while the process runs.
- `help`: describe commands. `start` does not resume trading.

Stop is effective when the local bot receives the command. An order already being
submitted may still reach Lighter. Wait for the STOPPED acknowledgment; existing
orders can execute afterward. The command cannot reach a sleeping or offline computer.
New submissions are disabled when Telegram polling fails or its heartbeat goes stale.

Exchange polling defaults to 10 seconds (configurable with `--poll-seconds`, minimum 5).
After confirming a complete fill and the resulting account position, the opposite
trigger is created on a subsequent poll. There is a polling/network delay between legs;
this is not an atomic pair of orders. If price has already crossed that next trigger,
it may execute immediately, subject to the execution-price bound.

Alerts report observed cumulative fills, including partial fills. Partial fills,
cancellations (including slippage/liquidity failures), external position changes and
conflicting orders pause new submissions for local review. No automatic market-order
fallback, resizing or cancellation is performed. Alerts persist locally for retry;
a crash after Telegram accepts a message but before local acknowledgment can duplicate
that alert.

## Restart and reconciliation

State is stored in `.state/mainnet-<account>-live.sqlite3`; read-only previews have a
separate state file. Keep these files. They contain the tracked exchange/client order
ID, configuration, stop/conflict flags, Telegram cursor and pending alerts, not keys.

- Matching manually placed orders are adopted only when there is exactly one active
  order in the selected market with matching side, fixed size, trigger, **execution
  bound**, type, IOC setting and reduce-only flag. Attached/bracket orders are not adopted.
- Other markets are not modified. Additional active orders in the selected market are
  conflicts even if they were entered manually.
- An intent is committed to disk **before** submission. A timeout or rejection does
  not cause blind resubmission. The bot looks for that specific order, then follows
  its fill history and verifies the resulting position.
- Missing order history blocks new submissions. It never means "filled". For old
  manually adopted orders, lookup is bounded to 1,000 recent inactive orders.
- If submission remains uncertain or the order is absent forever, inspect it on Lighter
  and resolve the recorded intent locally before continuing. This version deliberately
  has no "forget pending order and retry" shortcut; `--resume` does not bypass that guard.
- Restart with the same parameters. Changing saved configuration is rejected.
- `stop`, Ctrl+C and SIGTERM persist a stop flag. After inspecting the position and
  resolving any conflicts, restart locally with the same parameters plus `--live --resume`.
  That clears the stop/conflict latch but still reconciles any tracked order first.
- A forced crash preserves the prior stop flag and intent. Starting again without a
  saved stop flag resumes reconciliation and trading if `--live` is supplied.

Fresh startup above the buy trigger expects a flat account. During an established
cycle, the recorded order and actual confirmed position determine the next leg.
REST reads are checked twice for consistency, but manual trading concurrently with a
submission cannot be made atomic with the bot; keep this account/market dedicated.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests simulate the repeating cycle, startup rules, manual adoption, partial fills,
cancellations, delayed position updates, ambiguous submissions across restarts,
control authentication, persistent stop and exchange argument encoding. Public mainnet
metadata can be checked with `--markets`. Authenticated order placement and Telegram
delivery require your locally configured credentials; no live trade is needed to run
the unit tests.

References: [official Python SDK](https://github.com/elliottech/lighter-python),
[SDK stop-market example](https://github.com/elliottech/lighter-python/blob/a38b6405f362fc14a562fe7a97df03f3ee756bc1/examples/orders/create_stop_loss_market_order.py),
[Telegram Bot API](https://core.telegram.org/bots/api).
