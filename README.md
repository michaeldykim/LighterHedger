# Lighter Hedger

Local Python bot for one BTC, ETH or HYPE perpetual market on **Lighter mainnet**.
The size input is a fixed asset quantity. It alternates between **short that quantity**
and **flat**, never intentionally opening a long.

| Account state | Next order |
| --- | --- |
| Short the configured quantity | Buy to close at strike × 1.005, reduce-only |
| Flat after a confirmed buy fill | Sell to open at strike × 0.9975 |
| Flat at startup, mark at/above buy trigger | Sell to open at strike × 0.9975 |
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

## Offline historical simulation

The simulator uses the **same `Engine` and trading rules** as the live bot with a
simulated exchange implementing `ExchangePort` (`snapshot`, `lookup`, `create`).
The existing `Exchange` remains the live REST/SDK adapter. An injected runtime
supplies historical time and sequential order IDs; live runs retain real clocks
and random client IDs. No credentials, exchange requests, Telegram, SDK, or
third-party packages are needed for simulation. Python 3.11+ works on Windows,
macOS and Linux; the live runner and its journal still require macOS/Linux.

From the repository folder:

```sh
python -m hedger.simulate simulation_test
```

Each folder under `simulations/` is a separate simulation. Its folder name is the
simulation name, and it contains `config.json` and the daily price ZIPs. A folder
path can also be supplied, for example `python -m hedger.simulate simulations/simulation_test`.
All top-level `.zip` files (case-insensitive extension) are discovered automatically
and ordered by the **first recorded UTC timestamp inside each archive**, regardless
of directory listing order or filename. Overlapping data is rejected. Strategy
state continues across file/day boundaries without resetting.

Results are saved directly inside the simulation folder. Each run has a UTC
timestamp in its output filenames, including microseconds, so previous runs are
preserved. Generated result files are ignored by Git and are never read as price
inputs. Each run starts with fresh state independent of live SQLite journals.

The example sets strike **$93**, quantity **25 HYPE**, cash **$500**, an existing
short of **25 HYPE entered at $86.09**, zero fees, and the existing 1% execution
bound. It runs one strategy tick per recorded price. Its market profile is simulation-only:
4 price decimals, 2 quantity decimals, and no minimum quantity/notional checks.
The market ID is a local identifier. These are **not fetched or verified Lighter
market specifications**; supply exchange metadata in config when needed.

### Configuration

See the [parameter-by-parameter configuration reference](docs/simulation-config.md)
for units, allowed values, formulas, rounding rules and worked examples for every
setting, including slippage, fees and position initialization.

Edit `simulations/simulation_test/config.json`. Each config defines exactly one
simulation through its `strategy`, `account` and `market` sections.
Set the strike, quantity, starting cash, entry price and fees
directly in those sections. Specify decimal values as strings. For a flat start,
set `account.initial_position` to `"flat"` and `account.entry_price` to `null`.
There is no case list or per-case override system.

The runner validates the config and complete dataset before creating result
files, then keeps one immutable copy of the observations in memory. Each price
observation advances one engine, account, clock and order history. There is no
wall-clock waiting.

The three supplied ZIPs contain 25,035 observations from September 29 through
October 1, 2026. The first price is $86.20; the baseline retains the approved
$86.09 entry price and thus starts at $497.25 equity ($500 cash minus $2.75
unrealized P&L).

### Data and execution

Each daily ZIP must contain exactly one CSV. No extraction is necessary.
The required header is:

```csv
timestamp_utc,price_usd,source
2026-09-30T00:00:00Z,86.09,binance
```

Timestamps must explicitly use UTC and increase strictly across all input files;
prices must be finite and positive. Empty files, duplicate/out-of-order timestamps,
ambiguous archives and invalid config values are rejected rather than repaired.

The simulation **does not wait in real time**. It loops over the dataset and runs
exactly one strategy tick per row, using that row's timestamp and price. Existing
orders see the price before the engine runs. There are no extra ticks between
rows, even across gaps, and closely spaced rows are never skipped. The dataset's
sampling rate determines the strategy's cadence. There is no `poll_seconds`
simulation setting; remove that key from older configs. The live bot's separate
`--poll-seconds` option is unchanged.

Recorded prices serve as both mark and executable prices. A buy triggers at or
above its threshold; a sell triggers at or below its threshold. Triggered orders
fill fully at the recorded price if within the inclusive execution bound.
Otherwise they are canceled, causing the existing strategy to pause after
reconciliation. Newly submitted orders whose thresholds are already crossed
execute immediately against the most recent recorded price. A confirmed fill
is reconciled on that row's strategy tick, and the next leg is submitted on the
following row. If an order fills immediately during submission, reconciliation
happens on the next row and the opposite order follows on the row after that.
These are the existing engine's reconciliation rules. There is no extra tick
after the final observation.

No between-sample price interpolation, order-book liquidity, partial fills,
network latency, funding, margin checks or liquidation is modeled. Equity can
therefore go negative without liquidation. Existing startup/conflict rules still
apply: for example, flat below the buy trigger waits for an initial short; a
starting short at/above that trigger pauses.

### Results and accounting

- `actions-<UTC timestamp>.jsonl`: ordered historical timestamps and deterministic sequence/ID
  values for initialization, submissions, triggers, fills, cancellations, engine
  events, status changes and completion.
- `equity-<UTC timestamp>.csv`: initial equity and marks before/after each row's strategy tick,
  with cash, position, entry price, realized/unrealized P&L, fees and drawdown.
  Multiple rows can have the same timestamp, distinguished by the `event` column.
- `results-<UTC timestamp>.json`: simulation name, ordered input filenames,
  observation count, data fingerprint and performance summary, including the
  effective config, sources, final position,
  open orders, any unreconciled order and pause state. A failed/incomplete run has
  no completed results file; any logs already written are partial.

Results use model version `sampled-price-v2` and report `strategy_ticks`, which
equals the number of observations. Earlier `sampled-price-v1` outputs used a
separate polling schedule and can have different outcomes.

For example, `results-20261002T120000000000Z.json` identifies a run started at
12:00:00 UTC on October 2. All three files for that run share that timestamp.

Cash represents perpetual collateral: opening a short does not add sale proceeds.
Closing realizes `quantity * (entry price - fill price)`; each simulated fill
deducts `quantity * fill price * fee_pct / 100`. Initial positions are pre-existing,
with no simulated entry trade or entry fee. For a flat start, set
`initial_position` to `"flat"` and `entry_price` to `null`.

Equity is cash plus unrealized P&L. Replay net P&L is final equity minus initial
equity, and return uses initial equity as its denominator. Thus P&L accumulated
before the first observation is excluded from replay return, even if it is later
realized. Maximum drawdown is the largest peak-to-trough equity decrease over
recorded events; percentage drawdown uses the corresponding running peak.
`trade_count` counts fills (both buys and sells); `closed_trade_count` counts
completed short positions, including closure of a pre-existing initial short.
Open positions are valued at the final price and are not forcibly closed.

The same data, config and implementation produce byte-identical result **contents**.
Only the output filenames carry the wall-clock run timestamp. Financial arithmetic
uses a fixed 28-digit Decimal context; result contents do not contain wall-clock
timestamps, execution duration, random IDs or output-directory paths.

The previous single-case CLI remains available for a config with an explicit
chronologically ordered `data_files` list (plain CSV and ZIP inputs supported):

```sh
python -m hedger.simulate --config sim_config.example.json --output sim_results/hype-day1
```

This legacy mode requires a new output directory and writes `actions.jsonl`,
`equity.csv` and `summary.json`. The root example config covers September 30 only;
use the folder command to run all three days with the folder's config.

Simulation tests run without the live dependencies, including on Windows:

```sh
python -m unittest discover -s tests -p test_simulation.py -v
python -m unittest discover -s tests -p test_simulation_folder.py -v
python -m unittest discover -s tests -p test_runtime.py -v
```

They cover complete strategy cycles, both slippage-cancellation directions,
immediate execution, accounting and fees, one tick per data row, startup conflicts,
input validation, no future-price lookahead, repeatability, archive ordering,
output preservation and the supplied three-day simulation.
The full existing suite still requires Unix `fcntl` for the live state journal.
