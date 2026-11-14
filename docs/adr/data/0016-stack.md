# ADR 0016 data: the DeepSeek Harness worker stack

Read 2026-11-13 and 2026-11-14 (UTC) in the `meridian` distro, dsh 0.2.2-rc.1 (`66491b05`) with dsh-tui 0.20.0. Stars and last push are `gh api repos/<repo>` values at that time. Advisories are each repository's published GitHub security advisories (`gh api repos/<repo>/security-advisories`), read on the same day; none of the advisories pages showed an entry that affects the pin.

## Components (sections 2 to 4 and 8)

| Component | Upstream, pin | Stars, last push | Advisories | Installs and writes | Sends | Removal |
|---|---|---|---|---|---|---|
| Skills `spec-driven-development`, `code-review-and-quality`, `source-driven-development` | `addyosmani/agent-skills` 0.6.15, commit `8bfcc1f9916f2eea55494d8c1fa7f4bde867dd9e`, MIT | 117,200; 2026-11-01 | none published | sparse checkout in `~/.local/share/meridian/dsh-skill-src/addyosmani__agent-skills`, folders copied to `~/.dsh/skills/` | nothing; the text tells the model to fetch official docs | `rm -rf ~/.dsh/skills/{spec-driven-development,code-review-and-quality,source-driven-development} ~/.local/share/meridian/dsh-skill-src/addyosmani__agent-skills` |
| Skills `test-driven-development`, `systematic-debugging`, `verification-before-completion` | `obra/superpowers` v7.0.2, commit `22f0b463e7a5e579904dd6211a520321035526f7`, MIT | 317,290; 2026-11-03 | none published | as above (`obra__superpowers`); single folders, not the plugin or its SessionStart hook | nothing | `rm -rf ~/.dsh/skills/{test-driven-development,systematic-debugging,verification-before-completion} ~/.local/share/meridian/dsh-skill-src/obra__superpowers` |
| Skills `research`, `pr` | `mattpocock/skills` v1.3.2, commit `d1478fcb140db0b93c0c8df17bcfd311844749d0`, MIT | 323,901; 2026-11-13 | none published | as above (`mattpocock__skills`); each folder also holds an `agents/openai.yaml` and `pr` a `CREDITS.md`, copied unchanged | nothing | `rm -rf ~/.dsh/skills/{research,pr} ~/.local/share/meridian/dsh-skill-src/mattpocock__skills` |
| Code navigation `@deepseek-ai/dsh-lsp`, `dsh-lsp-stdio`, `dsh-tool-lsp` | `deepseek-ai/deepseek-harness`, npm 0.2.2-rc.1 (integrity values in `setup.sh` and `UPSTREAM.md`), MIT | 280,629; 2026-11-13 | none published | three plain dependencies in `~/.dsh/profiles/dsh-tui` (`dsh plugin --profile dsh-tui add`); three rows in the Meridian block; one read-only `lsp` tool. Its server is `sh -c 'exec ./.venv/bin/pyright-langserver --stdio'`, started in the session's working directory | nothing (a local language server) | delete the three `meridian-*lsp*` rows from the block, then `dsh plugin --profile dsh-tui remove @deepseek-ai/dsh-lsp @deepseek-ai/dsh-lsp-stdio @deepseek-ai/dsh-tool-lsp` |
| ast-grep | `ast-grep/ast-grep` 0.51.2, commit `627f854bc649ddf3eacdaabb5e61c76317da6260`, asset sha256 `40604c21…82366df`, MIT | 16,572; 2026-11-14 | three: GHSA-xx6h-xcfw-vf5j (critical) and GHSA-cmvf-x8f7-rvp6 (high), both fixed in 0.50.0, and GHSA-fj5f-4qw6-hhpg (medium), fixed in 0.51.1; the pin is past all three | `~/.local/bin/ast-grep`; the zip's `sg` alias is not installed (it would shadow the system's `sg`) | nothing | `rm ~/.local/bin/ast-grep` |
| agentsview | `kenn-io/agentsview` v0.47.0, commit `1079cb632051e8c9cbad2dcc945a60643c756d81`, asset sha256 `a49876ed…b0dc45`, MIT | 6,436; 2026-11-14 | none published | `~/.local/libexec/meridian/agentsview`, the wrapper `~/.local/bin/agentsview`; when run, a SQLite archive in `~/.agentsview/` and a daemon on 127.0.0.1:8080 | by default an anonymous PostHog ping once a day and a GitHub release check: the wrapper sets `AGENTSVIEW_TELEMETRY_ENABLED=0`, `DO_NOT_TRACK=1` and `AGENTSVIEW_DISABLE_UPDATE_CHECK=1`; its README also names LiteLLM and OpenRouter price tables, with an offline fallback | `rm -r ~/.local/bin/agentsview ~/.local/libexec/meridian ~/.agentsview` |
| Completion gate | own design: `deploy/wsl/dsh-check-gate.sh`, mounted by a second `@deepseek-ai/dsh-hooks-claude-code` row (`meridian-check-gate`) | n/a | n/a | `~/.dsh/hooks/dsh-check-gate.sh`, `~/.dsh/meridian-hooks.json`; per-session block counts under the worktree's git directory (`meridian-check-gate/`) | nothing | delete the `meridian-check-gate` row, then `rm -r ~/.dsh/hooks ~/.dsh/meridian-hooks.json` |
| Meridian block in `~/.dsh/cordis.patch.yml` | own design | n/a | n/a | the model row, the three LSP rows and the gate row, between `# >>> meridian-managed` and `# <<< meridian-managed`, above Orca's block, rewritten whole on each `setup.sh dsh` | nothing | delete the block's lines |

Install: `deploy/wsl/setup.sh dsh` from `~/src/meridian`, then `deploy/wsl/setup.sh agents-check`. `check_dsh` fails on any of these:
- a skill checkout is not clean at its pin, or a copy differs from it;
- `~/.dsh/skills` holds a name outside the eight;
- a row of the block is missing or disabled in `dsh --profile dsh-tui --dump-config`;
- any MCP row exists;
- an LSP package is missing from the profile;
- ast-grep or agentsview is not at its pin, or `~/.local/bin/sg` exists;
- the gate copy differs from the repository's;
- dsh is 0.2.2-rc.2 or newer and its worktree plugin lacks `retainOnArchive: true`.

### What was checked at source

- `@deepseek-ai/dsh-mcp-client` ships inside dsh's own tree (it is one of its bundled packages) and resolved by name from a profile with no dependencies. The stack ended up adding no MCP server, so it is not used.
- The LSP packages declare no `dsh.bundle`; `dsh plugin add` installs them as plain dependencies, and Cordis rows mount them by name.
- The definition check needed no model call. In a scratch dsh home with no network, a local stub answered the first request with one `lsp` tool call: `goToDefinition` at `meridian/ibkr_paper.py:72:64`, the name `IbkrBoundary`. dsh returned `meridian/boundary.py:86:7`, the class, from that worktree's `.venv` pyright 1.1.414. The stub then ended the turn.
- agentsview's own `source list` names `deepseek-harness` with default directory `.dsh/sessions` (`DEEPSEEK_HARNESS_SESSIONS_DIR`). A sync of the scratch home found its three stub sessions.
- Hook bridge README at 0.2.2-rc.1: "One config applies to the whole process"; `stop_hook_active` is always false; no consecutive-block cap.
- Two mounts in one process, tested in a scratch home with no network and the stub. Each read its own config: both SessionStart and Stop hooks ran. The second mount's block forced one more model turn, then both passed.
- The gate's row fails to load in a profile without the bridge package, such as the shipped headless template, with a warning.
- dsh 0.2.2-rc.2's `@deepseek-ai/dsh-experimental-worktree` has `retainOnArchive: z.boolean().default(false)`, and archive cleanup removes the checkouts a Session created (its `src/index.ts` and `src/archive.ts`).
- Idempotence, in a scratch `HOME` and `DSH_HOME`, starting from a copy of the machine's home patch:
  - two runs of `setup.sh dsh` left byte-identical files and the patch file's mtime unchanged;
  - Orca's block hashed `05b394bf…` before and after;
  - the old standalone model row moved into the block;
  - `check_dsh` passed, failed on one changed skill file and on an extra folder, and passed again once restored.

## Always-on context (section 5)

Method: [ab-dsh.md](ab-dsh.md)'s capture route, with `0012_analyze_capture.py` and `0012_count_tokens.py` (o200k_base, vocabulary sha256 `446a9538…`).
- Setup:
  - a scratch `HOME` and `DSH_HOME` in the shipped headless profile, with no key in the environment;
  - `unshare -rn` (no network), and `DEEPSEEK_BASE_URL` at a local stub that answers "OK";
  - Orca's `orca-agent-hooks` row disabled in both arms by a shared `--patch`;
  - `--permission-mode workspace-write --approval-policy never`, run in a clone of this repository.
- The probe: `Reply with exactly the word OK. Do not call any tool.` Runs in the order a1 b1 b2 a2 a3 b3.
- Arm a is today's home patch: upload rows, the model row and Orca's block. Arm b is `setup.sh dsh`'s home patch with `~/.dsh/skills`.
- The config dumps of the two arms differ only in the block's rows. The gate row does not load in this profile; it adds no prompt text.

| First request (o200k tokens) | a: before (3 runs) | b: after (3 runs) | Difference |
|---|---|---|---|
| system text | 523 | 583 | +60 (the `lsp` guidance) |
| tools (wire JSON) | 3,981 (24 tools) | 4,151 (25 tools) | +170 (`lsp`) |
| messages | 2,792 | 3,157 | +365 (the eight skills' names and descriptions) |
| prompt total | 7,296 | 7,891 | **+595** |
| raw request body | 7,513 tokens, 33,368 bytes | 8,115 tokens, 36,454 bytes | +602 |

The three runs of each arm were byte-identical (normalized sha256 equal). The figures are for the headless template; only the difference carries over to `dsh-tui`.

The same route measured serena 2.1.0 with its eight tools at +3,353 in total. Its tools were +2,927 (serena's schemas 2,721, dsh's MCP resource tools 206), with +61 of system text and the same +365 of skills.

## Refused, deferred and runner-up

| Item | Status | Reason | Trigger (dated) |
|---|---|---|---|
| `anthropics/claude-plugins-official` `skill-creator` (47,215; 2026-11-14; head `b5b01ac4f889fec0c4c6bb89f27ca7c8574473f6`, no releases) | refused | `scripts/run_eval.py`, `run_loop.py` and `improve_description.py` start `claude -p`, which sends skill text and queries to Anthropic, and `run_eval.py` writes `.claude/commands/` into the project. `eval-viewer/generate_review.py` kills any process listening on its port (`lsof -ti` then SIGTERM). `eval-viewer/viewer.html` loads `cdn.sheetjs.com/xlsx-0.20.3`. SKILL.md tells the agent to run these | 2027-02-11, or a version without them |
| `oraios/serena` 2.1.0 (31,367; 2026-11-09; wheel sha256 `cc6ae542…6b95d87`) | runner-up, not installed | the official `lsp` tool does navigation at 170 tokens. serena adds diagnostics and rename at +3,353 tokens. It needed `agent_interface: tools` (the REPL default runs Python), a fixed tool set, no modes, no trusted projects, a replacement connection line, and `SERENA_USAGE_REPORTING=false` (it pings `oraios-software.de` by default). Three advisories are published. Diagnostics stay with `uv run pyright` | 2027-02-11, or when the `lsp` tool fails a real task |
| `rtk-ai/rtk` | deferred | its hook rewrites the command; dsh 0.2.2-rc.1's bridge logs `updatedInput` without applying it (bridge README, "PreToolUse is partial"); nine native rewriters exist on the plugin list, the largest with 18 stars | the bridge applies `updatedInput`; checked again 2026-11-19 with rc.2 |
| `gastownhall/beads` | deferred | Orca's orchestration holds task state | the manifest's trigger: workers collide over task state |
| dsh 0.2.2-rc.2 (published 2026-11-12) | deferred | archiving a session deletes eligible worktrees by default; `check_dsh` fails on rc.2 or newer until `retainOnArchive: true` is set | after 2026-11-19 (seven days), with that switch set first |
| `microsoft/playwright-cli` | deferred | no page to test yet | the display milestone (M6) has a page |
| DeepSeek V4.1-Pro | deferred | not released | its release: read the notes, then move `DSH_MODEL` |
| `ranxianglei/billion-context` 0.1.213 (7,268) | deferred | updates itself (npm every 3 minutes unless `--no-auto-update`), so it cannot be pinned; it carries all model traffic through a local proxy and turns built-in compaction off | 2027-02-11, or built-in compaction measured failing |
| `@deepseek-ai/dsh-subagent-codex` 0.2.2-rc.1 (official) | deferred | always-on cost and benefit not measured; ADR 0009 measured a community peer that failed | 2027-02-11, measured as in ADR 0009 |
| `@deepseek-ai/dsh-experimental-session-search` 0.2.2-rc.1 (official) | deferred | experimental; same working directory only, and Orca gives each task its own | 2027-02-11 |

Jobs left to built-ins or with no pick:
- Python craft is the repository's `AGENTS.md` check line; the leading skill (trailofbits `modern-python`) replaces pyright with `ty`.
- Library docs come from the installed package, tagged source and `gh api`. Context7 would be a hosted index needing an account.
- GitHub work is `gh` (the GitHub MCP server needs a second token). Web research is dsh's built-in search and fetch.
- Planning is dsh's plan mode, todo and goals.
- No pick for:
  - sequential thinking (a scratchpad for a model already at maximum effort);
  - a model gateway (dsh picks a model per sub-agent);
  - a memory server, or a second web-search stack;
  - a shell sandbox beyond dsh's own (optional security work);
  - notifications (Orca's hooks).
- The verification, LSP and notification plugins on dsh's community list have 6 to 132 stars of their own.

## Every starred repository in the agent groups

Verdicts from the skills and tools research of 2026-11-13, each repository once, as stars and last push (2026). Picked or placed here: see above.

- **Instruction file sources:** `anthropics/claude-plugins-official` 47,212, 11-14: skill-creator refused (above); `mattpocock/skills` 323,891, 11-13: picked; `walkinglabs/learn-harness-engineering` 24,565, 10-22: guide; `Piebald-AI/claude-code-system-prompts` 13,161, 11-13: reference text.
- **Layer 7:** `agentskills/agentskills` 27,271, 11-04: the format, in use; `rtk-ai/rtk` 86,515, 11-13: deferred; `ccusage/ccusage` 19,429, 11-14: no dsh source, replaced by agentsview; `DietrichGebert/ponytail` 190,418, 10-29: only `.openclaw` skill paths, no job.
- **Measured here and not adopted:** `obra/superpowers` 317,285, 11-03: three folders picked; compound-engineering-plugin 26,078, 11-13: ADR 0006 stands; `openai/plugins` 7,936, 11-14: Codex format; oh-my-codex 33,783, 11-10: Codex only; `trailofbits/skills` 8,178, 11-12: `ty` conflicts with pyright; awesome-dsh-plugin 24,590, 11-13: catalogue (ranked below); semble 6,417, 11-08: ADR 0001 stands; context-mode 34,060, 11-14 and headroom 79,614, 11-14: duplicates of rtk.
- **Skill packs and frameworks:**
  - Picked: `addyosmani/agent-skills` 117,194, 11-01.
  - Not picked:
    - ECC 302,510, 11-09: catch-all, heavy.
    - wshobson/agents 42,494, 11-09: generic Python skills.
    - oh-my-claudecode 40,816, 11-13 and SuperClaude 23,934, 09-27: Claude formats.
    - Waza 7,585, 11-11: a duplicate.
    - Trellis 15,137, 09-29: a framework.
    - oh-my-openagent 70,897, 11-13: another runtime.
    - zcf 6,069, 10-29: a Claude config tool.
    - cursor/plugins 16,221, 11-14: Cursor format.
    - SkillOpt 19,069, 11-10: runner-up for skill authoring.
  - Small: claude-code-harness 3,208, 11-11; agents-best-practices 2,432, 10-19; skills-manager 7,496, 11-12.
  - Borderline stale: revfactory/harness 9,360, 09-28; Skill_Seekers 15,307, 09-30.
  - No job: ralph-claude-code 9,730, 11-14; loop-engineering 11,767, 11-14 (a guide); CLI-Anything 58,709, 09-22; book-to-skill 37,786, 11-08; knowledge-work-plugins 35,680, 11-13; vercel-labs/agent-skills 34,029, 11-12; obsidian-skills 52,327, 11-11; pm-skills 27,973, 11-08.
  - Stale: stitch-skills 8,771, 08-17.
- **Context and status tools:**
  - Picked: `kenn-io/agentsview` 6,436, 11-14.
  - Runner-up for compression: caveman 119,718, 11-13.
  - Duplicates: planning-with-files 28,049, 11-11 (of dsh's todo and goals).
  - Dsh not supported: codeburn 11,797, 11-13 (inferred); claude-hud 29,196, 11-10 and ccstatusline 13,595, 11-09 (Claude status lines).
  - No job: billion-context 7,266, 11-14 (deferred above); repomix 29,263, 11-13; i-have-adhd 61,127, 10-19; toon 25,634, 11-11.
  - Small: abtop 3,854, 09-14.
  - Stale: Claude-Code-Usage-Monitor 8,802, 07-05.
- **Guides and catalogues (read only):**
  - Guides: claude-code-best-practice 69,045; claude-cookbooks 54,621; claude-quickstarts 20,880; claude-code-ultimate-guide 6,436; claude-howto 47,160; claude-code-tips 10,340; zebbern/claude-code-guide 4,708; NirDiamant/Prompt_Engineering 7,936.
  - Reference only: system-prompts-and-models-of-ai-tools 144,661.
  - Stale: claude-token-efficient 6,175 (06-16); codex-cli-best-practice 1,027 (06-04); karpathy/autoresearch 100,018 (03-26); andrej-karpathy-skills 232,914 (04-20); VoltAgent/awesome-claude-design 4,528 (06-20); e2b-dev/awesome-ai-agents 30,932 (08-21).
  - Catalogues only: awesome-claude-code 57,953; ComposioHQ/awesome-claude-skills 79,445; composio-community/awesome-claude-plugins 1,994; awesome-codex-skills 17,314; quemsah/awesome-claude-plugins 1,606; VoltAgent/awesome-agent-skills 37,163, awesome-claude-code-subagents 26,538, awesome-codex-subagents 6,475 and awesome-openclaw-skills 53,754; github/awesome-copilot 41,139; awesome-hermes-agent 6,016; awesome-llm-apps 144,588; agentic-awesome-skills 49,671; alirezarezvani/claude-skills 29,772; claude-code-templates 33,493; tech-leads-club/agent-skills 7,167; awesome-mcp-servers 97,685.
  - No job: agency-agents 168,164 (a persona pack); f/prompts.chat 177,119.
- **Security skills:** cloudflare/security-audit-skill 71,997, 09-14 and Agentic-Bug-Hunter 5,865, 11-12: no job here.
- **Research, writing and design skills:**
  - Runner-up for research: scientific-agent-skills 57,080, 11-09.
  - No job: OpenResearch 8,111; academic-research-skills 56,820; AI-Research-SKILLs 14,525; last30days-skill 67,574; humanizer 68,861; diagram-design 66,910; archify 96,246; likec4 6,074; taste-skill 115,110; impeccable 109,685; hallmark 54,566; ui-ux-pro-max-skill 149,148; morluto/rea 457,900.
  - Small: uditgoenka/autoresearch 6,834.
  - A service, not a skill: local-deep-research 9,580.
  - Stale: MiroThinker 8,453 (07-06).
- **Code graphs and search servers:**
  - Runner-up for code navigation: `oraios/serena` 31,366, 11-09.
  - Runner-up for structural search: DeusData/codebase-memory-mcp 48,613, 11-14.
  - Duplicates: colbymchenry/codegraph 77,558, code-review-graph 32,755, Graphify-Labs/graphify 147,334 and GitNexus 48,521 (PolyForm Noncommercial), all of codebase-memory-mcp; xerj 19,042 (of web search).
  - Small duplicates: jcodemunch-mcp 2,850; SocratiCode 3,375; code-graph-rag 5,354.
  - Needs a vector database: zilliztech/claude-context 12,691.
  - No job: Understand-Anything 92,556; openwiki 17,944; deepwiki-open 18,420.
- **Memory and knowledge:**
  - beads 28,722, 11-14: deferred.
  - Runner-up: thedotmack/claude-mem 116,876.
  - Duplicates of beads: mem0 68,929; hindsight 60,917; mempalace 60,550; agentmemory 30,352; supermemory 31,616 (likely hosted); EverOS 13,908; akitaonrails/ai-memory 15,817.
  - Small: agentic-stack 2,314; storybloq 788.
  - No job: cognee 33,300; TencentDB-Agent-Memory 30,883; OpenViking 42,210; onyx 33,383; open-notebook 41,944; nashsu/llm_wiki 21,646; obsidian-second-brain 5,317; claude-obsidian 16,453; obsidian-mind 5,535; obsidian-smart-connections 5,558; claudian 15,987.
  - OpenClaw and Hermes only: gbrain 32,873.
  - Later corpus: Tencent/WeKnora 37,401.
  - Stale: khoj 38,124 (08-02).
- **Browser and web:**
  - Duplicates of Playwright: browser-use 120,965; ego-lite 22,800; lightpanda 42,021.
  - Scraping and stealth, no job: obscura 35,063; CloakBrowser 32,881.
  - Duplicate of wigolo: Scrapling 102,537.
  - Runners-up for web research: crawl4ai 87,329; searxng 39,532.
  - Conditional, not installed: wigolo 5,541.
  - No job: Agent-Reach 111,596.
  - Needs a paid account: firecrawl-mcp-server 7,814.
- **MCP and tools:**
  - No database job: dbhub 3,849.
  - Not a server: mcp-use 10,953 (a framework); modelcontextprotocol/modelcontextprotocol 9,688 (the specification).
  - The reference servers: modelcontextprotocol/servers 91,976 (sequential thinking rejected).
  - Duplicate of built-ins: DesktopCommanderMCP 10,306.
  - Needs an account: composio 31,062; notebooklm-py 20,225.
  - No job: trycua/cua 32,310; agent-desktop 23,360.
- **Documents and corpora:** markitdown 195,267 and PageIndex 40,409: in the architecture. MinerU 83,642: runner-up. ragflow 94,131 and RAG-Anything 24,517: a later corpus. context-hub 13,986 (05-31): stale.
- **Evaluation and observability:**
  - Duplicates of langfuse: opik 23,400; mlflow 28,798.
  - Not run traces: promptfoo 27,151 (prompt evaluations).
  - Claude only: claude-code-action 9,925.
  - Excessive here: signoz 32,632.
- **Gateways and routers:** OmniRoute 87,201: runner-up. CLIProxyAPI 58,507 and claude-code-router 38,145: no job. cc-switch 154,259: a desktop switcher. axonhub 5,455 and Switchyard 3,524: duplicates. weave-os/router 5,621: a prompt router.
- **Local models, no workload:** ollama 186,903; llmfit 38,979; whichllm 6,835; unsloth 79,463; ktransformers 19,669; TensorFold 2,080; magnitude 7,794; llm-d 5,253; LMCache 12,358; spark-vllm-docker 2,493; LiteRT-LM 6,877; gallery 25,292; Model-Optimizer 5,603; opencompass 7,595; VLMEvalKit 4,490.
- **Toolchain:** astral-sh/ty 20,085: beta, not used (pyright stays). NVIDIA/OpenShell 21,590: runner-up for a sandbox.
- **Desktop and shell, no job:** ohmyzsh 190,607; PowerToys 140,960; Mole 74,945; warp 66,007; omarchy 46,955; superfile 24,081.

## The DeepSeek Harness plugin list (awesome-dsh-plugin), ranked

From the lead's ranked pass over list head `155f3cee4ac4089b576837a10ffa3c93785c583f` (2026-11-13T23:20:10Z), live GraphQL star data of 2026-11-14 04:15 to 04:30 UTC. Research notes. The official LSP packages were then checked at source here, as above. No community plugin is installed: none meets the bar on its own stars, loads on 0.2.2-rc.1, and does a job not already held.

**Distribution:**
- 10,974 entries in 23 sections, pointing at 10,576 distinct repositories; 1,101 entries are sub-folders.
- 10,473 resolved; 103 repositories (104 entries) are gone; 65 archived, 91 forks, 74 moved.
- Median 1 star, p90 12, p99 517; 3,997 have 0 stars and 288 at least 100.
- 61 repositories have at least 1,000 stars (60 pushed since 2026-09-14 and not archived, 68 entries); 26 at least 5,000 (32 entries); 7 at least 20,000.
- Of the 26 at 5,000 or more:
  - 11 are host repositories with a small dsh folder;
  - 3 are multi-agent products (billion-context, treg, answer-me-with-html);
  - 12 are dsh-specific, of which only dsh-TUI, dsh-context and dsh-ops touch a coding worker's jobs.

**Shortlist:**

| Job | Pick | Stars | Supports 0.2.2-rc.1 | Verdict and reason |
|---|---|---|---|---|
| Terminal UI | `ccch1mneyyy/dsh-TUI` 0.20.0 | 7,680 own | yes | already installed at its latest release; kept |
| Code navigation | official `dsh-lsp`, `dsh-tool-lsp`, `dsh-lsp-stdio` 0.2.2-rc.1 | official | yes | **installed** (this ADR); serena runner-up |
| Context compression | `billion-context` 0.1.213 | 7,268 own | yes | deferred: updates itself, replaces built-in compaction |
| Context and usage view | `bowenliang123/dsh-context` 0.84.1 | 5,068 own | yes | no: Web panels, for a TUI and headless worker |
| Destructive-command and secret guard | `kenryu42/cc-safety-net` 2.7.12 | 2,026 own | yes | deferred: below 5,000, and optional security work |
| Memory | `vectorize-io/hindsight` coding-agents 0.8.7 | host 60,919 | yes | no: Hindsight Cloud by default (history leaves the machine), no adoption of its own |
| Planning and spec | `Q00/ouroboros` dsh-plugin | host 6,361 | no peers, not on npm | no: 36 MCP tools, needs a model key; plan mode and goals hold the job |
| Cross-model delegation | official `dsh-subagent-codex` 0.2.2-rc.1 | official | yes | deferred: measure as in ADR 0009 |
| Session search | official `dsh-experimental-session-search` 0.2.2-rc.1 | official | yes | deferred: experimental |
| Browser | `Tencent/BrowserSkill` dsh plugin 0.5.0 | host 10,385 | yes | no: needs a browser extension; no browser job |
| Sub-agent teams | `NanmiCoder/dsh-agent-teams` 0.1.30 | 2,927 own | yes | no: built-in sub-agents and official Agent Teams |
| Web research | `DDDMUC/dsh-free-search` 0.9.48 | 1,129 own | yes | no: built-in web search |

No entry meets the bar for some jobs:
- verification: oh-my-agent (host 1,461) is refused on rc.1; dsh-confirm-gate has 101;
- review: brooks-lint 1,573, a skill pack;
- testing: superpowers-dsh 163;
- Git: Web panels;
- docs lookup: SpecFusion 77;
- cost: dsh-cost-meter 688, Web only;
- notifications: dsh-im 3,576 is an IM bridge;
- sandboxing: mirage is refused on rc.1;
- rtk rewriters: the largest has 18 stars.

**Top five per section** (stars, last push; all pushed since 2026-09-14, none archived; "host" means the host repository's stars):

| Section | Top five and verdict |
|---|---|
| AGI Architecture | clearai-dsh 696 (11-08), no measured gain; dsh-memory 672 (11-14); dsh-soul 85 (11-08); dsh-pua 72 (11-12); dsh-engram 70 (11-13). None meets the bar |
| UI Enhancements | dsh-web task-board and web-all, collection 10,408 (11-13), Web; dsh-TUI 7,680 (11-14), installed; Balance-Whale-Widget 7,203 (10-11), Web; DSH-better-sidebar 5,143 (11-14), refused on rc.1 |
| Usage and Billing | dsh-context 5,068 (11-13), Web; dsh-cost-meter 688 (11-10), Web; dsh-damage-pulse 290 (11-13); TokenLedger 205 (09-15); dsh-usage-stats 188 (11-13). agentsview stays |
| Themes and Appearance | dsh-wallpaper-engine 6,804; dsh-deep-whale 3,104; dsh-claude-style 596; open-sea-skin 393; dsh-liang-skin 387. Cosmetic |
| Models and Providers | dsh-our-free-model 73,064 (11-13), third-party account channels, no; dsh-connect-workbuddy 1,559; dsh-model-router 962; dsh-plugin-subscriptions 603; dsh-xdpool 517. Not a worker job |
| Identity and Communication | dsh-purge 7,987 (11-13), prompt and host-policy patches, no; dsh-aurabot-qq 623; EduWork dsh-oidc host 354; workdsh enterprise-connection 332; dsh-feiyu-mood 264 |
| Sessions and Messages | billion-context 7,268 (11-14), deferred; dsh-infinite-gen 4,234, an unconditional-compliance prompt, no; dsh-synapse 714, Web; dsh-archive-manager 353, Web; dsh-chat-import 310 |
| Memory | hindsight host 60,919; OpenViking host 42,210, needs its server; MemOS host 12,393, npm latest refused; ReMe host 3,799; memsearch host 2,873. All hosts |
| Tools and Capabilities | WeKnora host 37,403, needs its server; next-ai-draw-io host 36,932; treg 7,930, paid tool catalogue, no; dsh-ops 5,798, replaces built-in file tools, no; dsh-blender-plugin 2,083 |
| WSL and Windows Interop | dsh-wsl-workspace 119; dsh-wsl 13; dsh-win-toolkit 4; dsh-wsl-native 4; dsh-wsl-env 3. None |
| Browser and Web | BrowserSkill host 10,385; dsh-free-search 1,129; dsh-browser 1,060, not on npm; modsearch 981; dsh-ego-browser 503 |
| Vision and Multimodal | modlens 4,961; dsh-vision-router 1,268; dsh-vision-toolkit 945; dsh-see-now 633; dsh-video-storyboard 536. Not a worker job |
| Voice and Audio | dsh-tts-bridge 254; dsh-voice-prompt-enhancer 127; xiaomi-mimo-tts 58; dsh-plugin-tts 57; voice-ai-girlfriend 55. None |
| Docs and Rendering | archify host 96,249, a diagram skill; dsh-univer-office 717; dsh-marktext 604; EduWork knowledge-studio host 354; dsh-industry-research 219 |
| Skills | Mole host 74,947, disk cleanup; dsh-web skill-explorer 10,408, Web; answer-me-with-html 6,309; skillhub host 5,419, Web registry; brooks-lint 1,573, overlaps the chosen skills |
| Workflow and Automation | LoopX host 6,583, refused and not on npm; ouroboros host 6,361; dashi-taskboard host 3,485, Web; dsh-agent-teams 2,927; AI-Novel-Writer host 2,622 |
| Git and Code Review | dsh-web git-graph 10,408, Web; codex-guard host 132; dsh-git-panel 51; clutch-dsh-worktree 46; DSH_VsCodeMode 31. None |
| Notifications and Integrations | dsh-im 3,576; dsh-pocket 2,955, phone remote; openpets host 1,399; dsh-bili-scroll 1,394; Avernet host 602. None |
| Development and Runtime | dsh-routing-suite 7,021, runtime injector not on npm, no; mirage host 3,785, refused; oh-my-agent host 1,461, refused; dsh-skills-manager 562, Web; dsh-skill-mcp-panel 277, Web |
| Security and Permissions | cc-safety-net 2,026, deferred; helm-d host 1,266; api-relay-audit 914; dsh-redteam-model 877; dsh-auto-review 248 (an official one exists) |
| Remote and Mobile | dsh-web remote-web-ui and ssh 10,408; ds-harness-remote 2,827; dsh-mobile 852; dsh-uumit-remote 522. Remote access, no |
| Plugin Markets and Managers | dsh-market 12,330, Web; dsh-web plugin-manager 10,408; dsh-plugin-shop 664; dsh-skin-market 329; dsh-find-plugin 232. The `dsh plugin` CLI covers it |
| Just for Fun | dsh-pet 6,238; dsh-tavern 1,606; dsh-bili-whale 1,042; dsh-ads 722; dsh-meme 566. No |

**Official optional packages** (from the installed `dsh-official-bundles`; all on npm at 0.2.2-rc.1):

| Package (`@deepseek-ai/…`) | List | Experimental | Adds | For a coding worker |
|---|---|---|---|---|
| `dsh-experimental-session-search` | optional, off | yes | 5 read-only tools over earlier sessions | deferred |
| `dsh-experimental-terminal-bundle` | optional, hidden | no | 6 persistent-terminal tools | overlaps background jobs |
| `dsh-experimental-ralph-bundle` | optional | yes | repeated work with fresh agents | overlaps the workflow tool |
| `dsh-experimental-agent-team-profile` | optional | yes | Agent Teams; turns ordinary delegation off | no |
| `dsh-experimental-auto-review` | optional | yes | per-tool LLM permission review | optional security work |
| `dsh-experimental-tool-worktree` | optional, hidden | yes | creates and enters a git worktree | no: Orca owns worktrees |
| `dsh-experimental-forge-bundle`, `-inspector-profile`, `-plugin-market-bundle` | optional | yes | change requests, session-log inspection, plugin discovery | Web only |
| `dsh-personalized-recommendations`, `-badge-skill-bundle`, `-session-titles-bundle`, `-voice-input-bundle`, `-cot-translation-bundle`, `-liveshare` | optional | yes | recommendations, badge, titles, voice, translation, sharing | no |
| `dsh-subagent-codex`, `dsh-subagent-claude-code` | on demand | no | delegate one task to Codex or Claude Code with its own login | deferred to a measurement |
| `dsh-cua-bundle` | on demand | yes | macOS Computer Use | no |
| `dsh-lsp`, `dsh-tool-lsp`, `dsh-lsp-stdio` | in no list | – | the LSP seam, one `lsp` tool, a stdio provider | **installed** |
