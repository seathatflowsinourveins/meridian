# M3: the Alpaca paper lane

Study written 2026-11-12 for M3 (plan 9.2); current behavior checked against `7bec9f4`, 2026-11-13.
Historical sources: public `seathatflowsinourveins/sextant` at `33cdee7` and `sextant-paper` at `a991b73`, read with `gh api`, cited as `repo@commit:path:lines` or `repo#N`.
A second reader re-checked each study claim at its source, not the note as it stands. Nothing here talked to Alpaca.
Owner setup, commands, pass criteria and records: [lanes](../../LANES.md#alpaca-paper-lane-m3-owner-only).

## 1. The earlier adapter

Owner's design on NautilusTrader 2.0.0rc8 (`d53849b`), alpaca-py 0.44.0 (`cc4cb3b7`), Python 3.13 (sextant-paper@a991b73:pyproject.toml:L5-9, UPSTREAMS.md:L9-10).

| Module (sextant-paper@a991b73:src/sextant/) | Lines | What it does |
|---|---|---|
| `alpaca/execution.py` | 1,406 | the execution client: paced submit, modify (PATCH), cancel, query; the `trade_updates` stream; startup reports. sextant's copy (1,213 lines) is older: imported by sextant-paper#3, then fixed in #10 to #31 |
| `alpaca/wire.py` | 225 | decimal-text payloads, the house order-id namespace, `AccountGateway`: every execution REST call, reads included, through one pacer, SDK retries off |
| `alpaca/reports.py` | 337 | Alpaca rows as order, position and fill reports at instrument precision |
| `execution/pacer.py`, `risk/controls.py` | 249, 124 | the account order budget (section 5) and its 16 registry rows |
| `alpaca/{config,factories,constants,parsing,providers}.py` | 15-109 | configs holding key *names*; MARGIN and NETTING factories; assets as `Equity`; a provider whose asset calls skip the pacer |
| `alpaca/{data,stream_facts,trade_updates}.py` | 908, 110, 111 | market data and ranking facts (`trade_updates.py` is market-data corrections, not the order stream) |
| `alpaca/commission.py`, `data/alpaca_history.py` | 83, 280 | sourced paper fee rows; a historical data downloader |

Paper B's old writer (`paper/b_protector_main.py`) used typed SDK calls through its own paced client: another writer to the node. Paper was hard-coded (`paper=True`, no switch); environment-variable key names were injected per process from systemd-creds files (sextant@33cdee7:docs/adr/0028-local-keys.md:L15-25).

## 2. Three failed attended starts (2026-11-11)

Paper B's "stage 1" starts (sextant#470, rows 10-11) died in startup reconciliation before the flat-account gate; the engine kept only "Failed to get mass status from ALPACA" (sextant#671, #688).

| Start (New York) | What failed | Fix | Proven |
|---|---|---|---|
| 1, about 15:10 | No cause recorded. From start 2: ended orders in symbols outside the node's loaded 100-name claim list made a report fail ("report instrument is unavailable"), and one such row failed the whole read (sextant@33cdee7:docs/handbook/lessons.jsonl:L138) | sextant#671 (`d537f3ea`): a per-stage trace. sextant#693 (`1dfb44ce`): skip and count ended rows in unloaded symbols; working ones refuse | #671 by start 2 |
| 2, about 16:17 | The same, now visible: 437 order rows, 261 in unloaded symbols, 1,300 fill rows, 0 positions (lessons.jsonl:L138-139) | sextant#693 | start 3 passed it |
| 3, 16:30 to 17:28 (likely after 17:19) | 435 ended unloaded rows were skipped; then the fill stage refused 8,422 of 8,822 fills: the venue's FILL history reaches further back than its order listing (sextant#697). The refusal of unexplained fills predates sextant#636, which made startup read every FILL page | sextant#697 (`f433e67a`): count fills older than the oldest listed order | never |

No fourth start is recorded at either pin; all three ran sextant code, so none of sextant-paper's later fixes (#10 to #31) met a real start. The rehearsal passed because its fake history lacked these shapes (lessons.jsonl:L138); start 3's cause was probably latent in starts 1 and 2 (inferred). The previous writer played no part: sextant#663 fixed a gate refusal on its cancelled order, but no start reached the gate. Receipts carry no commit; starts 2 and 3 show counts from unmerged changes (inferred: unmerged trees). The rc9 claim issue found while porting is covered in section 4.

## 3. Current adapter: carried, changed and omitted

Offline coverage: `tests/test_alpaca_{wire,trade_updates,reconcile,node,paper,data}.py`; failure-specific proofs are in section 4.

- `wire.py`: every REST call, including reads and asset loads, uses one [account budget](../../HANDBOOK.md#rate-budgets); sells are REDUCE. SDK retries are off; 429 pauses the pacer. Payloads use decimal text.
- Commands run as tasks outside the engine's command queue; an order outside the universe is denied unsent. The on-wire mark separates once-only unsent refusal from sent settlement: documented POST 403/422 or DELETE 422/429 refusal, stream or later read; other uncertain outcomes are gaps.
- DELETE 204 is only an attempt. One unresolved cancel per order; its slot is taken before the budget. An unsent cancel refusal names its command so the engine restores the order.
- Startup reports wait for subscription acknowledgement. A lost stream, SDK decode/routing failure, event outside the 20 classifications (`restated`, anything new), or unreadable/unmappable answer (non-JSON body, listing, pages, row, symbol) is a gap; a failed read request is not.
- Gaps deny new orders until a full read issued afterwards matches the engine cache: each reported order's status and filled quantity and each net position, including flat. Equal reads need no mutation; empty reads require a flat cache. Nonconvergence at the request timeout is a new gap; open-order checks can stop admission but cannot reopen it.
- Executions pass once, never if the engine already holds them (including fills inferred from a read/check); out-of-sequence executions are gaps. Reads below known fills are reread. No report is volunteered ahead of stream fills; such a stream report is a gap.
- `reconcile.py` reads the whole order history and refuses gaps; missing, malformed or engine-mismatched symbols refuse. Section 4 covers withheld unloaded history, pre-history fills and fixed, value-free stage traces. Ended unmappable history (`replaced`, brackets) is counted without fills and refuses with them.
- Engine settings on rc9: no missing-order generation, unbounded lookback, unresolved submissions retained; open-order checks replace in-flight checks (the old node had neither), with no individual wait setting over a minute.
- `data.py`: session-selected JSON decimal-text quotes (`alpaca_sessions.session_at` shares New York windows; admission also requires calendar rows), pinned host before sign-in, no REST; lost/unreadable/unmapped streams latch failure. Unusable `quote_age_ns` is None; execution loads instruments. [Quote-size restrictions and the lane's age limit](../../LANES.md#alpaca-paper-lane-m3-owner-only).
- Connect refuses without sourced per-fill commission. `AlpacaPaperExecClientConfig.for_paper_equities()` uses `meridian/alpaca/commission.py`: zero USD for paper US-equity fills only, no real-trading cost model. Its two dated citations and exact quotes show that paper excludes regulatory fees but does not mention commissions; the commission page supplies that statement.
- Unlike the earlier line, alpaca-py 0.45.0's asynchronous trade stream runs on the node loop and is pinned to the paper host before sign-in (websockets would follow redirects); every REST call has a timeout (open in sextant#463).
- Order paging asks one microsecond past the edge, preserving edge rows for inclusive or exclusive `until` (the old pager refused exclusive). FILL paging stops past the oldest listed order. Another writer's activity stops new orders; its startup rule is in the handbook.

Omitted: modify/successor lineage, trailing stops and exit guard (protection, M4); owner custody/claim lists (one writer per account); fee registry; bars, trades, historical data; wire counters; handover leases; live-lane and IBKR parts.

## 4. Failure proofs

| Failure | Answer | Test (`tests/test_alpaca_node.py`: the real engine, a synthetic venue) |
|---|---|---|
| no cause recorded | per-stage trace: requests, rows, failure class, HTTP status, fixed reason | `test_a_failed_start_records_*` |
| ended orders in unloaded symbols | withheld and counted; a working one, at any leg depth, refuses | `test_failure_case_2_*` |
| fills older than the order history | counted; a newer unexplained fill still refuses | `test_failure_case_3_*` |
| start 3's whole shape | 437 orders and 8,822 fills: passes, reading 5 FILL pages, not 89 | `test_the_third_starts_shape_*` |
| an old writer's orders | ended ones are history; [working-order rule](../../LANES.md#alpaca-paper-lane-m3-owner-only) | `test_failure_case_1_*` |
| a fresh rc9 node treats every earlier order as external and drops it unless claimed | the strategy claims its universe (`external_order_instrument_ids`) | `test_without_the_claim_*` |

## 5. Order-budget interface

`meridian/alpaca/budget.py` uses M2's harvested pacer (`meridian/order_budget/`, #3): imported `ActionKind`/`PacerRefused` let the gateway catch M2 refusals; its `Protocol` is checked against `AccountPacer` by pyright in `tests/test_alpaca_budget.py`.
[Rate budgets](../../HANDBOOK.md#rate-budgets) holds production loading and pacing; fake tests cover both. A cancel reaching DELETE costs two requests (read, DELETE); readers cap pages at `request_budget`, each order page at 500 rows (180 pages gives at most 90,000 rows, including overlaps, not 90,000 distinct orders).

## 6. Keys

See [owner credential setup and the unit](../../LANES.md#alpaca-credentials).

## 7. Replay data on the Sextant disk

No code wrote venue answers to disk; records contain counts only (sextant-paper@a991b73:src/sextant/alpaca/execution.py:L57-60; sextant#671, #693, #697). Each start's folder held `order-mode-receipt.json` and `b-lifecycle-journal.jsonl` (no venue row); this note does not locate them (sextant@33cdee7:docs/handbook/lessons.jsonl:L138).
Logs went to the unit's user journal (start 1 wrote no error line). Paths in `~/sextant-data`:

| Path | What | Basis |
|---|---|---|
| `handoffs/LEAD-STATE.md`; the notes `FAILED-START-1.md` and `LEAD-1618-stage1-run2-cause-and-fix.md` | the lead's state and run notes | sextant@33cdee7:scripts/compact_context.py:L41; notes by file name: sextant@33cdee7:docs/handbook/lessons.jsonl:L138-139 |
| `harvest-final/evidence/` | an older Paper B capture (9.3 MB, before 2026-11-07, format unknown): the only venue-derived history found | sextant@33cdee7:docs/research/2026-11-06-campaign-harvest.md:L164-167 |
| `calibration/universe.json` | the 100-name claim list | named in code |

Outside it: `~/.config/sextant/paper/paper-b-stage1.params`, the unit file and journal. Smallest useful subset: the starts' folders, lead state, two notes, params, journal export and Paper B capture.
Receipts carry an account-scope hash: `meridian-evidence` only. They check replay counts (section 2); the replay is a reconcile-only start on the assigned account.

## 8. Left for the owner

Owner steps: [keys, local rows, quote-age limit, attended restart and first order after confirming the previous writer stopped](../../LANES.md#alpaca-paper-lane-m3-owner-only); the section 7 subset, if wanted; the handbook command has not been run by an agent.
