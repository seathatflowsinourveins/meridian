# Meridian handbook

How this harness works: its purpose, its rules, its layout, agents and dependencies, the
re-entry rules it will carry, its rate budgets, its run records, how a strategy is added and how
a goal is set. The lanes and their runbooks are in `docs/LANES.md`. `AGENTS.md` holds the
boundaries every agent follows and points here for the rest. At most 400 lines
(`size-budget.toml`). One repo, one WSL2 distro (`meridian`).

## Purpose

In the owner's words, as the approved plan of 2026-11-12 records them (its section 2):

- "All three order lanes (engine sandbox, IBKR paper, Alpaca paper). TradingView through
  every path." All venues "seamlessly", from "sota strategies templates upstream", and
  TradingView's "full landscape".
- "Dormant project trees cleared; one new project. [...] the new repo replaces the sextant line
  on this PC."
- "Memory and retrieval with local embeddings, at upstream quality. Every addition lands with
  an evidence ADR."

The plan reads this as one paper-trading harness on NautilusTrader whose first job was a
reconciled paper order (M1, reached on 2026-11-12), then the three lanes in the order IBKR,
sandbox, Alpaca, then the owner's mover strategy and its re-entry rules, then TradingView as a
display. Paper only throughout: no lane, agent or tool reaches a real-money account.

Milestones (plan 9.2); each ends in a committed, scrubbed run record:

| Milestone | What | State |
|---|---|---|
| M1 | one engine-placed IBKR paper order, reconciled | reached (`evidence/M1-*`) |
| M2 | the sandbox lane on IBKR data; the order budget with its soak; this handbook; the size budget | built; the sandbox's run on IBKR data is the owner's |
| M3 | Alpaca paper: data client and execution adapter, reconciliation against recorded history | adapter merged; entry point built; owner run pending |
| M4 | ranking, the mover strategy and its protection: sandbox, then paper | not started |
| M5 | re-entry and rotation in paper; thresholds calibrated by replay | not started |
| M6, M7 | TradingView display; unattended operation | not started |

## Rules

| Rule | Where it is held | How |
|---|---|---|
| Paper only: no route to a real-money account is created, enabled or tested | `meridian/boundary.py` for IBKR; the sandbox's wiring; Alpaca's hard-coded paper endpoint (M3) | refused at run time |
| | `tests/test_paper_only.py`: live endpoints, ports, trading modes, key names | CI tripwire |
| Only the engine places orders; no agent, script, skill or MCP server gets an order tool or broker connector; no agent starts a lane | `AGENTS.md` | rule |
| `risk/` and `*.contract.json` belong to the owner: read them, never create or edit them | `AGENTS.md`; `.gitignore` keeps every contract copy out of git | rule |
| No credential or key value is read, printed, copied or moved | `AGENTS.md`; gitleaks over the whole history in CI | rule; CI tripwire |
| Nothing derived from an account and no calibrated parameter in this public repository: account ids, raw order or fill history, reconciliation fixtures and tuned thresholds go to the private `meridian-evidence` (clone it as `~/src/meridian-evidence`); scrubbed run records may stay in `evidence/` | `tests/test_public_tree.py` (IBKR-style account-id shapes, allowlist copies); run records scrubbed before writing | CI tripwire |
| CI is fork-safe: no self-hosted runner, no `pull_request_target`, no secret a fork's pull request could reach | `tests/test_public_tree.py`, which checks the workflow files | CI tripwire |
| Everything installed, integrated or built on has an `UPSTREAM.md` row and code-area map, added in the same commit: version or commit, the URL that was read, the date, what it is for, "upstream" or "own design"; start from upstream's own example | `AGENTS.md`, `upstream-map.toml`, `tests/test_upstream_gate.py` | rule; CI |
| Files under `upstream/` are verbatim copies, never edited (its `NOTICE.md` is the one file written here); harvested own-design files say what changed | `tests/test_upstream_unmodified.py`, `tests/test_order_budget_harvest.py` | CI |
| `uv.lock` is committed; new releases wait 7 days; the engine is the one named exception and is pinned exactly | `pyproject.toml` (`exclude-newer`), Dependabot's cooldown | resolver |
| One evidence ADR per ecosystem addition, at most 60 lines | `docs/adr/README.md`, `tests/test_size_budget.py` | rule; CI |
| The size budget | `size-budget.toml`, `tests/test_size_budget.py` | CI tripwire |
| The owner sets goals; a goal never names a lane run, an order, the IB Gateway, port 4002 or a step only the owner takes | "Goals" below | rule |
| Work is reviewed by a different model family before it merges (`/codex:review` in Claude Code); findings are fixed in the pull request or closed with a reason; nothing auto-files issues | plan 9.5 | rule |
| MCP servers are off machine-wide for Claude Code and Codex; a skill, plugin or MCP server is added only by an ADR (`docs/adr/README.md`), and none gets an order tool or broker connector | `deploy/wsl/setup.sh agents-check` | check |
| Ask the owner before adding a paid service or an account; no licence is chosen for this repo's own code: that is the owner's decision | the owner | rule |
| One writer per account; plain DAY LIMIT entries, no brackets | plan 9.1 | rule; the M1 record fails an order that is not a DAY LIMIT |

The offline gate requires exactly one map entry per `meridian/` or `deploy/` file, citing an upstream
row, feature and local need; unused entries fail. Project and group dependency rows must match
locked versions. Add the register row and map entry with the change; CI checks both.

A tripwire catches a mistake, not a determined change: agents here run in bypass mode and can
edit the tests too. The owner's GitHub settings are the lock, where GitHub offers one.
`tests/test_paper_only.py` is such a tripwire; the paper boundary itself is `meridian/boundary.py`.

- Account ids stay out of the repo and out of `evidence/`. The allowlist holds SHA-256 hashes.
  A hash of a short id can be reversed by trying every id, so treat
  `risk/boundary.contract.json` as if it held the id itself; git ignores it.
- A branch from outside the owner's sessions (a fork's pull request) is read on GitHub, never
  opened in an Orca worktree or agent session: its setup and hooks would run as the owner unread.
- Check a finding at its source before acting on it. Find the root cause before disabling a
  check. Run the checks before saying something works. Report a failure as a failure. Add
  nothing the current milestone does not need.

## Re-entry and rotation (own design; thresholds uncalibrated)

The owner's own design, carried from Sextant's ADR-0006 (`seathatflowsinourveins/sextant` at
`33cdee7b`, `docs/adr/0006-reentry-and-rotation.md`), itself from the owner's earlier repos.
No upstream ships these rules. The strategy template holds R1, R2's band, R3a, R5 and the
confidence rule; the rest waits for M5. **Every threshold is
uncalibrated**: Sextant's replay registry gives each one as a named parameter with no value,
and its Paper B registry has one value, marked `UNCALIBRATED`. M5 calibrates them by replay;
tuned values go to `meridian-evidence`, never into this repository.

- **R1, flat first, then a cooldown.** Re-enter only after a broker-flat receipt (net zero, and
  every entry, protective and replacement order final; unknown or partial is not flat), and
  only `cooldown_seconds` after that receipt, not after the sell.
- **R2, retry, rotate or wait.** Retry the same symbol if its setup fires and its parent rank is
  within `retry_rank_band`; else rotate into the best unheld, independently qualified name
  within `rotation_rank_band`; else wait.
- **R3, reclaim.** Within `reclaim_lookback_s` since our sell the name traded at or below the
  sell trigger or the segment VWAP, then above it for `reclaim_trades_count` trades over
  `reclaim_trades_span_s`, with covered flow. Buy at most `reclaim_max_above_buffers` above the level after a held
  higher-low retest of `reclaim_hold_s`. Never the first print.
- **R3a, whipsaw.** After `whipsaw_stopouts_max` stop-outs in a row before the gain lock arms,
  the next entry on that symbol needs a capped reclaim or a qualifying OVERSELL; rising alone
  is not enough.
- **R3b, OVERSELL flush.** A flush below the sell price by `flush_min_depth` within
  `flush_window_s`, a selling climax (`climax_ratio` over `climax_window_s`), a held higher low
  (`oversell_hold_s`) and buy flow (`buy_flow_ratio` over `flow_window_s`), with a live
  catalyst if there is one and a rank within `retry_rank_band`; buy at most
  `oversell_max_above_buffers` above the higher low. Shadow only until the trade classifier's
  coverage is shown.
- **Confidence and size.** A same-symbol re-entry needs `reentry_min_confidence`; a missing
  confidence is refused before sizing, never taken as 1. Its size is scaled by
  `confidence_size_floor + (1 - confidence_size_floor) x confidence`.
- **R4, held rotation.** Swap a held name only if the pair's expected lift exceeds
  `2 x round-trip cost / price + rotation_lift_margin_bps / 10,000`, and the target scores at
  least `rotation_score_ratio` times the weakest holding.
- **R5, freshness.** A missing, stale or ambiguous ranking means wait: no stale fallback.
- **R6, modes.** Paper re-entry has no count cap. IBKR paper re-entry stays off. The capped,
  non-renewing mode is for a live lane and does not apply in this repository.

They serve the mover strategy (M4, own design): long-only US equities ranked live by price
move times dollar-volume ratio against each symbol's time-matched baseline, entered on the
first rising leg with a LIMIT at the ask, protected by a rising sell trigger. In Sextant's
replay, holding each entry to 15:55 ET beat all 96 active-exit variants (plan 9.1); that is a
replay, not a walk-forward validation.

## Rate budgets

| Venue | Its limit | The budget here | Held by |
|---|---|---|---|
| Alpaca (M3) | 200 requests per minute per account, every request counted; 429 past it | documented fixture: 180 paced requests in any 60 s window, burst 18; production uses owner rows below; CANCEL > REDUCE > MODIFY > QUERY > SUBMIT | `meridian/order_budget/` |
| IBKR | 50 messages per second from all clients of one Gateway together; error 100 past it, and a likely disconnect | none yet: a run of the M1 or the sandbox lane sends a few messages | n/a |
| Sandbox | none: the venue is simulated inside the engine | none needed | n/a |

The order budget is the owner's account pacer, harvested from Sextant (see `UPSTREAM.md`).
Every request takes a token; with the fixture rows, the bucket holds 18 and refills one token every
370,370,371 ns. A request past the budget waits in the pacer's queue, most urgent kind first;
its caller can withdraw it, and then it is dropped without being sent. An entry also waits
until the bucket holds more tokens than its protection reserve, so protective orders keep room;
only an entry whose reserve would reach the whole burst is refused (`PacerRefused` when it is
requested, `refuse(reason)` if it gets there while queued), and one whose reserve cannot be
worked out is dropped, so a caller checks reserve authority in its own admission. The soak
(`uv run python -m meridian.order_budget.soak`: offline, one simulated hour against a venue that
answers 429 past 200 a minute, with quiet spells in which the bucket fills up again) measured
at most 179 in any window, before and after each quiet spell, 161 to 163 a minute under steady
overload, no 429, no withdrawn entry sent, and every cancel and reduce sent. The budget holds
within one pacer: a new one starts with a full burst, so a lane that restarts within a minute
of its last request can add up to 18 to that window; Alpaca starts each new pacer empty, including after reconnect.

For Alpaca, copy `deploy/alpaca-order-budget.template.json` to the owner-held `order_budget_rows_path`; fill all fields of its 16 rows
with truthful sources and `REVIEWED` or unreviewed `PAPER_DEFAULT` scopes; optional null reserves may use `UNAVAILABLE`.
`meridian/alpaca/pacing.py` maps `PAPER_DEFAULT` for M2's unchanged validation and returns separate scope counts; missing/invalid or `FIXTURE_ONLY` rows refuse without values.
The venue limit must be 200 per 60 s; this repo supplies no production values. Fixture 429 backoff starts at 1 s and doubles to 30 s; production uses its rows.

The engine's own limits are only a backstop: its risk engine throttles submits and modifies
(100 a second each by default) and denies the excess, but a strategy's cancels and queries
pass unthrottled.

## Run records

Every run that passes writes one record to `evidence/`; a failed run writes to `runs/` only,
which git ignores and which may hold account ids.

- Name: `<milestone>-<lane>-<UTC stamp>-<mode>.json`, for example
  `M1-ibkr-paper-20261113T004629Z-order.json`.
- JSON with sorted keys, a two-space indent and one trailing newline.
- Every record has `schema` (`meridian.run-record/1`), `milestone`, `lane`, `mode`, `result`
  (`pass` or `fail`), `problems` (empty on a pass), `run_started_utc` and `run_ended_utc`.
- The rest is the lane's. IBKR paper: `boundary`, `gateway` (its `port` and how that port is
  bound, `bind`), `engine`, `startup_reconciliation`, `orders_refused` (a count, in every
  mode), `order`, `close_order` (fill mode only), `events`, `at_stop`, `engine_error`; the
  four M1 records of 2026-11-12 and 13 were written before `bind` and `orders_refused` and
  lack them. The order budget's soak: `budget`, `simulated_venue`, `demand`, `observed`,
  `component`, `offline`. The sandbox lane: `gateway`, `boundary`, `engine`, `node` (its
  clients), `strategy`, `trader_started`, `market_data`, `orders` (each with the execution
  client that took it), `events`, `at_stop`, `engine_error`.
- Scrubbed: normalised fields only. No account id, no hash of one, no broker or engine free
  text; those stay in `runs/`. `meridian/ibkr_paper.py` refuses to write a record that holds
  the account id or its hash.
- Checked by `tests/test_evidence_records.py` (every committed record: its name, this format,
  the common fields, a pass), `tests/test_run_record.py` and `tests/test_sandbox_lane.py` (the
  writers), `tests/test_order_budget_soak.py` and `tests/test_public_tree.py` (account-id
  shapes anywhere). The soak keeps one record, the latest: a fresh run must reproduce it field
  for field, and a passing run replaces it.

## How to add a strategy

Every strategy here is built on `meridian/strategy_template/` (M4, on upstream's
`EMACrossTrailingStop` example): one state machine per symbol (flat, entering, holding,
exiting) and at most one unresolved order per symbol. After an entry fills, the engine's
`OrderEmulator` holds a DAY `TRAILING_STOP_LIMIT` trailing by that symbol's ATR of quote-to-quote
mid changes times a multiple (with a floor); it only ratchets up. On the first quote whose bid
reaches it, it is released as a DAY LIMIT an exit buffer under the trigger; if the bid gapped
below that, the template cancels and re-prices at the bid less the buffer. Re-entry follows R1,
R2's band, R3a, R5 and the confidence rule (where: `strategy.py`'s docstring). Venue actions
are counted by kind for the lane's pacer; ratchets are local. Subclass `TrailingTemplate`,
implement `entry_signal` (and `rank`, `confidence`, `reclaim_qualified` for re-entry; missing
means wait), and supply every `TemplateParams` value from configuration: there are no defaults.
The package holds the template (`strategy.py`, `params.py`, `actions.py`) and its offline
simulation, `uv run python -m meridian.strategy_template.sim [--copies N]`. Not yet in a lane.
Add `--report` for the engine's statistics, order/fill/position CSVs and standalone HTML under
`runs/`; first `uv sync --locked`. Inputs remain synthetic and uncalibrated; undefined statistics are null.
[Pinned analysis evidence](adr/data/m5-engine-stats.md) explains the engine's cash-PnL semantics.

1. Start from an upstream template: the strategy template above, a NautilusTrader example or
   built-in strategy at the pinned version, or a cited published method. Name it in the strategy file's docstring (repository,
   path, version or commit). If no upstream fits, write "own design" and why.
2. Never edit an upstream file. Vendor it verbatim under `upstream/` with its licence and
   subclass it, as `meridian/ibkr_node.py` does with upstream's `IbV2OrderStrategy`.
3. Add its `UPSTREAM.md` row in the same commit.
4. Parameters: named, with no value in this repository; tuned values go to `meridian-evidence`.
5. Tests: it builds offline against the pinned engine, and it runs in the sandbox lane on the
   fake feed, as `tests/test_sandbox_lane.py` does with upstream's strategy. A strategy never
   adds an execution client.
6. Simulate first: `uv run python -m meridian.sim` replays it offline through the engine's own
   `BacktestNode`, catalog, fill, fee and latency models, session statuses, risk throttle and
   reports, one node per parameter set, results under `runs/` (manifest and Alpaca gaps:
   `docs/adr/data/m5-native-sim.md`). Then sandbox, then paper (plan 9.2). Every paper run is
   the owner's, attended, and ends in a run record.

## Goals

A goal makes an agent runtime keep taking turns on its own until a stated end state holds. The
owner sets goals. That is a rule, not a lock: an agent with a shell can start one (Claude Code,
below). Whether Claude Code's model may propose one rests first on a feature flag of
Anthropic's; the owner can only narrow it (`modelProposedGoals`, below), and nothing in this
repository changes either. A goal here:

- names one measurable end state, proved by a command whose exit code decides and whose output
  the session prints: no runtime below runs a check of its own, so the decision rests on what
  the session has shown;
- carries a turn bound, "or stop after N turns";
- never names a lane run, an order, the IB Gateway or port 4002, or a step only the owner takes
  (a trust dialog, a key, a merge, an attended run).

```text
/goal on this branch uv sync --locked and the check line at the end of AGENTS.md exit 0, their last lines printed; or stop after 20 turns
/goal uv run pytest -q tests/test_size_budget.py exits 0 and git diff --quiet <start> -- size-budget.toml tests/test_size_budget.py; echo "exit $?" prints exit 0, both outputs printed; or stop after 10 turns
```

`<start>` is the full hash of the commit the goal starts from. With no base, `git diff` compares
with the index only, so a raised limit passes once it is staged; a branch name moves with the
agent's commits. `git diff --quiet` prints nothing, hence the `echo`. The test file is guarded
too; a change elsewhere that alters its run, such as a `conftest.py` skipping it, is not caught.

| Runtime, version read | Set; stop | Who decides it is met; its own bound | Source, read 2026-11-13 |
|---|---|---|---|
| Claude Code 2.1.322 | `/goal <condition>`; `/goal clear`; also `claude -p "/goal ..."` | a small fast model after each turn, from the conversation only; no turn cap | https://code.claude.com/docs/en/goal and https://code.claude.com/docs/en/permissions, "Project allow rules and workspace trust" and "What runs before you trust a folder" (both unversioned); the settings schema and the ProposeGoal tool in `~/.local/share/claude/versions/2.1.322` |
| Codex CLI 0.167.2 | `/goal <objective>`; `/goal pause`, `resume`, `clear` | the working model (`update_goal`); an optional token budget | https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex (unversioned); `codex-rs/ext/goal/src/spec.rs` and `codex-rs/features/src/lib.rs` at tag `rust-v0.167.2` |
| DeepSeek Harness 0.2.2-rc.1 | `/goal` to create, edit, pause, resume or clear | the working model, no independent evaluator; 256 rounds by default (`defaultMaxGoalRounds`) | `deepseek-ai/deepseek-harness` at `66491b0` (tag `dsh-v0.2.2-rc.1`), `packages/bundle/base/cordis.patch.yml` lines 327-334; the `dsh-goal`, `dsh-command-goal` and `dsh-tool-goal` READMEs in the installed package |
| Antigravity CLI 1.5.7 | `/goal <objective>`; ask it to stop, or start another `/goal` | the working model, told at each stop to audit its own work; no iteration cap | https://antigravity.google/docs/commands/goal.md and https://antigravity.google/docs/cli/reference.md (unversioned) |

Claude Code runs a goal as a session-scoped Stop hook and offers `/goal` under the trust rule
for hooks in settings files. An interactive session needs the repository trusted: Claude Code
keys trust on the repository root, in a worktree on the main checkout's root, so trusting
`~/src/meridian` covers the clone and every worktree, and a trusted folder above a checkout
(`~/src`, `~/src/meridian-worktrees`) does not count. Accepting that dialog is the owner's step.
`claude -p` and SDK runs never show the dialog and run `/goal` in any folder, so trust does not
stop an agent from starting a goal. `/goal` is off while `disableAllHooks` is true or managed
settings set `allowManagedHooksOnly`. Its model gets a ProposeGoal tool only when the feature
flag `tengu_propose_goal` is on, and never in a non-interactive run; that flag is off by default
in 2.1.322 and was not among the flags cached in the distro's `~/.claude.json` on 2026-11-13.
`modelProposedGoals` can narrow the tool but not turn it on: `auto` (the default; the model
chooses whether to ask first), `alwaysAsk` or `disabled`. A typed `/goal` is unaffected. Claude
Code takes that key's value from user, managed and command-line settings only, and a project's
files cannot loosen it; the key is marked internal in the 2.1.322 settings schema and is not on
the docs pages read.

Codex's `create_goal` tool tells its model to start a goal only when the user or the
instructions ask; DeepSeek Harness refuses a model-created goal without a direct human request
in that turn. `codex features list` shows `goals` stable and on.

## Layout, agents and dependencies

| Path | What it is |
|---|---|
| `deploy/wsl/` | the distro definition (cloud-init) and the user-level setup script |
| `meridian/boundary.py`, `meridian/ib_probe.py` | the paper checks (Gateway login mode, ports, account form, optional allowlist) and the probe that asks the Gateway which accounts it manages (own design) |
| `meridian/ibkr_paper.py`, `meridian/ibkr_node.py` | IBKR paper lane: gate, owner confirmation, run record; the engine side, built on upstream's example |
| `meridian/order_budget/`, `meridian/sandbox_*.py` | M2: the order budget (the owner's pacer, from Sextant) and the sandbox lane (no broker) |
| `meridian/alpaca/` | Alpaca paper execution adapter (M3 groundwork, own design); study in `docs/adr/data/m3-alpaca.md` |
| `deploy/systemd/` | the Alpaca lane's unit for `paper`, prepared and not enabled; keys only as systemd credentials |
| `upstream/` | upstream example files, unmodified |
| `.agents/skills/` | skills every agent reads; each has a link in `.claude/skills/` for Claude Code |
| `orca.yaml`, `.worktreeinclude` | Orca: the setup script and tabs of each new worktree; nothing ignored is copied |
| `risk/boundary.contract.json` | optional: the owner's allowlist of paper accounts |
| `evidence/` | scrubbed run records: one per attended run that passed, and the latest offline soak |
| `runs/` | local run output, ignored by git; may hold account ids |

- Four agent runtimes run here through Orca, one git worktree per task: Claude Code leads
  (`claude-fable-5-2`; its workers run `claude-opus-5-5`), Codex (`gpt-6-astra`, `gpt-6.1-sol`
  for bulk) and Antigravity work and review, DeepSeek Harness works (code and research).
- The agent runtimes start from checksummed pins in `deploy/wsl/setup.sh` and update themselves
  in sessions the owner starts (Orca's launches do not); `setup.sh agents-check` verifies them.
- NautilusTrader 2.0 is a release-candidate line with breaking changes between candidates.
  Read its release notes before moving the pin, and never answer an API question from memory:
  read the installed package or the tagged source.

## Size budget, ADRs and this file

- `size-budget.toml` sets the limits and `tests/test_size_budget.py` checks them: `AGENTS.md`
  at most 30 lines and `CLAUDE.md` 1, this handbook 400, `docs/LANES.md` 180, each ADR 60, and
  totals for agent instructions, prose, config, workflows and skills; every tracked file must be
  of a kind the file names. It is a tripwire: see the file's header for why GitHub cannot lock
  it while every push comes from the owner's account. The open-issue count is not checked:
  without a token CI can read only issues and pull requests together.
- ADRs: `docs/adr/README.md` lists last checks and revisit dates; read the Decision first.
  Recheck sources; append a dated kept/replaced/re-measured line in `docs/adr/data/NNNN-revisits.md`,
  then update the index; the weekly watch reports in the GitHub issue labelled `landscape`.
  Runtime pins: the Orca automation "Meridian upkeep" turns that report into a pull request (`setup.sh drift`).
