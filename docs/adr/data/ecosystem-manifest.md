# Ecosystem manifest

The architecture approved by the owner on 2026-11-13, checked at its source on origin/main
(and, for a row in build, on the branch it names) on 2026-11-14. The eight approved layers,
with simulation added as Layer 3.5 under trading; one maintained, leading upstream per job. A
row's state is one of
**in use** (with the pull request or commit that brought it), **in build** (with its branch or
open pull request), **measured, not adopted** (with its ADR), **planned** (with its milestone)
or **watch**. "Rests on" names the upstream repository; "Pin" the exact version or commit, from
`UPSTREAM.md`, `pyproject.toml`, `uv.lock` or the pins in `deploy/wsl/setup.sh`; "Where" the
file or ADR here; "Checked" the date the row was checked at its source. A row whose state cannot
be established says so. A row that predates pull requests names the commit that brought it.
Research tools install into a `research` dependency group and test tools into `dev`; neither is
in the order path.

2026-11-13: the owner decided that a stack of additions to one runtime can be admitted by
selection (maintained, leading, one upstream per job) in one ADR, without a with-and-without
run per item (`docs/adr/README.md`).

2026-11-14: every row checked at its source on main, and the since-landed work added: the simulation layer under trading (Layer 3.5), the DeepSeek Harness stack and the Claude Code and Codex workflow layers in build, the second reviewer, the lead skill and its merge gate, the upstream gate, the weekly watch, the pinned secret scan, the plotting library and the screener's holder; the admitted stars moved to their layers.

### Layer 1, base system
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Distro, services | WSL 3.0.3.0, Ubuntu 26.04.1, systemd 259 | `3.0.3.0`, `26.04.1`, `259` | in use (commit 62746f1) | deploy/wsl/meridian.user-data; UPSTREAM.md | 2026-11-14 |
| Python toolchain | `astral-sh/uv` | `0.13.7` | in use (PR #1) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| GitHub | `cli/cli` | `2.104.0` | in use (PR #1) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| Backups of run records | `restic/restic` | not pinned | planned (after M7, when the unattended runs produce state) | none | 2026-11-14 |

### Layer 2, toolchain and CI
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Lint and format | `astral-sh/ruff` | `0.17.3` | in use (commit 95df775) | pyproject.toml; uv.lock; UPSTREAM.md | 2026-11-14 |
| Types | `microsoft/pyright` | `1.1.414` | in use (commit 95df775) | pyproject.toml; uv.lock; UPSTREAM.md | 2026-11-14 |
| Tests | `pytest-dev/pytest` | `9.2.0` | in use (commit 95df775) | pyproject.toml; uv.lock; UPSTREAM.md | 2026-11-14 |
| Property tests of trailing and re-entry invariants | `HypothesisWorks/hypothesis` | `6.170.15` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_dev_dependencies.py | 2026-11-14 |
| Tests at session edges and half days | `adamchainz/time-machine` | `3.6.0` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_dev_dependencies.py | 2026-11-14 |
| Secret scan, pinned install | `gitleaks/gitleaks` | `8.30.1`, `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` | in use (PR #39; CI from commit 850abc5) | .github/workflows/ci.yml; deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| CI | `actions/checkout`, `astral-sh/setup-uv`, `dependabot/dependabot-core` | `v7.0.1`, `3d3c42e5aac5ba805825da76410c181273ba90b1`, `v10.3.3`, `68559e99cc807c1eb7e9238fd43a15bba460eec2` | in use (commit 850abc5) | .github/workflows/ci.yml; .github/workflows/landscape.yml; .github/dependabot.yml; UPSTREAM.md | 2026-11-14 |
| Settings and logs of the unattended service | `pydantic/pydantic` with `pydantic/pydantic-settings`, `hynek/structlog` | not pinned | planned (M7) | none | 2026-11-14 |
| Engineering standards | `nautechsystems/nautilus_engineering` | not pinned | watch | none | 2026-11-14 |
| Upstream gate: every code area and dependency names its upstream | own design on `pytest-dev/pytest` | `9.2.0` | in use (PR #37) | upstream-map.toml; UPSTREAM.md; tests/test_upstream_gate.py; tests/test_ecosystem_manifest.py | 2026-11-14 |

### Layer 3, trading
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Engine: orders, emulated trailing stops, fast exit, brackets, risk, backtest, sandbox, indicators, statistics, tearsheets | `nautechsystems/nautilus_trader` | `2.0.0rc9`, `da6b57aefdd62b44f675e434ffcfefca7f4025dd` | in use (commit 95df775) | pyproject.toml; uv.lock; UPSTREAM.md | 2026-11-14 |
| Alpaca: orders, trade stream, quotes around the clock, screener, clock and calendar | `alpacahq/alpaca-py` | `0.45.0` | in use (PR #5) | pyproject.toml; uv.lock; UPSTREAM.md | 2026-11-14 |
| IBKR | the engine's own Interactive Brokers adapter (`nautechsystems/nautilus_trader`), IB Gateway | `2.0.0rc9`, `10.50.1g` | in use (commit 850abc5; fill mode PR #2) | UPSTREAM.md; deploy/wsl/setup.sh; meridian/ibkr_node.py | 2026-11-14 |
| Feature and replay computation | `pola-rs/polars` | `2.1.0` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Reference data, calendars, fundamentals | `openbq-org/OpenBB` | `2.0.1` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Filings and point-in-time fundamentals | `dgunning/edgartools` | `5.62.1` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Symbol universe with sector tags | `JerBouma/FinanceDatabase` | `2.5.1` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Movers and ranking universe: holds the job | `alpacahq/alpaca-py` (`ScreenerClient`) | `0.45.0` | in build (branch seathatflowsinourveins/m4-movers) | branch seathatflowsinourveins/m4-movers:meridian/alpaca/screener.py; branch seathatflowsinourveins/m4-movers:docs/adr/data/m4-universe.md | 2026-11-14 |
| Advisory mover input: not adopted | `deepentropy/tvscreener` | not pinned | watch | none | 2026-11-14 |
| Parameter sweeps before the engine's backtest confirms | `polakowo/vectorbt` | `1.2.0` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Purged and combinatorial cross-validation; basket sizing | `skfolio/skfolio` | `1.12.7` | in use (PR #34; M5 evaluation pending) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Deflated Sharpe, overfitting probability; method | `stefan-jansen/machine-learning-for-trading` and its `ml4t-diagnostic` package | `0.2.0` | in use (PR #34; M5 evaluation pending) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Exchange sessions and holidays in replay | `gerrymanoim/exchange_calendars` (live sessions use Alpaca's own clock) | `4.13.2` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Replay data checks | `unionai-oss/pandera` | `0.35.0` | in use (PR #34) | pyproject.toml; uv.lock; UPSTREAM.md; tests/test_research_dependencies.py | 2026-11-14 |
| Ranking models | `microsoft/qlib` | not pinned | planned (M4) | none | 2026-11-14 |
| Forecast features | `google-research/timesfm` | not pinned | planned (M5) | none | 2026-11-14 |
| LLM research signal, offline and advisory | `TauricResearch/TradingAgents` | not pinned | planned (M5; never in the order path) | none | 2026-11-14 |
| Agent-to-engine interface | `nautechsystems/nautilus_agents` | not pinned | watch (no host side at rc9) | none | 2026-11-14 |

### Layer 3.5, simulation
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Offline one-order practice on the engine's native simulated exchange | `nautechsystems/nautilus_trader` | `2.0.0rc9` | in use (PR #22) | meridian/alpaca_sim.py; tests/test_alpaca_sim.py; UPSTREAM.md | 2026-11-14 |
| Strategy-template simulation on the engine's native `BacktestEngine` | `nautechsystems/nautilus_trader` | `2.0.0rc9` | in use (PR #31) | meridian/strategy_template/sim.py; tests/test_strategy_template.py; UPSTREAM.md | 2026-11-14 |
| Engine statistics and tearsheet export | `nautechsystems/nautilus_trader` | `2.0.0rc9` | in use (PR #52) | meridian/strategy_template/report.py; docs/adr/data/m5-engine-stats.md; UPSTREAM.md | 2026-11-14 |
| Native simulation end to end | `nautechsystems/nautilus_trader` | `2.0.0rc9` | in build (branch seathatflowsinourveins/m5-native-sim) | pyproject.toml; docs/adr/data/m5-native-sim.md (in build) | 2026-11-14 |

### Layer 4, display
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Owner-built page: candles, trail lines, fill markers | `tradingview/lightweight-charts` | not pinned | planned (M6) | none | 2026-11-14 |
| Results views: the engine's own tearsheet | `plotly/plotly.py` | `7.1.0` | in use (PR #52; research group) | pyproject.toml; uv.lock; docs/adr/data/m5-engine-stats.md; UPSTREAM.md | 2026-11-14 |
| Live order and fill blotter | `perspective-dev/perspective` | not pinned | planned (M6, if a static page is not enough) | none | 2026-11-14 |
| TradingView Desktop, attended | `tradesdontlie/tradingview-mcp` (inside the kit) | not pinned | not established on main (the 22:02 plan records in use on the Windows side; no file here records it) | none | 2026-11-14 |
| Building and testing the page | `bigskysoftware/htmx`, `microsoft/playwright` | not pinned | planned (M6) | none | 2026-11-14 |

### Layer 5, runtimes
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Lead, and Opus workers | `anthropics/claude-code` | `2.1.325` | in use (PR #1; pin moved in PR #35) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| Workers and review | `openai/codex` | `0.167.2` | in use (PR #1) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| Worker: full worker since 2026-11-13, mechanical tasks only before | `deepseek-ai/deepseek-harness` with `ccch1mneyyy/dsh-TUI` | `0.2.2-rc.1`, `0.20.0` | in use (PR #1; role in PR #38) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |

### Layer 6, orchestration and review
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Fleet, one worktree per task | `stablyai/orca` | `1.4.258` | in use (PR #45) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| Cross-family review | `openai/codex-plugin-cc` and `codex review` | `1.0.6`, `db52e28f4d9ded852ab3942cea316258ae4ef346` | in use (PR #1; quiet since July, watched) | deploy/wsl/setup.sh; UPSTREAM.md | 2026-11-14 |
| A second reviewer with a published benchmark | `alibaba/open-code-review` | `1.13.9` | in use (PR #47; ADR 0020; delegation mode only) | deploy/wsl/setup.sh; UPSTREAM.md; docs/adr/0020-open-code-review.md | 2026-11-14 |
| The lead's procedure and merge gate | git 2.53.0, `cli/cli` | `2.53.0`, `2.104.0` | in use (PR #39) | .agents/skills/lead/SKILL.md; UPSTREAM.md; tests/test_lead_gate.py | 2026-11-14 |
| Weekly landscape watch and upkeep | GitHub REST 2026-03-10, `stablyai/orca` automations | `2026-03-10`, `1.4.258` | in use (PR #32; automation PR #41) | .github/workflows/landscape.yml; deploy/landscape_watch.py; UPSTREAM.md | 2026-11-14 |
| Named fallbacks, not installed | `max-sixty/worktrunk` (if Orca is dropped), `coleam00/Archon` (if command-ended gates are needed) | not pinned | watch | none | 2026-11-14 |

### Layer 7, skills and context
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Skill format | `agentskills/agentskills`, `stablyai/orca`'s two skills | `1.4.257` | in use (PR #1; layout PR #39) | .agents/skills/NOTICE.md; tests/test_skills_layout.py; UPSTREAM.md | 2026-11-14 |
| The few-line instruction file | `anthropics/claude-plugins-official`, `mattpocock/skills`, `walkinglabs/learn-harness-engineering`, `Piebald-AI/claude-code-system-prompts` | not pinned | in use (PR #39) | AGENTS.md; docs/LANES.md; UPSTREAM.md | 2026-11-14 |
| Side-agent omission notes | the built-in "You should know" in Claude Code 2.1.322 and later | `2.1.322` | in use (PR #17; ADR 0014) | docs/adr/0014-claude-you-should-know.md; UPSTREAM.md | 2026-11-14 |
| Shell-output compression | `rtk-ai/rtk` | `1.2.0` | measured, not adopted (ADR 0017, on branch seathatflowsinourveins/adr-0015-rtk) | branch seathatflowsinourveins/adr-0015-rtk:docs/adr/0017-rtk-shell-output.md | 2026-11-14 |
| Status line: context, plan limits, activity, and token and cost accounting | `jarrodwatts/claude-hud` (holds it; ccusage is not installed: one upstream per job) | `0.15.0`, `b86e1c3e5255880578de4b7cc87dc383228c2a18` | in use (PR #40; ADR 0015) | deploy/wsl/setup.sh; UPSTREAM.md; docs/adr/0015-claude-hud.md | 2026-11-14 |
| Token and cost accounting for DeepSeek Harness | `kenn-io/agentsview` (reads dsh's sessions) | `0.47.0` | in build (PR #44; ADR 0016) | branch seathatflowsinourveins/dsh-stack:docs/adr/data/0016-stack.md | 2026-11-14 |
| Write-less-code skill | `DietrichGebert/ponytail` (holds it on Codex); `Yeachan-Heo/oh-my-claudecode`'s ai-slop-cleaner (holding it on Claude Code) | `5.3.3` | in build (PR #53; branch seathatflowsinourveins/codex-stack; branch seathatflowsinourveins/claude-omc-stack; ADR 0018, ADR 0019) | branch seathatflowsinourveins/codex-stack:UPSTREAM.md; branch seathatflowsinourveins/claude-omc-stack:docs/adr/data/0019-stack.md | 2026-11-14 |
| Workflow layer for Claude Code | `Yeachan-Heo/oh-my-claudecode` | `5.8.4` | in build (branch seathatflowsinourveins/claude-omc-stack; ADR 0019) | branch seathatflowsinourveins/claude-omc-stack:UPSTREAM.md; branch seathatflowsinourveins/claude-omc-stack:docs/adr/data/0019-stack.md | 2026-11-14 |
| Workflow layer for Codex | `Yeachan-Heo/oh-my-codex` | `0.22.6` | in build (PR #53; branch seathatflowsinourveins/codex-stack; ADR 0018) | branch seathatflowsinourveins/codex-stack:UPSTREAM.md; branch seathatflowsinourveins/codex-stack:docs/adr/data/0018-stack.md | 2026-11-14 |
| DeepSeek Harness skills: spec, self-review, source reading, test first, root cause, proof before done, research, the pull request body | `addyosmani/agent-skills`, `obra/superpowers`, `mattpocock/skills` (single folders at a pin) | `0.6.15`, `8bfcc1f9916f2eea55494d8c1fa7f4bde867dd9e`, `7.0.2`, `22f0b463e7a5e579904dd6211a520321035526f7`, `1.3.2`, `d1478fcb140db0b93c0c8df17bcfd311844749d0` | in build (PR #44; ADR 0016) | branch seathatflowsinourveins/dsh-stack:docs/adr/data/0016-stack.md | 2026-11-14 |
| Structural search for DeepSeek Harness | `ast-grep/ast-grep` | `0.51.2` | in build (PR #44; ADR 0016) | branch seathatflowsinourveins/dsh-stack:docs/adr/data/0016-stack.md | 2026-11-14 |
| Code navigation for DeepSeek Harness | the `lsp` tool of `deepseek-ai/deepseek-harness` on the worktree's pyright | `0.2.2-rc.1` | in build (PR #44; ADR 0016) | branch seathatflowsinourveins/dsh-stack:docs/adr/data/0016-stack.md | 2026-11-14 |
| Completion gate for DeepSeek Harness | own design: `deploy/wsl/dsh-check-gate.sh` | not pinned | in build (PR #44; ADR 0016) | branch seathatflowsinourveins/dsh-stack:deploy/wsl/dsh-check-gate.sh | 2026-11-14 |
| Code navigation for Codex | `oraios/serena` (the official dsh lsp holds dsh's job) | `2.1.0` | in build (PR #53; branch seathatflowsinourveins/codex-stack; ADR 0018) | branch seathatflowsinourveins/codex-stack:UPSTREAM.md; branch seathatflowsinourveins/codex-stack:docs/adr/data/0018-stack.md | 2026-11-14 |

### Layer 8, memory and retrieval
| Job | Rests on | Pin | State | Where | Checked |
|---|---|---|---|---|---|
| Memory and code search | files in git, ripgrep, `microsoft/pyright` | `1.1.414` | in use (ADR 0001; they beat the measured alternative) | docs/adr/0001-semble-code-search.md; UPSTREAM.md | 2026-11-14 |
| Shared task state | `gastownhall/beads` | not pinned | watch (measure only when workers collide over task state) | none | 2026-11-14 |
| A corpus of broker documents | `microsoft/markitdown`, `VectifyAI/PageIndex` | not pinned | planned (when there is a corpus; no milestone) | none | 2026-11-14 |

## Placement of the starred repositories

The owner's starred list was read on 2026-11-13 with `gh api user/starred --paginate --jq '.[].full_name'`.

- Starred repositories returned by the command: 393
- Rows with `starred` = yes: 393
- Rows with `starred` = no: 19

| repository | group | in architecture | starred |
|---|---|---|---|
| `anthropics/claude-plugins-official` | instruction file sources | yes | yes |
| `mattpocock/skills` | instruction file sources | yes | yes |
| `walkinglabs/learn-harness-engineering` | instruction file sources | yes | yes |
| `Piebald-AI/claude-code-system-prompts` | instruction file sources | yes | yes |
| `astral-sh/uv` | Layer 1, base system | yes | no |
| `cli/cli` | Layer 1, base system | yes | yes |
| `restic/restic` | Layer 1, base system | yes | yes |
| `astral-sh/ruff` | Layer 2, toolchain and CI | yes | no |
| `microsoft/pyright` | Layer 2, toolchain and CI | yes | yes |
| `pytest-dev/pytest` | Layer 2, toolchain and CI | yes | yes |
| `HypothesisWorks/hypothesis` | Layer 2, toolchain and CI | yes | no |
| `adamchainz/time-machine` | Layer 2, toolchain and CI | yes | no |
| `gitleaks/gitleaks` | Layer 2, toolchain and CI | yes | yes |
| `actions/checkout` | Layer 2, toolchain and CI | yes | yes |
| `astral-sh/setup-uv` | Layer 2, toolchain and CI | yes | no |
| `dependabot/dependabot-core` | Layer 2, toolchain and CI | yes | yes |
| `pydantic/pydantic` | Layer 2, toolchain and CI | yes | yes |
| `pydantic/pydantic-settings` | Layer 2, toolchain and CI | yes | no |
| `hynek/structlog` | Layer 2, toolchain and CI | yes | no |
| `nautechsystems/nautilus_engineering` | Layer 2, toolchain and CI | yes | no |
| `nautechsystems/nautilus_trader` | Layer 3, trading | yes | yes |
| `alpacahq/alpaca-py` | Layer 3, trading | yes | yes |
| `pola-rs/polars` | Layer 3, trading | yes | yes |
| `openbq-org/OpenBB` | Layer 3, trading | yes | yes |
| `dgunning/edgartools` | Layer 3, trading | yes | yes |
| `JerBouma/FinanceDatabase` | Layer 3, trading | yes | no |
| `deepentropy/tvscreener` | Layer 3, trading | yes | yes |
| `polakowo/vectorbt` | Layer 3, trading | yes | yes |
| `skfolio/skfolio` | Layer 3, trading | yes | no |
| `stefan-jansen/machine-learning-for-trading` | Layer 3, trading | yes | yes |
| `gerrymanoim/exchange_calendars` | Layer 3, trading | yes | no |
| `unionai-oss/pandera` | Layer 3, trading | yes | no |
| `microsoft/qlib` | Layer 3, trading | yes | yes |
| `google-research/timesfm` | Layer 3, trading | yes | yes |
| `TauricResearch/TradingAgents` | Layer 3, trading | yes | yes |
| `nautechsystems/nautilus_agents` | Layer 3, trading | yes | no |
| `tradingview/lightweight-charts` | Layer 4, display | yes | no |
| `perspective-dev/perspective` | Layer 4, display | yes | no |
| `tradesdontlie/tradingview-mcp` | Layer 4, display | yes | yes |
| `bigskysoftware/htmx` | Layer 4, display | yes | yes |
| `microsoft/playwright` | Layer 4, display | yes | yes |
| `plotly/plotly.py` | Layer 4, display | yes | no |
| `anthropics/claude-code` | Layer 5, runtimes | yes | yes |
| `openai/codex` | Layer 5, runtimes | yes | no |
| `deepseek-ai/deepseek-harness` | Layer 5, runtimes | yes | yes |
| `ccch1mneyyy/dsh-TUI` | Layer 5, runtimes | yes | yes |
| `stablyai/orca` | Layer 6, orchestration and review | yes | yes |
| `openai/codex-plugin-cc` | Layer 6, orchestration and review | yes | yes |
| `alibaba/open-code-review` | Layer 6, orchestration and review | yes | yes |
| `max-sixty/worktrunk` | Layer 6, orchestration and review | yes | yes |
| `coleam00/Archon` | Layer 6, orchestration and review | yes | yes |
| `agentskills/agentskills` | Layer 7, skills and context | yes | yes |
| `rtk-ai/rtk` | Layer 7, skills and context | yes | yes |
| `DietrichGebert/ponytail` | Layer 7, skills and context | yes | yes |
| `obra/superpowers` | Layer 7, skills and context | yes | yes |
| `Yeachan-Heo/oh-my-codex` | Layer 7, skills and context | yes | yes |
| `addyosmani/agent-skills` | Layer 7, skills and context | yes | yes |
| `Yeachan-Heo/oh-my-claudecode` | Layer 7, skills and context | yes | yes |
| `kenn-io/agentsview` | Layer 7, skills and context | yes | yes |
| `jarrodwatts/claude-hud` | Layer 7, skills and context | yes | yes |
| `oraios/serena` | Layer 7, skills and context | yes | yes |
| `ast-grep/ast-grep` | Layer 7, skills and context | yes | no |
| `gastownhall/beads` | Layer 8, memory and retrieval | yes | yes |
| `microsoft/markitdown` | Layer 8, memory and retrieval | yes | yes |
| `VectifyAI/PageIndex` | Layer 8, memory and retrieval | yes | yes |
| `ccusage/ccusage` | Context and status tools | no | no |
| `ranxianglei/billion-context` | Context and status tools | no | yes |
| `JuliusBrussee/caveman` | Context and status tools | no | yes |
| `yamadashy/repomix` | Context and status tools | no | yes |
| `OthmanAdi/planning-with-files` | Context and status tools | no | yes |
| `ayghri/i-have-adhd` | Context and status tools | no | yes |
| `toon-format/toon` | Context and status tools | no | yes |
| `getagentseal/codeburn` | Context and status tools | no | yes |
| `graykode/abtop` | Context and status tools | no | yes |
| `sirmalloc/ccstatusline` | Context and status tools | no | yes |
| `Maciek-roboblog/Claude-Code-Usage-Monitor` | Context and status tools | no | yes |
| `EveryInc/compound-engineering-plugin` | Measured here and not adopted | no | yes |
| `openai/plugins` | Measured here and not adopted | no | yes |
| `trailofbits/skills` | Measured here and not adopted | no | yes |
| `awesome-dsh-plugin/awesome-dsh-plugin` | Measured here and not adopted | no | yes |
| `MinishLab/semble` | Measured here and not adopted | no | yes |
| `mksglu/context-mode` | Measured here and not adopted | no | yes |
| `headroomlabs-ai/headroom` | Measured here and not adopted | no | yes |
| `QuantConnect/Lean` | A second engine | no | yes |
| `StockSharp/StockSharp` | A second engine | no | yes |
| `ricequant/rqalpha` | A second engine | no | yes |
| `fasiondog/hikyuu` | A second engine | no | yes |
| `bbfamily/abu` | A second engine | no | yes |
| `kernc/backtesting.py` | A second engine | no | yes |
| `whchien/ai-trader` | A second engine | no | yes |
| `coding-kitties/investing-algorithm-framework` | A second engine | no | yes |
| `AI4Finance-Foundation/FinRL-Trading` | A second engine | no | yes |
| `Lumiwealth/lumibot` | An agent places the orders, or the route is live money | no | yes |
| `NoFxAiOS/nofx` | An agent places the orders, or the route is live money | no | yes |
| `TraderAlice/OpenAlice` | An agent places the orders, or the route is live money | no | yes |
| `HKUDS/AI-Trader` | An agent places the orders, or the route is live money | no | yes |
| `HKUDS/Vibe-Trading` | An agent places the orders, or the route is live money | no | yes |
| `marketcalls/openalgo` | An agent places the orders, or the route is live money | no | yes |
| `longbridge/longbridge-terminal` | An agent places the orders, or the route is live money | no | yes |
| `jarrodwatts/jev-trader` | An agent places the orders, or the route is live money | no | yes |
| `shner-elmo/TradingView-Screener` | Trading, no job in this architecture or not kept up | no | yes |
| `tradermonty/claude-trading-skills` | Trading, no job in this architecture or not kept up | no | yes |
| `virattt/ai-hedge-fund` | Trading, no job in this architecture or not kept up | no | yes |
| `virattt/dexter` | Trading, no job in this architecture or not kept up | no | yes |
| `asavinov/intelligent-trading-bot` | Trading, no job in this architecture or not kept up | no | yes |
| `shiyu-coder/Kronos` | Trading, no job in this architecture or not kept up | no | yes |
| `akfamily/akshare` | Trading, no job in this architecture or not kept up | no | yes |
| `ZhuLinsen/daily_stock_analysis` | Trading, no job in this architecture or not kept up | no | yes |
| `xbtlin/ai-berkshire` | Trading, no job in this architecture or not kept up | no | yes |
| `anthropics/financial-services` | Trading, no job in this architecture or not kept up | no | yes |
| `666ghj/MiroFish` | Trading, no job in this architecture or not kept up | no | yes |
| `ClickHouse/ClickHouse` | Trading, no job in this architecture or not kept up | no | yes |
| `PrefectHQ/prefect` | Trading, no job in this architecture or not kept up | no | yes |
| `flyteorg/flyte` | Trading, no job in this architecture or not kept up | no | yes |
| `dbt-labs/dbt` | Trading, no job in this architecture or not kept up | no | yes |
| `wilsonfreitas/awesome-quant` | Trading, no job in this architecture or not kept up | no | yes |
| `paperswithbacktest/awesome-systematic-trading` | Trading, no job in this architecture or not kept up | no | yes |
| `wangzhe3224/awesome-systematic-trading` | Trading, no job in this architecture or not kept up | no | yes |
| `atilaahmettaner/tradingview-mcp` | Display, own stack or unofficial endpoint | no | yes |
| `Open-Dev-Society/OpenStock` | Display, own stack or unofficial endpoint | no | yes |
| `Mathieu2301/TradingView-API` | Display, own stack or unofficial endpoint | no | yes |
| `Fincept-Corporation/FinceptTerminal` | Display, own stack or unofficial endpoint | no | yes |
| `ghostfolio/ghostfolio` | Display, own stack or unofficial endpoint | no | yes |
| `koala73/worldmonitor` | Display, own stack or unofficial endpoint | no | yes |
| `margelo/react-native-graph` | Display, own stack or unofficial endpoint | no | yes |
| `astral-sh/ty` | Toolchain, one tool per job | no | yes |
| `jdx/mise` | Toolchain, one tool per job | no | yes |
| `oven-sh/bun` | Toolchain, one tool per job | no | yes |
| `aquasecurity/trivy` | Toolchain, one tool per job | no | yes |
| `NVIDIA/OpenShell` | Toolchain, one tool per job | no | yes |
| `harness/harness` | Toolchain, one tool per job | no | yes |
| `Tracer-Cloud/opensre` | Toolchain, one tool per job | no | yes |
| `di-sukharev/opencommit` | Toolchain, one tool per job | no | yes |
| `architecture-decision-record/architecture-decision-record` | Toolchain, one tool per job | no | yes |
| `vinta/awesome-python` | Toolchain, one tool per job | no | yes |
| `earendil-works/pi` | Runtimes, the same job as the three in use | no | yes |
| `anthropics/claude-agent-sdk-python` | Runtimes, the same job as the three in use | no | yes |
| `shareAI-lab/learn-claude-code` | Runtimes, the same job as the three in use | no | yes |
| `cordiverse/cordis` | Runtimes, the same job as the three in use | no | yes |
| `NousResearch/hermes-agent` | Runtimes, the same job as the three in use | no | yes |
| `NousResearch/hermes-agent-self-evolution` | Runtimes, the same job as the three in use | no | yes |
| `cline/cline` | Runtimes, the same job as the three in use | no | yes |
| `aaif-goose/goose` | Runtimes, the same job as the three in use | no | yes |
| `OpenHands/OpenHands` | Runtimes, the same job as the three in use | no | yes |
| `can1357/oh-my-pi` | Runtimes, the same job as the three in use | no | yes |
| `1jehuang/jcode` | Runtimes, the same job as the three in use | no | yes |
| `tinyhumansai/openhuman` | Runtimes, the same job as the three in use | no | yes |
| `PrimeIntellect-ai/prime-agent` | Runtimes, the same job as the three in use | no | yes |
| `langchain-ai/deepagents` | Runtimes, the same job as the three in use | no | yes |
| `langchain-ai/open-swe` | Runtimes, the same job as the three in use | no | yes |
| `openai/openai-agents-python` | Runtimes, the same job as the three in use | no | yes |
| `HKUDS/nanobot` | Runtimes, the same job as the three in use | no | yes |
| `HKUDS/OpenHarness` | Runtimes, the same job as the three in use | no | yes |
| `odysseus-dev/odysseus` | Runtimes, the same job as the three in use | no | yes |
| `lsdefine/GenericAgent` | Runtimes, the same job as the three in use | no | yes |
| `bytedance/deer-flow` | Runtimes, the same job as the three in use | no | yes |
| `assafelovic/gpt-researcher` | Runtimes, the same job as the three in use | no | yes |
| `BigPizzaV3/CodexPlusPlus` | Runtimes, the same job as the three in use | no | yes |
| `ollama/ollama` | Local models, no workload yet | no | yes |
| `AlexsJones/llmfit` | Local models, no workload yet | no | yes |
| `Andyyyy64/whichllm` | Local models, no workload yet | no | yes |
| `unslothai/unsloth` | Local models, no workload yet | no | yes |
| `kvcache-ai/ktransformers` | Local models, no workload yet | no | yes |
| `ashhart/TensorFold` | Local models, no workload yet | no | yes |
| `magnitudedev/magnitude` | Local models, no workload yet | no | yes |
| `llm-d/llm-d` | Local models, no workload yet | no | yes |
| `LMCache/LMCache` | Local models, no workload yet | no | yes |
| `eugr/spark-vllm-docker` | Local models, no workload yet | no | yes |
| `google-ai-edge/LiteRT-LM` | Local models, no workload yet | no | yes |
| `google-ai-edge/gallery` | Local models, no workload yet | no | yes |
| `NVIDIA/Model-Optimizer` | Local models, no workload yet | no | yes |
| `open-compass/opencompass` | Local models, no workload yet | no | yes |
| `open-compass/VLMEvalKit` | Local models, no workload yet | no | yes |
| `OrchestratorInc/agent-orchestrator` | Orchestrators and councils, the same job as Orca | no | yes |
| `getpaseo/paseo` | Orchestrators and councils, the same job as Orca | no | yes |
| `pingdotgg/t3code` | Orchestrators and councils, the same job as Orca | no | yes |
| `mvschwarz/openrig` | Orchestrators and councils, the same job as Orca | no | yes |
| `omnigent-ai/omnigent` | Orchestrators and councils, the same job as Orca | no | yes |
| `paperclipai/paperclip` | Orchestrators and councils, the same job as Orca | no | yes |
| `ruvnet/ruflo` | Orchestrators and councils, the same job as Orca | no | yes |
| `smtg-ai/claude-squad` | Orchestrators and councils, the same job as Orca | no | yes |
| `multica-ai/multica` | Orchestrators and councils, the same job as Orca | no | yes |
| `HarnessMD/munder-difflin` | Orchestrators and councils, the same job as Orca | no | yes |
| `open-inspect/background-agents` | Orchestrators and councils, the same job as Orca | no | yes |
| `rowboatlabs/rowboat` | Orchestrators and councils, the same job as Orca | no | yes |
| `Nexting-ai/nexting` | Orchestrators and councils, the same job as Orca | no | yes |
| `SeemSeam/claude_codex_bridge` | Orchestrators and councils, the same job as Orca | no | yes |
| `open-multi-agent/open-multi-agent` | Orchestrators and councils, the same job as Orca | no | yes |
| `loopx-project/loopx` | Orchestrators and councils, the same job as Orca | no | yes |
| `unclebob/swarm-forge` | Orchestrators and councils, the same job as Orca | no | yes |
| `superplanehq/superplane` | Orchestrators and councils, the same job as Orca | no | yes |
| `aannoo/hcom` | Orchestrators and councils, the same job as Orca | no | yes |
| `apache/maka` | Orchestrators and councils, the same job as Orca | no | yes |
| `n8n-io/n8n` | Orchestrators and councils, the same job as Orca | no | yes |
| `langgenius/dify` | Orchestrators and councils, the same job as Orca | no | yes |
| `nyldn/claude-octopus` | Orchestrators and councils, the same job as Orca | no | yes |
| `0xNyk/council-of-high-intelligence` | Orchestrators and councils, the same job as Orca | no | yes |
| `wanshuiyin/Auto-claude-code-research-in-sleep` | Orchestrators and councils, the same job as Orca | no | yes |
| `promptfoo/promptfoo` | Evaluation and observability services | no | yes |
| `anthropics/claude-code-action` | Evaluation and observability services | no | yes |
| `comet-ml/opik` | Evaluation and observability services | no | yes |
| `mlflow/mlflow` | Evaluation and observability services | no | yes |
| `SigNoz/signoz` | Evaluation and observability services | no | yes |
| `cheaper-inference/OmniRoute` | Gateways | no | yes |
| `router-for-me/CLIProxyAPI` | Gateways | no | yes |
| `musistudio/claude-code-router` | Gateways | no | yes |
| `farion1231/cc-switch` | Gateways | no | yes |
| `looplj/axonhub` | Gateways | no | yes |
| `weave-os/router` | Gateways | no | yes |
| `NVIDIA-NeMo/Switchyard` | Gateways | no | yes |
| `affaan-m/ECC` | Skill packs and frameworks | no | yes |
| `wshobson/agents` | Skill packs and frameworks | no | yes |
| `SuperClaude-Org/SuperClaude_Framework` | Skill packs and frameworks | no | yes |
| `tw93/Waza` | Skill packs and frameworks | no | yes |
| `mindfold-ai/Trellis` | Skill packs and frameworks | no | yes |
| `Chachamaru127/claude-code-harness` | Skill packs and frameworks | no | yes |
| `revfactory/harness` | Skill packs and frameworks | no | yes |
| `frankbria/ralph-claude-code` | Skill packs and frameworks | no | yes |
| `code-yeongyu/oh-my-openagent` | Skill packs and frameworks | no | yes |
| `DenisSergeevitch/agents-best-practices` | Skill packs and frameworks | no | yes |
| `cobusgreyling/loop-engineering` | Skill packs and frameworks | no | yes |
| `UfoMiao/zcf` | Skill packs and frameworks | no | yes |
| `microsoft/SkillOpt` | Skill packs and frameworks | no | yes |
| `HKUDS/CLI-Anything` | Skill packs and frameworks | no | yes |
| `yusufkaraaslan/Skill_Seekers` | Skill packs and frameworks | no | yes |
| `virgiliojr94/book-to-skill` | Skill packs and frameworks | no | yes |
| `xingkongliang/skills-manager` | Skill packs and frameworks | no | yes |
| `cursor/plugins` | Skill packs and frameworks | no | yes |
| `anthropics/knowledge-work-plugins` | Skill packs and frameworks | no | yes |
| `vercel-labs/agent-skills` | Skill packs and frameworks | no | yes |
| `google-labs-code/stitch-skills` | Skill packs and frameworks | no | yes |
| `obsidianmd/obsidian-skills` | Skill packs and frameworks | no | yes |
| `phuryn/pm-skills` | Skill packs and frameworks | no | yes |
| `drona23/claude-token-efficient` | Guides and catalogues, read but not installed | no | yes |
| `shanraisshan/claude-code-best-practice` | Guides and catalogues, read but not installed | no | yes |
| `shanraisshan/codex-cli-best-practice` | Guides and catalogues, read but not installed | no | yes |
| `anthropics/claude-cookbooks` | Guides and catalogues, read but not installed | no | yes |
| `anthropics/claude-quickstarts` | Guides and catalogues, read but not installed | no | yes |
| `FlorianBruniaux/claude-code-ultimate-guide` | Guides and catalogues, read but not installed | no | yes |
| `luongnv89/claude-howto` | Guides and catalogues, read but not installed | no | yes |
| `ykdojo/claude-code-tips` | Guides and catalogues, read but not installed | no | yes |
| `zebbern/claude-code-guide` | Guides and catalogues, read but not installed | no | yes |
| `x1xhlol/system-prompts-and-models-of-ai-tools` | Guides and catalogues, read but not installed | no | yes |
| `NirDiamant/Prompt_Engineering` | Guides and catalogues, read but not installed | no | yes |
| `karpathy/autoresearch` | Guides and catalogues, read but not installed | no | yes |
| `multica-ai/andrej-karpathy-skills` | Guides and catalogues, read but not installed | no | yes |
| `hesreallyhim/awesome-claude-code` | Guides and catalogues, read but not installed | no | yes |
| `ComposioHQ/awesome-claude-skills` | Guides and catalogues, read but not installed | no | yes |
| `composio-community/awesome-claude-plugins` | Guides and catalogues, read but not installed | no | yes |
| `composio-community/awesome-codex-skills` | Guides and catalogues, read but not installed | no | yes |
| `quemsah/awesome-claude-plugins` | Guides and catalogues, read but not installed | no | yes |
| `VoltAgent/awesome-agent-skills` | Guides and catalogues, read but not installed | no | yes |
| `VoltAgent/awesome-claude-code-subagents` | Guides and catalogues, read but not installed | no | yes |
| `VoltAgent/awesome-codex-subagents` | Guides and catalogues, read but not installed | no | yes |
| `VoltAgent/awesome-openclaw-skills` | Guides and catalogues, read but not installed | no | yes |
| `VoltAgent/awesome-claude-design` | Guides and catalogues, read but not installed | no | yes |
| `github/awesome-copilot` | Guides and catalogues, read but not installed | no | yes |
| `0xNyk/awesome-hermes-agent` | Guides and catalogues, read but not installed | no | yes |
| `e2b-dev/awesome-ai-agents` | Guides and catalogues, read but not installed | no | yes |
| `Shubhamsaboo/awesome-llm-apps` | Guides and catalogues, read but not installed | no | yes |
| `sickn33/agentic-awesome-skills` | Guides and catalogues, read but not installed | no | yes |
| `alirezarezvani/claude-skills` | Guides and catalogues, read but not installed | no | yes |
| `davila7/claude-code-templates` | Guides and catalogues, read but not installed | no | yes |
| `msitarzewski/agency-agents` | Guides and catalogues, read but not installed | no | yes |
| `tech-leads-club/agent-skills` | Guides and catalogues, read but not installed | no | yes |
| `punkpeye/awesome-mcp-servers` | Guides and catalogues, read but not installed | no | yes |
| `f/prompts.chat` | Guides and catalogues, read but not installed | no | yes |
| `cloudflare/security-audit-skill` | Security skills | no | yes |
| `awarexone/Agentic-Bug-Hunter` | Security skills | no | yes |
| `alphaXiv/OpenResearch` | Research, writing and design skills, no job here | no | yes |
| `K-Dense-AI/scientific-agent-skills` | Research, writing and design skills, no job here | no | yes |
| `Imbad0202/academic-research-skills` | Research, writing and design skills, no job here | no | yes |
| `Orchestra-Research/AI-Research-SKILLs` | Research, writing and design skills, no job here | no | yes |
| `uditgoenka/autoresearch` | Research, writing and design skills, no job here | no | yes |
| `mvanhorn/last30days-skill` | Research, writing and design skills, no job here | no | yes |
| `LearningCircuit/local-deep-research` | Research, writing and design skills, no job here | no | yes |
| `MiroMindAI/MiroThinker` | Research, writing and design skills, no job here | no | yes |
| `blader/humanizer` | Research, writing and design skills, no job here | no | yes |
| `cathrynlavery/diagram-design` | Research, writing and design skills, no job here | no | yes |
| `tt-a1i/archify` | Research, writing and design skills, no job here | no | yes |
| `likec4/likec4` | Research, writing and design skills, no job here | no | yes |
| `Leonxlnx/taste-skill` | Research, writing and design skills, no job here | no | yes |
| `pbakaus/impeccable` | Research, writing and design skills, no job here | no | yes |
| `Nutlope/hallmark` | Research, writing and design skills, no job here | no | yes |
| `nextlevelbuilder/ui-ux-pro-max-skill` | Research, writing and design skills, no job here | no | yes |
| `morluto/rea` | Research, writing and design skills, no job here | no | yes |
| `browser-use/browser-use` | Browsers, scraping and MCP servers | no | yes |
| `citrolabs/ego-lite` | Browsers, scraping and MCP servers | no | yes |
| `lightpanda-io/browser` | Browsers, scraping and MCP servers | no | yes |
| `h4ckf0r0day/obscura` | Browsers, scraping and MCP servers | no | yes |
| `CloakHQ/CloakBrowser` | Browsers, scraping and MCP servers | no | yes |
| `D4Vinci/Scrapling` | Browsers, scraping and MCP servers | no | yes |
| `unclecode/crawl4ai` | Browsers, scraping and MCP servers | no | yes |
| `KnockOutEZ/wigolo` | Browsers, scraping and MCP servers | no | yes |
| `Panniantong/Agent-Reach` | Browsers, scraping and MCP servers | no | yes |
| `searxng/searxng` | Browsers, scraping and MCP servers | no | yes |
| `firecrawl/firecrawl-mcp-server` | Browsers, scraping and MCP servers | no | yes |
| `bytebase/dbhub` | Browsers, scraping and MCP servers | no | yes |
| `mcp-use/mcp-use` | Browsers, scraping and MCP servers | no | yes |
| `modelcontextprotocol/servers` | Browsers, scraping and MCP servers | no | yes |
| `modelcontextprotocol/modelcontextprotocol` | Browsers, scraping and MCP servers | no | yes |
| `wonderwhy-er/DesktopCommanderMCP` | Browsers, scraping and MCP servers | no | yes |
| `ComposioHQ/composio` | Browsers, scraping and MCP servers | no | yes |
| `trycua/cua` | Browsers, scraping and MCP servers | no | yes |
| `vercel-labs/agent-desktop` | Browsers, scraping and MCP servers | no | yes |
| `teng-lin/notebooklm-py` | Browsers, scraping and MCP servers | no | yes |
| `mem0ai/mem0` | Memory servers and vaults | no | yes |
| `thedotmack/claude-mem` | Memory servers and vaults | no | yes |
| `vectorize-io/hindsight` | Memory servers and vaults | no | yes |
| `MemPalace/mempalace` | Memory servers and vaults | no | yes |
| `rohitg00/agentmemory` | Memory servers and vaults | no | yes |
| `supermemoryai/supermemory` | Memory servers and vaults | no | yes |
| `EverMind-AI/EverOS` | Memory servers and vaults | no | yes |
| `codejunkie99/agentic-stack` | Memory servers and vaults | no | yes |
| `topoteretes/cognee` | Memory servers and vaults | no | yes |
| `akitaonrails/ai-memory` | Memory servers and vaults | no | yes |
| `TencentCloud/TencentDB-Agent-Memory` | Memory servers and vaults | no | yes |
| `garrytan/gbrain` | Memory servers and vaults | no | yes |
| `Storybloq/storybloq` | Memory servers and vaults | no | yes |
| `volcengine/OpenViking` | Memory servers and vaults | no | yes |
| `Tencent/WeKnora` | Memory servers and vaults | no | yes |
| `onyx-dot-app/onyx` | Memory servers and vaults | no | yes |
| `khoj-ai/khoj` | Memory servers and vaults | no | yes |
| `lfnovo/open-notebook` | Memory servers and vaults | no | yes |
| `nashsu/llm_wiki` | Memory servers and vaults | no | yes |
| `eugeniughelbur/obsidian-second-brain` | Memory servers and vaults | no | yes |
| `AgriciDaniel/claude-obsidian` | Memory servers and vaults | no | yes |
| `breferrari/obsidian-mind` | Memory servers and vaults | no | yes |
| `brianpetro/obsidian-smart-connections` | Memory servers and vaults | no | yes |
| `YishenTu/claudian` | Memory servers and vaults | no | yes |
| `infiniflow/ragflow` | Document stacks, for a later corpus | no | yes |
| `opendatalab/MinerU` | Document stacks, for a later corpus | no | yes |
| `HKUDS/RAG-Anything` | Document stacks, for a later corpus | no | yes |
| `andrewyng/context-hub` | Document stacks, for a later corpus | no | yes |
| `colbymchenry/codegraph` | Code graphs and search servers | no | yes |
| `DeusData/codebase-memory-mcp` | Code graphs and search servers | no | yes |
| `tirth8205/code-review-graph` | Code graphs and search servers | no | yes |
| `Graphify-Labs/graphify` | Code graphs and search servers | no | yes |
| `abhigyanpatwari/GitNexus` | Code graphs and search servers | no | yes |
| `zilliztech/claude-context` | Code graphs and search servers | no | yes |
| `jgravelle/jcodemunch-mcp` | Code graphs and search servers | no | yes |
| `giancarloerra/SocratiCode` | Code graphs and search servers | no | yes |
| `vitali87/code-graph-rag` | Code graphs and search servers | no | yes |
| `xerj-org/xerj` | Code graphs and search servers | no | yes |
| `Egonex-AI/Understand-Anything` | Code graphs and search servers | no | yes |
| `langchain-ai/openwiki` | Code graphs and search servers | no | yes |
| `AsyncFuncAI/deepwiki-open` | Code graphs and search servers | no | yes |
| `ohmyzsh/ohmyzsh` | Desktop and shell tools | no | yes |
| `microsoft/PowerToys` | Desktop and shell tools | no | yes |
| `tw93/Mole` | Desktop and shell tools | no | yes |
| `warpdotdev/warp` | Desktop and shell tools | no | yes |
| `omacom/omarchy` | Desktop and shell tools | no | yes |
| `yorukot/superfile` | Desktop and shell tools | no | yes |
| `sindresorhus/awesome` | Outside the ecosystem | no | yes |
| `sindresorhus/awesome-nodejs` | Outside the ecosystem | no | yes |
| `awesome-selfhosted/awesome-selfhosted` | Outside the ecosystem | no | yes |
| `awesome-foss/awesome-sysadmin` | Outside the ecosystem | no | yes |
| `alebcay/awesome-shell` | Outside the ecosystem | no | yes |
| `veggiemonk/awesome-docker` | Outside the ecosystem | no | yes |
| `docker/awesome-compose` | Outside the ecosystem | no | yes |
| `avelino/awesome-go` | Outside the ecosystem | no | yes |
| `fffaraz/awesome-cpp` | Outside the ecosystem | no | yes |
| `enaqx/awesome-react` | Outside the ecosystem | no | yes |
| `jaywcjlove/awesome-mac` | Outside the ecosystem | no | yes |
| `abhisheknaiidu/awesome-github-profile-readme` | Outside the ecosystem | no | yes |
| `public-apis/public-apis` | Outside the ecosystem | no | yes |
| `ripienaar/free-for-dev` | Outside the ecosystem | no | yes |
| `donnemartin/system-design-primer` | Outside the ecosystem | no | yes |
| `rohitg00/ai-engineering-from-scratch` | Outside the ecosystem | no | yes |
| `chrislgarry/Apollo-11` | Outside the ecosystem | no | yes |
| `VeejaLiu/ScienceFictionCollection` | Outside the ecosystem | no | yes |
| `ankitects/anki` | Outside the ecosystem | no | yes |
| `immich-app/immich` | Outside the ecosystem | no | yes |
| `paperless-ngx/paperless-ngx` | Outside the ecosystem | no | yes |
| `Zackriya-Solutions/meetily` | Outside the ecosystem | no | yes |
| `screenpipe/screenpipe` | Outside the ecosystem | no | yes |
| `clash-verge-rev/clash-verge-rev` | Outside the ecosystem | no | yes |
| `warp-tech/warpgate` | Outside the ecosystem | no | yes |
| `Kong/insomnia` | Outside the ecosystem | no | yes |
| `OtterMind/Chat2DB` | Outside the ecosystem | no | yes |
| `supabase/supabase` | Outside the ecosystem | no | yes |
| `tursodatabase/turso` | Outside the ecosystem | no | yes |
| `PostHog/posthog` | Outside the ecosystem | no | yes |
| `usekaneo/kaneo` | Outside the ecosystem | no | yes |
| `refactoringhq/tolaria` | Outside the ecosystem | no | yes |
| `deta/surf` | Outside the ecosystem | no | yes |
| `Crosstalk-Solutions/project-nomad` | Outside the ecosystem | no | yes |
| `flutter/flutter` | Outside the ecosystem | no | yes |
| `llvm/llvm-project` | Outside the ecosystem | no | yes |
| `catchorg/Catch2` | Outside the ecosystem | no | yes |
| `google/googletest` | Outside the ecosystem | no | yes |
| `fmtlib/fmt` | Outside the ecosystem | no | yes |
| `JetBrains/go-modern-guidelines` | Outside the ecosystem | no | yes |
| `e2e-inc/e2e` | Outside the ecosystem | no | yes |
| `abi/screenshot-to-code` | Outside the ecosystem | no | yes |
| `BuilderIO/agent-native` | Outside the ecosystem | no | yes |
| `aws/agent-toolkit-for-aws` | Outside the ecosystem | no | yes |
| `bilawalsidhu/gods-eye-view` | Outside the ecosystem | no | yes |
| `bradautomates/claude-video` | Outside the ecosystem | no | yes |
| `HKUDS/DeepTutor` | Outside the ecosystem | no | yes |
| `THU-MAIC/OpenMAIC` | Outside the ecosystem | no | yes |
| `Open-LLM-VTuber/Open-LLM-VTuber` | Outside the ecosystem | no | yes |
| `livekit/agents` | Outside the ecosystem | no | yes |
| `modelscope/FunASR` | Outside the ecosystem | no | yes |
| `NVIDIA-NeMo/Speech` | Outside the ecosystem | no | yes |
| `NVIDIA/auto-ontology` | Outside the ecosystem | no | yes |
| `opengeos/GeoLibre` | Outside the ecosystem | no | yes |
| `storytold/artcraft` | Outside the ecosystem | no | yes |
| `nexu-io/openmotion` | Outside the ecosystem | no | yes |
| `ZSeven-W/openpencil` | Outside the ecosystem | no | yes |
| `Osmantic/ODS` | Outside the ecosystem | no | yes |
| `languagetool-org/languagetool` | Outside the ecosystem | no | yes |
