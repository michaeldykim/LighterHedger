# Simulation configuration reference

Each simulation folder contains one `config.json` and its daily price ZIPs.
For example, [simulation_test/config.json](../simulations/simulation_test/config.json)
is run with:

```powershell
python -m hedger.simulate simulation_test
```

Every parameter below is required. Missing or unknown keys are rejected; there
are no implicit defaults. Use quoted strings for decimal values, such as `"93"`
or `"0.1"`, and JSON integers for IDs and decimal-place counts.
All numeric values must be finite. JSON does not support comments, so parameter
descriptions live here rather than inside the config.

Examples below use the root sim_config.example.json settings. The market profile is
simulation-only, not verified Lighter metadata. Running the simulation does not
fetch market settings, place live orders or send Telegram messages.

## Strategy parameters

### `strategy.symbol` — asset being simulated

Current value: `"HYPE"`. Accepted values: `"BTC"`, `"ETH"`, or `"HYPE"` (uppercase).

This identifies the asset in the strategy, market and action logs. It also gives
the unit of `strategy.quantity`: with `"HYPE"`, a quantity of `"25"` means 25 HYPE.

Changing this value does not download, convert or select different price data.
The CSV contains price, time and source, but no symbol column; the simulator
cannot verify that its prices belong to the configured asset. Put only the
intended asset's daily ZIPs in that simulation folder.

### `strategy.strike` — reference price for both triggers

Current value: `"93"`, meaning **$93 per HYPE**. Must be greater than zero.

The strategy derives two prices from the strike:

- Buy to close the short: `strike × 1.0001` (0.01% above strike).
- Sell to open the short: `strike × 0.9999` (0.01% below strike).

At $93, these are **$93.0093** for the buy and **$92.9907** for the sell, using
the configured four price decimals. Buy triggers round upward to the price
increment; sell triggers round downward.

The strike stays fixed throughout the replay. It does not follow the recorded
price or change after a fill. Those two trigger multipliers are fixed trading
rules in the code, not additional config parameters. The initial short's
entry price comes from the dataset's first price.

### `strategy.quantity` — fixed position and order size

Current value: `"25"`, meaning **25 HYPE**, not $25. Must be positive.

Every sell opens a short of this quantity; every buy closes that quantity. If
the initial position is `"short"`, it also starts at this size. There is no
automatic resizing as cash or prices change.

With 25 HYPE short, a $1 price increase decreases unrealized P&L by $25; a $1
decrease increases it by $25, while the position remains open.

Quantity must fit `market.size_decimals` exactly and meet `market.min_quantity`
and `market.min_notional`. It is rejected rather than silently rounded. The
existing strategy also requires `quantity × 10^size_decimals` to be a positive
integer smaller than `2^63`.

### `strategy.slippage_pct` — maximum adverse execution price

Current value: `"1"`, meaning **1%**. Must be greater than zero and less than 100;
the current strategy does not accept zero here.

The percentage is measured from each order's **trigger price**:

- Maximum buy price: `buy trigger × (1 + slippage_pct / 100)`.
- Minimum sell price: `sell trigger × (1 - slippage_pct / 100)`.

With the current config, the limits are **$93.9393** for buying and **$92.0608**
for selling. They round inward to the configured precision so rounding never
widens the allowance. Equality with the limit is allowed.

If an active buy order sees the recorded price jump through its $93.0093 trigger:

- At **$93.50**, it fills completely at $93.50.
- At **$94.50**, it is canceled because the price exceeds $93.9393. The strategy
  pauses when it reconciles that cancellation; it does not automatically retry.

For an active sell, a recorded price of **$92.50** triggers and fills it, but
**$91.50** triggers cancellation because it is below the minimum sell price.

This is a price limit, not a fee or an automatic 1% adjustment. Fills use the
recorded price when allowed; actual liquidity and between-sample moves are not
modeled. Increasing this parameter permits worse execution prices without
changing either trigger.

## Market parameters

### `market.id` — local market identifier

Current value: `0`. Must be a JSON integer from **0 to 2,147,483,647**.

Simulated orders carry this ID, and the engine checks it when matching orders
to the configured market. In offline replay it is a local identifier: `0` does
not claim that HYPE's actual exchange market ID is zero.

Changing it does not change prices, symbol selection, fees or trading rules.

### `market.size_decimals` — permitted quantity precision

Current value: `2`. Must be a JSON integer from **0 to 12**.

This defines the smallest representable asset quantity as `10^-size_decimals`.
With two decimals, the increment is **0.01 HYPE**: `"25"` and `"25.01"` are valid
quantities, while `"25.001"` is rejected.

This validates quantity; it does not round it or control price precision. A
value of `0` permits whole-asset quantities only. Other minimum-order checks
still apply.

### `market.price_decimals` — trigger and execution-bound precision

Current value: `4`. Must be a JSON integer from **0 to 12**.

The price increment is `10^-price_decimals`, so four decimals means **$0.0001**.
It controls how order prices are rounded:

- Buy trigger: round up; sell trigger: round down.
- Maximum buy execution price: round down; minimum sell execution price: round up.

For example, changing this to `2` at a $93 strike produces a **$93.01** buy
trigger and a **$92.99** sell trigger, instead of $93.0093 and $92.9907. This can
change when orders trigger and whether fills are permitted.

It does not round the historical data or actual simulated fill prices. Those
remain the recorded prices. The strategy additionally requires every rounded
trigger and execution bound, multiplied by `10^price_decimals`, to be greater
than zero and smaller than `2^32`; an incompatible price/precision combination
is rejected.

### `market.min_quantity` — minimum order size in asset units

Current value: `"0"`, meaning **no additional minimum quantity restriction**.
Must be zero or positive.

The configured quantity must be at least this amount. For example, a minimum
of `"10"` permits the current 25-HYPE orders; a minimum of `"30"` rejects them.
Equality is allowed.

Setting this to zero does not permit zero-sized orders: `strategy.quantity`
must still be positive and fit the permitted precision.

### `market.min_notional` — minimum order value in dollars

Current value: `"0"`, meaning **no additional minimum dollar-value restriction**.
Must be zero or positive.

The strategy checks this once when validating the order specifications, using:

```text
quantity × minimum sell execution price >= min_notional
```

For the current config, that value is `25 × $92.0608 = $2,301.52`. A minimum
of `"2000"` passes; `"2400"` fails. Equality is allowed. The check uses the sell
execution bound, not the current recorded price, starting cash or strike.

This is an order-value rule, not a collateral requirement. It does not require
the account to hold $2,301.52 in cash.

## Account parameters

### `account.starting_cash` — initial collateral balance

Current value: `"500"`, meaning **$500**. Must be greater than zero.

Cash is the simulated perpetual account's collateral balance. Opening a short
does not credit the proceeds of selling the asset. Closing a short adds its
realized profit or subtracts its realized loss; execution fees reduce cash.

Equity includes unrealized P&L in addition to cash. An initial short uses the
first recorded price as its entry price, so initial unrealized P&L is zero and
initial equity equals starting cash. For example, with $500 cash and the first
price of $87.71, the short starts with a $87.71 entry price and $500 equity.

Replay return uses initial equity as its denominator. The simulator does not
model margin requirements or liquidation, so starting cash does not cap order size.

### `account.initial_position` — position already held at replay start

Current value: `"short"`. Accepted values are **`"short"` or `"flat"`**.

- `"short"`: start with `strategy.quantity` short at the first dataset price.
- `"flat"`: start with no position and no entry price.

This initializes a pre-existing position. It does not simulate an opening trade,
charge an entry fee or count that position as a fill. Longs and partial-sized
initial shorts are not supported.

The first price and current position determine startup behavior:

| Position | First price below buy trigger | First price at/above buy trigger |
| --- | --- | --- |
| Short | Submit a buy-to-close trigger | Pause because the starting state conflicts with the strategy |
| Flat | Wait; do not automatically open a short | Submit a sell-to-open trigger |

With the current $93.0093 buy trigger and first price of $87.71, `"short"`
submits the closing trigger. A flat account waits and can begin trading if a
later recorded price reaches the buy threshold. The simulator never creates a
manual initial short on its own.

### Initial entry price � derived automatically

There is no `account.entry_price` config parameter. For a short start, the
simulator uses the very first price in the complete, chronologically ordered
dataset. It initializes the position once; opening the next daily ZIP does not
reset its entry price. For a flat start, the entry price is absent until a sell fills.

```text
Unrealized P&L = quantity � (entry price - latest recorded price)
Realized P&L   = quantity � (entry price - buy fill price)
```

For example, with a first recorded price of $87.71, closing an initial 25-HYPE
short at $88 realizes `25 � ($87.71 - $88) = -$7.25` before fees.

Entry price does not set the triggers. After a new sell fills, its actual fill
price becomes the entry price of that new short. Results record the derived
`initial_entry_price` (null for flat starts), and the initialization action also
records it. Remove `entry_price` from older configs; unknown keys are rejected.
This behavior is identified by result model version `sampled-price-v3`.

### `account.fee_pct` — fee charged on each simulated fill

Current value: `"0"`, meaning **zero fees**. Must be zero or greater and less
than 100. `"0.1"` means **0.1%**, not 10%.

Each buy or sell fill deducts:

```text
Fee = filled quantity × fill price × fee_pct / 100
```

For example, with `"0.1"`, a 25-HYPE fill at $94 costs
`25 × $94 × 0.001 = $2.35`. A later fill incurs its own fee at its own price.

No fee is charged for submitting or canceling an unfilled order, or for the
pre-existing initial position. Fees reduce cash and equity and are reported
separately. Unlike `slippage_pct`, this parameter changes trading costs, not
the prices at which an order is allowed to fill. The value is configured locally,
not looked up from the exchange.

## Timing

Timing comes directly from the dataset; there is no timing parameter in the
simulation config. The runner immediately reads each row, sets the historical
clock to its timestamp, evaluates existing orders at its price, and runs the
strategy once. It never sleeps, inserts ticks between rows or skips closely
spaced observations. This also applies across gaps and daily ZIP boundaries.

For example, if an existing buy fills at the price on row 2, the engine reconciles
that fill on row 2 and submits the opposite order on row 3. If a newly submitted
order fills immediately on row 3, it is reconciled on row 4 and the next order
can be submitted on row 5. There is no additional strategy tick after the last row.

The earlier `poll_seconds` simulation parameter has been removed. Delete it from
older configs; unknown keys are rejected. This does not change the live bot's
separate `--poll-seconds` option. New results identify this timing behavior as
`sampled-price-v3` and report one `strategy_ticks` count per observation.

## Input selection and the legacy config

For the normal folder command, do not add input/output paths or a simulation
name to `config.json`. The folder name is the simulation name, every top-level
ZIP is included in recorded-time order, and timestamped output files go into
that same folder. These choices are not config parameters.

The older `--config FILE --output DIR` command additionally requires:

### `data_files` — explicit input list for legacy mode only

This is a nonempty JSON array of CSV or ZIP paths, for example:

```json
"data_files": ["simulations/simulation_test/2026-10-02_HYPE.csv.zip"]
```

Relative paths are resolved from the config file's directory. Files are replayed
in the supplied order, which must be chronological; the legacy command does not
automatically discover or sort them. Timestamps must increase strictly across
files. This field is rejected in the normal simulation-folder config, where ZIP
discovery is automatic. It appears in saved effective configurations because the
runner records the files it selected.
