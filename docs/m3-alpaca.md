# M3 groundwork: the Alpaca paper lane

Written 2026-11-12 for M3 (plan 9.2): what the earlier Sextant line's Alpaca adapter did, why its
startup reconciliation failed in three attended starts, and what `meridian/alpaca/` carries.
Sources: the owner's public repos `seathatflowsinourveins/sextant` at `33cdee7` and `sextant-paper`
at `a991b73`, read with `gh api`, cited as `repo@commit:path:lines` or `repo#N`. A second reader
re-checked each study claim at its source, not the note as it stands. Nothing here talked to Alpaca.

## 1. What the earlier adapter does

Built on NautilusTrader 2.0.0rc8 (tag commit `d53849b`) and alpaca-py 0.44.0 (`cc4cb3b7`),
Python 3.13 (sextant-paper@a991b73:pyproject.toml:L5-9, UPSTREAMS.md:L9-10). Owner's design.

| Module (sextant-paper@a991b73:src/sextant/) | Lines | What it does |
|---|---|---|
| `alpaca/execution.py` | 1,406 | the execution client: paced submit, modify (PATCH), cancel, query; the `trade_updates` stream; startup reports. sextant's copy (1,213 lines) is older: imported by sextant-paper#3, then fixed in #10 to #31 |
| `alpaca/wire.py` | 225 | decimal-text payloads, the house order-id namespace, `AccountGateway`: every execution REST call, reads included, through one pacer, SDK retries off |
| `alpaca/reports.py` | 337 | Alpaca rows as order, position and fill reports at instrument precision |
| `execution/pacer.py`, `risk/controls.py` | 249, 124 | the account order budget (section 5) and its 16 registry rows |
| `alpaca/{config,factories,constants,parsing,providers}.py` | 15-109 | configs holding key *names*; MARGIN and NETTING factories; assets as `Equity`; a provider whose asset calls skip the pacer |
| `alpaca/{data,stream_facts,trade_updates}.py` | 908, 110, 111 | market data and ranking facts (`trade_updates.py` is market-data corrections, not the order stream) |
| `alpaca/commission.py`, `data/alpaca_history.py` | 83, 280 | sourced paper fee rows; a historical data downloader |

A second order path, the old Paper B writer (`paper/b_protector_main.py`), used typed SDK calls
through its own paced client; to the node its orders are another writer's. Paper is hard-coded
(`paper=True`, no switch); keys are environment-variable names injected per process from
systemd-creds files (sextant@33cdee7:docs/adr/0028-local-keys.md:L15-25).

## 2. Why startup reconciliation failed in three attended starts (2026-11-11)

Paper B's "stage 1" starts (sextant#470, rows 10-11) all died in the engine's startup
reconciliation, before the node's flat-account gate. The engine keeps only "Failed to get mass
status from ALPACA" (sextant#671, #688).

| Start (New York) | What failed | Fix | Proven |
|---|---|---|---|
| 1, about 15:10 | No cause recorded. From start 2: ended orders in symbols outside the node's loaded 100-name claim list made a report fail ("report instrument is unavailable"), and one such row failed the whole read (sextant@33cdee7:docs/handbook/lessons.jsonl:L138) | sextant#671 (`d537f3ea`): a per-stage trace. sextant#693 (`1dfb44ce`): skip and count ended rows in unloaded symbols; working ones refuse | #671 by start 2 |
| 2, about 16:17 | The same, now visible: 437 order rows, 261 in unloaded symbols, 1,300 fill rows, 0 positions (lessons.jsonl:L138-139) | sextant#693 | start 3 passed it |
| 3, 16:30 to 17:28 (likely after 17:19) | 435 ended unloaded rows were skipped; then the fill stage refused 8,422 of 8,822 fills: the venue's FILL history reaches further back than its order listing (sextant#697). The refusal of unexplained fills predates sextant#636, which made startup read every FILL page | sextant#697 (`f433e67a`): count fills older than the oldest listed order | never |

No fourth start is recorded at either pin, and all three ran sextant code: none of sextant-paper's
later fixes (#10 to #31) met a real start. The rehearsal had passed because its fake history had
none of these shapes (lessons.jsonl:L138); start 3's cause was probably latent in starts 1 and 2
(inferred). The previous writer played no part: sextant#663 fixed a gate refusal on its cancelled
order, and no start reached the gate. Receipts carry no commit; starts 2 and 3 show counts from
unmerged changes (inferred: unmerged trees). Found while porting, on rc9: a fresh node treats
every earlier order as external and drops it unless a strategy claims the instrument.

## 3. What is carried and what is not

Carried, each with offline tests (`tests/test_alpaca_{wire,trade_updates,reconcile,node,paper}.py`):
- One gateway sends every REST call, reads and asset loads included, through one budget,
  CANCEL > REDUCE > MODIFY > QUERY > SUBMIT (a sell is REDUCE); SDK retries off; a 429 pauses.
- Commands run as tasks, never awaited in the engine's command queue. One on-wire mark splits
  "not sent" (refused once) from "sent" (settled only by a documented refusal, POST 403/422 or
  DELETE 422/429, by the stream, or by a later read). A DELETE 204 is an attempt; one
  unresolved cancel per order. Decimal text end to end, whole shares, prices on tick.
- Startup reads wait for the stream's subscription acknowledgement. A lost stream, an update that
  cannot be classified (20 events are; `restated`, corrections, anything new are not) or an answer
  that cannot be read or mapped (a body not JSON, a listing, its pages, a row, its symbol) is a gap,
  a failed request is not: no new order until a full read issued after it reaches the engine; an
  open-order check can stop new orders, not resume them. Executions go on once each, none the engine
  holds (it infers one a read or check shows first); a recovery read below its fills is reread.
- Reconciliation reads the whole order history, fails closed on any gap, withholds and counts ended
  history in unloaded symbols (a row without one refuses), counts fills older than the order
  history, and names the failing stage with reasons from a fixed, value-free list. Engine settings:
  no missing-order generation, unbounded lookback, unresolved submissions retained, open-order
  checks, not in-flight (the old node had neither), none waiting over a minute; re-checked on rc9.
- No invented fee: connect refuses without a sourced per-fill commission (the old line's was a
  sourced zero, sextant@33cdee7:lanes/paper/shared-node.params.json:L26-47).

Left out: modify and successor lineage, trailing stops and the exit guard (protection, M4); owner
custody and claim lists (one writer per account); the fee registry; the market-data client (it
comes with the attended order); wire counters; handover leases; live-lane and IBKR parts.

Changed on purpose: the stream runs on the node's loop (alpaca-py 0.45.0's is asynchronous) and is
pinned to the paper host before the SDK signs in (websockets would follow a redirect); keys come
from systemd credentials; every REST call has a timeout (open in sextant#463); the next order page
asks one microsecond past the edge, so edge rows return whether `until` is inclusive or not (the old
pager refused the exclusive case); FILL paging stops once it passes the oldest listed order; ended
history no simple report carries (`replaced`, brackets) is counted without fills and refuses with
them; a cancel's slot is taken before the budget; a cancel refused unsent names its command, so the
engine puts the order back; another writer's working order refuses the start and its activity stops
new orders; no report is volunteered ahead of the stream's fills (one from the stream is a gap), and
no execution the engine already holds is handed on (one out of sequence is a gap).

## 4. How the port answers each failure

| Failure | Answer | Test (`tests/test_alpaca_node.py`: the real engine, a synthetic venue) |
|---|---|---|
| no cause recorded | per-stage trace: requests, rows, failure class, HTTP status, fixed reason | `test_a_failed_start_records_*` |
| ended orders in unloaded symbols | withheld and counted; a working one, at any leg depth, refuses | `test_failure_case_2_*` |
| fills older than the order history | counted; a newer unexplained fill still refuses | `test_failure_case_3_*` |
| start 3's whole shape | 437 orders and 8,822 fills: passes, reading 5 FILL pages, not 89 | `test_the_third_starts_shape_*` |
| an old writer's orders | ended ones are history; a working one refuses | `test_failure_case_1_*` |
| rc9 drops unclaimed earlier orders | the strategy claims its universe (`external_order_instrument_ids`) | `test_without_the_claim_*` |

## 5. The order budget

M2 harvests the old pacer and keeps its interface (`meridian/order_budget/`, branch
`m2/order-budget`, its own pull request). This pull request does not build on it: it stays
independent, against main, and `meridian/alpaca/budget.py` states the part used here as a
`Protocol`, exactly as sextant-paper@a991b73:src/sextant/execution/pacer.py has it (blob `49a30e9`,
same in sextant). Once the order-budget pull request is merged, a follow-up makes `budget.py` import
`ActionKind` and `PacerRefused` from `meridian.order_budget.pacer`: names, signatures and enum
values are the same there, but as separate classes pyright rejects M2's pacer for the `Protocol` and
the gateway would not catch M2's `PacerRefused`. The lane should start its pacer empty: a new one
starts with a full burst. Rows: 180 requests per 60 s of Alpaca's 200, burst 18, 429 backoff 1 s
doubling to 30 s. Tests use a stand-in; connect refuses until a pacer is wired. A cancel costs two
requests (read, DELETE); readers stop at the budget's page count (90,000 orders).

## 6. Keys

`deploy/systemd/meridian-alpaca-paper.service` runs as `paper` and loads two encrypted credentials
by absolute path, so a missing file stops it before it starts; the code also refuses without
them and never reads the environment. The owner, in a distro terminal (no TPM, so the host key):

```bash
sudo systemd-creds setup
systemd-ask-password -n "Alpaca paper key id:" | sudo systemd-creds encrypt --with-key=host --name=alpaca-paper-key-id - /etc/credstore.encrypted/alpaca-paper-key-id
systemd-ask-password -n "Alpaca paper secret key:" | sudo systemd-creds encrypt --with-key=host --name=alpaca-paper-secret-key - /etc/credstore.encrypted/alpaca-paper-secret-key
```

The unit is not installed and has no `[Install]` section. Until the lane's entry point exists it
runs only `python -m meridian.alpaca.credentials`: presence, no socket. M7 installs `/opt/meridian`.

## 7. Replay data on the Sextant disk

No code wrote the venue's answers to disk; every record is counts only (sextant-paper@a991b73:
src/sextant/alpaca/execution.py:L57-60; sextant#671, #693, #697). Each start wrote
`order-mode-receipt.json` and `b-lifecycle-journal.jsonl` (no venue row) to its own folder; this
note does not locate them (receipt name: sextant@33cdee7:docs/handbook/lessons.jsonl:L138). Logs
went to the unit's user journal (start 1 wrote no error line). Paths in `~/sextant-data`:

| Path | What | Basis |
|---|---|---|
| `handoffs/LEAD-STATE.md`; the notes `FAILED-START-1.md` and `LEAD-1618-stage1-run2-cause-and-fix.md` | the lead's state and run notes | sextant@33cdee7:scripts/compact_context.py:L41; notes by file name: sextant@33cdee7:docs/handbook/lessons.jsonl:L138-139 |
| `harvest-final/evidence/` | an older Paper B capture (9.3 MB, before 2026-11-07, format unknown): the only venue-derived history found | sextant@33cdee7:docs/research/2026-11-06-campaign-harvest.md:L164-167 |
| `calibration/universe.json` | the 100-name claim list | named in code |

Outside it: `~/.config/sextant/paper/paper-b-stage1.params`, the unit file and its journal. Smallest
useful subset: the starts' folders, the lead's state, the two notes, the params, the journal export
and the Paper B capture; receipts carry an account-scope hash, so `meridian-evidence` only. They
check a replay's counts (section 2); the replay is a reconcile-only start on the assigned account.

## 8. Left for the owner

- The paper keys into the two credential files (section 6); the section 7 subset, if wanted.
- The attended first order, on the account you assign, after the previous writer is confirmed
  stopped; its PR adds the lane entry point, the data client and the sourced commission rows.
