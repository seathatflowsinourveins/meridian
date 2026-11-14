# Meridian lanes

The order lanes and their runbooks, the owner's steps before and during a run, and the Orca
service notes. Rules, budgets and run records: `docs/HANDBOOK.md`. At most 180 lines
(`size-budget.toml`).

| Lane | Orders go to | Market data | What keeps it off a real-money account |
|---|---|---|---|
| IBKR paper (M1) | the IB Gateway logged in to Paper Trading, `127.0.0.1:4002` | the same Gateway | `meridian/boundary.py` refuses unless the Gateway is a paper login, before and after every run |
| Sandbox (M2) | the engine's sandbox execution client, a simulated venue inside the engine | the IB Gateway, data only | no broker at all: no IBKR execution client in its configuration, and a test that fails if one is added |
| Alpaca paper (M3) | Alpaca's paper endpoint | Alpaca | the paper endpoint hard-coded; `tests/test_paper_only.py` fails on a live endpoint or live key name |

No agent starts a lane, in any mode: every run is started and attended by the owner. A run's
terminal check (typing PAPER) only proves a terminal, and agents have terminals too: any Orca
session can type into one (`orca-ide terminal send`).

## Orca

Orca's `orca-cli` and `orchestration` skills are in `.agents/skills/`; the command is
`orca-ide`. Its runtime is the `orca-serve` user service on 127.0.0.1:6790: if it is down,
report that or run `systemctl --user start orca-serve`, never `orca-ide open`, `serve` or
`serve service install`, which can listen on every interface. Agents' servers bind 127.0.0.1.

## IBKR paper lane (owner only)

Before a run:

- IB Gateway is installed by `deploy/wsl/setup.sh gateway`. The owner starts it with
  `~/Jts/ibgateway/1050/ibgateway` (its window shows through WSLg) and logs in to
  **Paper Trading**. The lane connects to `127.0.0.1:4002` and nowhere else.
- In the Gateway, Configure > Settings > API > Settings: socket port 4002, **Read-Only API
  unticked**, "Allow connections from localhost only" ticked. The Gateway listens on every
  interface (`*:4002`) and the machine uses mirrored networking, so that box is what keeps
  other hosts out. `~/Jts/jts.ini` lists `TrustedIPs=127.0.0.1` only; the box itself is stored
  in the Gateway's encrypted settings and can only be checked in its window.
- Optional, stricter: an allowlist in `risk/boundary.contract.json`. To create it, the owner
  runs this; it shows the reported account and prints the contract only after PAPER is typed:
  `mkdir -p risk && C="$(uv run python -m meridian.boundary contract)" && printf '%s\n' "$C" > risk/boundary.contract.json`
- The rc9 source (nautilus_trader@da6b57a:
  crates/adapters/interactive_brokers/src/execution/reports.rs:L204-211) requests all open
  orders with either `fetch_all_open_orders` value; the startup AAPL.XNAS cache check
  includes reconciled external orders and account positions. The order request is a
  snapshot (https://www.interactivebrokers.com/docs/tws-api/doc/order-management/open-orders),
  so it does not guarantee visibility of later orders. Only reports returned and successfully
  cached are visible; Client Portal/mobile coverage remains unverified. Before `fill`, check
  all paper-account AAPL orders and positions by hand in IBKR, across every entry route.
- The paper account has no open order or position in AAPL. The lane refuses to submit if it sees one.

The lane refuses unless the Gateway's `~/Jts/jts.ini` says `tradingMode=p`, the Gateway
listens on port 4002 only, and it reports one account whose id has the paper form (a D
prefix, as in NautilusTrader's IB guide examples: a convention, not a documented rule).
Details in `meridian/boundary.py`.

```bash
uv run python -m meridian.ibkr_paper order      # reconcile, one DAY LIMIT order, stop
uv run python -m meridian.ibkr_paper fill       # regular hours: buy 1 that fills, close it
uv run python -m meridian.ibkr_paper restart    # reconcile only; places nothing
```

`order` places one DAY LIMIT BUY of 1 share, 2% under the bid, and cancels it once the venue
accepts it. A pass is "accepted, then cancelled, nothing filled". If the order ever fills, the
run fails, the lane sends no second order, and the owner closes the share by hand.
`fill` runs only on weekdays from 09:30 to 15:55 New York time. It places one DAY LIMIT BUY of
1 share 2% above the ask, so it fills, and on that fill one DAY LIMIT SELL of the filled
quantity 2% under the lower of the bid and the fill price, so the run ends flat. A pass is
"both filled, flat at stop". If an order is still working when the run stops, the run fails and
says so: run `restart` (its record shows any open order or share) before closing anything by hand.
The engine's own output goes to `runs/…-engine.log`, which can show the account id and stays on
this machine; the terminal shows only the lane's lines, and `evidence/` is scrubbed. In order
and fill mode every check runs again after PAPER is typed, and a change to the Gateway in the
meantime (a restart, a re-login, another port) refuses.

## Sandbox lane (M2)

The engine's sandbox execution client is a venue simulated inside NautilusTrader: its own
matching engine fills the strategy's orders against live market data, in a simulated cash
account. Here it takes the IB Gateway's market data and runs upstream's built-in `ExecTester`
strategy on 1 share of AAPL, as upstream's sandbox example does (`meridian/sandbox_node.py`).
The node has one data client, IB's, and the sandbox as its only execution client:
`tests/test_sandbox_lane.py` fails if any other execution client is added, and runs the lane
offline on a fake feed.

Before a run: the Gateway set-up of the IBKR lane above. The account needs no particular
state, because no order goes to it.

```bash
uv run python -m meridian.sandbox_lane run      # owner only, attended; about 90 seconds
```

It runs the IBKR lane's paper checks, asks for PAPER at the terminal, checks again, runs the
node for a minute (the engine's output goes to `runs/...-engine.log`), checks again, and
writes the record. In that minute `ExecTester` buys 1 share at market on the first quote, keeps
a LIMIT buy resting 5.00 USD under the bid, and on stop cancels it and sells the share. A pass
is: the paper checks passed again after the run; the node ran its full time and stopped without
an error (a stop before its time fails the run); the trader started; AAPL.XNAS came from IB and
quotes arrived; the engine registered the sandbox and no other execution client; the strategy
placed orders and the simulated venue accepted one; every order went to the sandbox, was booked
on the simulated account and ended filled, cancelled or expired; none was denied or rejected;
nothing was open at stop. The record is `evidence/M2-sandbox-<stamp>-run.json`.

The lane asks IB for delayed-frozen data, upstream's default, so outside regular hours it
trades against the last quote IB has; the sandbox keeps no trading calendar. A run in which no
quote arrives fails. After a run the owner can check in IB's own window that the paper account
shows no new order. Optional and not yet tried: with Read-Only API ticked the Gateway refuses
orders from every API client; the IBKR lane needs it unticked, and whether market data still
flows with it ticked has not been checked.

## Alpaca paper lane (M3, owner only)

`meridian.alpaca_lane` wires session quotes and the [execution adapter](adr/data/m3-alpaca.md#3-current-adapter-carried-changed-and-omitted) with the [order budget](HANDBOOK.md#rate-budgets).
Quotes carry prices only: Alpaca documents round-lot sizes but its Asset model has no
per-symbol shares-per-lot field ([Asset](https://alpaca.markets/sdks/python/api_reference/trading/models.html#asset),
[quotes](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), read 2026-11-13).
The client validates then drops sizes, publishing zero as unknown following rc9's CoinAPI and
IB adapters (paths and lines in `UPSTREAM.md`); **no consumer may use this lane's quote sizes**.

Before a run: stop the previous writer and confirm it is stopped;
check that AAPL has no open order or position, across every entry route on the paper account.
AAPL is the same equity as upstream's IBKR stock example. Reconciliation claims AAPL.ALPACA;
working orders outside that universe or from another writer refuse. No agent starts either mode.
Copy `deploy/alpaca-lane.template.json` to ignored `local/alpaca-lane.json`; fill its two null fields: `order_budget_rows_path`
(relative to that file or absolute) and `quote_max_age_ns` (positive integer; no code default).
Both files belong outside the tree or under `local/` (backups there are ignored too); [rows must pass the production loader](HANDBOOK.md#rate-budgets).
Missing/invalid values refuse without printing paths or values; `--settings` selects the settings file.

### Alpaca credentials

The owner creates the two encrypted files in a distro terminal (no TPM, so the host key):
```bash
sudo systemd-creds setup
systemd-ask-password -n "Alpaca paper key id:" | sudo systemd-creds encrypt --with-key=host --name=alpaca-paper-key-id - /etc/credstore.encrypted/alpaca-paper-key-id
systemd-ask-password -n "Alpaca paper secret key:" | sudo systemd-creds encrypt --with-key=host --name=alpaca-paper-secret-key - /etc/credstore.encrypted/alpaca-paper-secret-key
```
`deploy/systemd/meridian-alpaca-paper.service` is prepared, not installed/enabled, and has no `[Install]` section. It runs as `paper`, loads both credentials by absolute path (missing files prevent startup), and runs only `python -m meridian.alpaca.credentials`: presence/format checks, no socket. M7 installs `/opt/meridian`. The loader refuses missing credentials; key values come only from their files, whose directory is named by `CREDENTIALS_DIRECTORY`.

From the repository root, in a distro terminal the owner started outside Orca, use the system
manager (the existing encrypted credentials target it, not the per-user manager):

```bash
sudo systemd-run --pty --wait --collect --service-type=exec \
  --unit=meridian-alpaca-attended --uid="$(id -u)" --gid="$(id -g)" \
  --working-directory="$PWD" --property=UMask=0077 \
  --property=LoadCredentialEncrypted=alpaca-paper-key-id:/etc/credstore.encrypted/alpaca-paper-key-id \
  --property=LoadCredentialEncrypted=alpaca-paper-secret-key:/etc/credstore.encrypted/alpaca-paper-secret-key \
  "$PWD/.venv/bin/python" -m meridian.alpaca_lane restart
```

Replace the final `restart` with `order` for the one-order run; append `--settings /absolute/path`
for another local settings file. `--pty` supplies the terminal for PAPER; `--wait` waits even
if the PTY is detached. The fixed unit name prevents overlapping instances of this command,
but cannot exclude another writer. `--uid` uses the owner's current checkout permissions.
This command follows installed systemd 259's systemd-run(1) and systemd.exec(5), read 2026-11-13.
It was **not run**: credential loading/decryption, TTY attachment, sudo policy and the actual
paper connection remain untested; only the owner may perform that attended check.

`restart` reconciles, sends no order or cancel, stops, and passes only with the instrument clean
and execution coverage complete. `order` asks for PAPER, repeats all local checks, then buys
one share with a DAY LIMIT 2% below a fresh bid, rounded down to the venue tick. It checks
`quote_age_ns` before pricing and again at paced submission; missing/stale quotes place nothing.
[24/5](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api) (read 2026-11-13): Sunday 20:00–Friday 20:00 New York; paper-calendar rows check holidays and early closes.
Regular uses IEX; overnight uses free real-time indicative `overnight`; pre/after uses delayed SIP, whose age includes 15 minutes (an owner limit of 15 minutes or less refuses it).
DAY LIMIT sends `extended_hours=true`; overnight requires eligible, unhalted asset flags. Boundaries discard cached quotes and refuse queued submissions across sessions (sources in `UPSTREAM.md`).
It cancels after venue `new` proves routing; queued `accepted` alone cannot pass. A pass is routed, cancelled, nothing filled,
flat with no open or in-flight order at stop. Any fill fails and sends no second order; the
owner inspects and closes any share by hand. An unresolved order also fails: inspect it before
acting; there is no stop-time cancel or close. The M1 time limits apply (25 s restart, 60 s order).
All local checks run again after the run. Engine output and failures stay in `runs/`; passing
records go to `evidence/M3-alpaca-paper-<stamp>-<mode>.json`. Public records contain no broker
text or identifiers, include commission citations and counts of paper-default/reviewed budget
rows (also shown at the terminal), session/feed used to price the order, and only the quote-age limit's presence. No real run has been performed.

`uv run python -m meridian.alpaca_sim` is a simulation, not a lane; no typed word. It exercises the unchanged one-order strategy and native engine order flow, excluding the Alpaca adapter, order budget, credentials, streams and venue.
Quotes are synthetic, generated in process: no market or recorded data, no real price.
PASS means accepted, then cancelled, nothing filled and flat at stop; any fill means FAIL.
Records go only to `runs/*-simulation.json`, never `evidence/`; it is offline and keyless.
