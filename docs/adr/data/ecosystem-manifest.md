# Ecosystem manifest

Taken from the plan approved by the owner on 2026-11-13.

State: **in use**; **add** (install, integrate or build on, one pull request each);
**measure** (a harness addition, adopted only on an ADR's with-and-without result); **watch**.
Research tools install into a `research` dependency group and test tools into `dev`; neither
is in the order path.

2026-11-13: the owner decided that a stack of additions to one runtime can be admitted by
selection (maintained, leading, one upstream per job) in one ADR, without a with-and-without
run per item (`docs/adr/README.md`).

2026-11-13 (ADR 0018, the Codex worker stack): `Yeachan-Heo/oh-my-codex` moves from "measured
here and not adopted" to layer 7, in use for Codex; `DietrichGebert/ponytail` from "measure" to
in use, as a Codex plugin; `rtk-ai/rtk` is not adopted (ADR 0017).
2026-11-14 (ADR 0018): `oraios/serena` is in use for Codex as its MCP server for navigation and
diagnostics (layer 7 row); its placement stays in layer 8, where ADR 0016 put it.

### Layer 1, base system
| Job | Rests on | State |
|---|---|---|
| Distro, services | WSL2, Ubuntu 26.04, systemd | in use |
| Python toolchain | `astral-sh/uv` | in use |
| GitHub | `cli/cli` | in use |
| Backups of run records | `restic/restic` | add, when the unattended runs produce state |

### Layer 2, toolchain and CI
| Job | Rests on | State |
|---|---|---|
| Lint and format | `astral-sh/ruff` | in use |
| Types | `microsoft/pyright` | in use |
| Tests | `pytest-dev/pytest` | in use |
| Property tests of trailing and re-entry invariants | `HypothesisWorks/hypothesis` | add (`dev`) |
| Tests at session edges and half days | `adamchainz/time-machine` | add (`dev`) |
| Secret scan | `gitleaks/gitleaks` | in use |
| CI | `actions/checkout`, `astral-sh/setup-uv`, `dependabot/dependabot-core` | in use |
| Settings and logs of the unattended service | `pydantic/pydantic` with `pydantic/pydantic-settings`, `hynek/structlog` | add, replacing hand-written loaders |
| Engineering standards | `nautechsystems/nautilus_engineering` | compare with ours, then an ADR |

### Layer 3, trading
| Job | Rests on | State |
|---|---|---|
| Engine: orders, emulated trailing stops, fast exit, brackets, risk, backtest, sandbox, indicators, statistics, tearsheets | `nautechsystems/nautilus_trader` | in use, pinned 2.0.0rc9; follow each release |
| Alpaca: orders, trade stream, quotes around the clock, screener, clock and calendar | `alpacahq/alpaca-py` | in use, pinned 0.45.0 |
| IBKR | the engine's own Interactive Brokers adapter, IB Gateway | in use |
| Feature and replay computation | `pola-rs/polars` | add (`research`) |
| Reference data, calendars, fundamentals | `openbq-org/OpenBB` | add (`research`) |
| Filings and point-in-time fundamentals | `dgunning/edgartools` | add (`research`) |
| Symbol universe with sector tags | `JerBouma/FinanceDatabase` | add (`research`) |
| Movers and ranking universe | alpaca-py's `ScreenerClient` first; `deepentropy/tvscreener` as advisory input that broker data must confirm | add |
| Parameter sweeps before the engine's backtest confirms | `polakowo/vectorbt` | add (`research`) |
| Purged and combinatorial cross-validation; basket sizing | `skfolio/skfolio` | add (`research`), M5 |
| Deflated Sharpe, overfitting probability; method | `stefan-jansen/machine-learning-for-trading` and its `ml4t-diagnostic` package | add (`research`), M5 |
| Exchange sessions and holidays in replay | `gerrymanoim/exchange_calendars` (live sessions use Alpaca's own clock) | add |
| Replay data checks | `unionai-oss/pandera` | add (`research`) |
| Ranking models | `microsoft/qlib` | measure under purged cross-validation against a plain baseline, M4 |
| Forecast features | `google-research/timesfm` | measure the same way, M5 |
| LLM research signal, offline and advisory | `TauricResearch/TradingAgents` | measure the same way; never in the order path |
| Agent-to-engine interface | `nautechsystems/nautilus_agents` | watch: no host side at rc9 |

### Layer 4, display
| Job | Rests on | State |
|---|---|---|
| Owner-built page: candles, trail lines, fill markers | `tradingview/lightweight-charts` | add, M6 |
| Results views | the engine's Plotly tearsheets | add, M5 |
| Live order and fill blotter | `perspective-dev/perspective` | add, M6, if a static page is not enough |
| TradingView Desktop, attended | `tradesdontlie/tradingview-mcp` (inside the kit) | in use on the Windows side |
| Building and testing the page | `bigskysoftware/htmx`, `microsoft/playwright` | add, M6 |

### Layer 5, runtimes
| Job | Rests on | State |
|---|---|---|
| Lead, and Opus workers | `anthropics/claude-code` | in use |
| Workers and review | `openai/codex` | in use |
| Worker (mechanical tasks only until 2026-11-13) | `deepseek-ai/deepseek-harness` with `ccch1mneyyy/dsh-TUI` | in use |

### Layer 6, orchestration and review
| Job | Rests on | State |
|---|---|---|
| Fleet, one worktree per task | `stablyai/orca` | in use |
| Cross-family review | `openai/codex-plugin-cc` and `codex review` | in use (the plugin has been quiet since July: watched) |
| A second reviewer with a published benchmark | `alibaba/open-code-review` | in use, delegation mode only (ADR 0020, 2026-11-14) |
| Named fallbacks, not installed | `max-sixty/worktrunk` (if Orca is dropped), `coleam00/Archon` (if command-ended gates are needed) | watch |

### Layer 7, skills and context
| Job | Rests on | State |
|---|---|---|
| Skill format | `agentskills/agentskills`, Orca's two skills, the built-in "You should know" | in use |
| The few-line instruction file | the four maintained sources named in section 1 | add |
| Shell-output compression | `rtk-ai/rtk` | not adopted, 2026-11-13 (ADR 0017) |
| Status line: context, plan limits, activity, and token and cost accounting | `jarrodwatts/claude-hud` (ADR 0015) | in use |
| Token and cost accounting for DeepSeek Harness | `kenn-io/agentsview` (reads dsh's sessions) | in use for DeepSeek Harness (ADR 0016) |
| Write-less-code skill | `DietrichGebert/ponytail` | in use for Codex, 2026-11-13 (ADR 0018) |
| Codex workflow layer | `Yeachan-Heo/oh-my-codex` | in use, 2026-11-13 (ADR 0018) |
| Code navigation and diagnostics for Codex | `oraios/serena` | in use, 2026-11-14 (ADR 0018) |
| DeepSeek Harness skills: spec, self-review, source reading, test first, root cause, proof before "done", research, the pull request body | `addyosmani/agent-skills`, `obra/superpowers`, `mattpocock/skills` (single folders at a pin) | in use for DeepSeek Harness (ADR 0016) |
| Structural search | `ast-grep/ast-grep` | in use for DeepSeek Harness (ADR 0016) |

2026-11-13: ADR 0016 (a stack ADR) adds the skills, structural-search and accounting rows for
DeepSeek Harness. `kenn-io/agentsview` holds accounting for dsh, whose sessions claude-hud
and `ccusage/ccusage` do not read.
`anthropics/claude-plugins-official`'s skill-creator was refused: its scripts call another
model service.

2026-11-14: token and cost accounting is held by claude-hud, adopted on 2026-11-13 (ADR 0015): the
session's cost, a daily and weekly ledger, session tokens and both usage windows, all from
Claude Code's own status payload. `ccusage/ccusage` is not installed: one upstream per job. It
would add per-model reports over past transcripts, which nothing here needs yet.

2026-11-14: `DietrichGebert/ponytail` is not installed on Claude Code. Read at v5.3.3 (commit
`7801d061243d7b753bad0e0b3c057cd250b11755`, verified on GitHub, the commit the Codex stack
pins): for Claude Code it ships three hooks that add its ruleset and a codebase map to every
session and every subagent, a band module that writes a ledger after each turn, and a prompt
that makes Claude offer to replace `statusLine`, which claude-hud holds (ADR 0015). On Claude
Code the cleanup and write-less job is left to the oh-my-claudecode stack now in review, which
keeps its `ai-slop-cleaner` skill for it; on Codex ponytail holds the job. One upstream per
job on each runtime. Revisit if that stack is not adopted.

### Layer 8, memory and retrieval
| Job | Rests on | State |
|---|---|---|
| Memory and code search | files in git, ripgrep, pyright | in use (they beat the measured alternative, ADR 0001) |
| Shared task state | `gastownhall/beads` | measure, only when workers collide over task state |
| A corpus of broker documents | `microsoft/markitdown`, `VectifyAI/PageIndex` | add, when there is a corpus |
| Code navigation for DeepSeek Harness | the `lsp` tool of `deepseek-ai/deepseek-harness` (`dsh-lsp` packages) on the worktree's pyright | in use (ADR 0016) |
| Its runner-up, not installed | `oraios/serena` | watch |

2026-11-13: ADR 0016 adds dsh's official `lsp` tool for code navigation (dsh has no LSP of its
own). `oraios/serena` is the runner-up: the official package does the job at 170 always-on
tokens, against 2,927 for serena.

## Placement of the starred repositories

The owner's starred list was read on 2026-11-13 with `gh api user/starred --paginate --jq '.[].full_name'`.

- Starred repositories returned by the command: 393
- Rows with `starred` = yes: 393
- Rows with `starred` = no: 18

2026-11-13 (ADR 0016): `addyosmani/agent-skills`, `obra/superpowers` and `kenn-io/agentsview`
move into Layer 7 and `oraios/serena` into Layer 8. `ast-grep/ast-grep` (not starred) is added,
so the rows with `starred` = no go from 17 to 18.

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
| `ast-grep/ast-grep` | Layer 7, skills and context | yes | no |
| `ccusage/ccusage` | Context and status tools | no | no |
| `DietrichGebert/ponytail` | Layer 7, skills and context | yes | yes |
| `Yeachan-Heo/oh-my-codex` | Layer 7, skills and context | yes | yes |
| `gastownhall/beads` | Layer 8, memory and retrieval | yes | yes |
| `microsoft/markitdown` | Layer 8, memory and retrieval | yes | yes |
| `VectifyAI/PageIndex` | Layer 8, memory and retrieval | yes | yes |
| `obra/superpowers` | Layer 7, skills and context | yes | yes |
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
| `addyosmani/agent-skills` | Layer 7, skills and context | yes | yes |
| `wshobson/agents` | Skill packs and frameworks | no | yes |
| `Yeachan-Heo/oh-my-claudecode` | Skill packs and frameworks | no | yes |
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
| `ranxianglei/billion-context` | Context and status tools | no | yes |
| `JuliusBrussee/caveman` | Context and status tools | no | yes |
| `yamadashy/repomix` | Context and status tools | no | yes |
| `OthmanAdi/planning-with-files` | Context and status tools | no | yes |
| `ayghri/i-have-adhd` | Context and status tools | no | yes |
| `toon-format/toon` | Context and status tools | no | yes |
| `kenn-io/agentsview` | Layer 7, skills and context | yes | yes |
| `getagentseal/codeburn` | Context and status tools | no | yes |
| `graykode/abtop` | Context and status tools | no | yes |
| `jarrodwatts/claude-hud` | Layer 7, skills and context | yes | yes |
| `sirmalloc/ccstatusline` | Context and status tools | no | yes |
| `Maciek-roboblog/Claude-Code-Usage-Monitor` | Context and status tools | no | yes |
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
| `oraios/serena` | Layer 8, memory and retrieval | yes | yes |
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
