# ADR 0018 data: the Codex worker stack

Read 2026-11-13 (ET; 2026-11-14 UTC) in the `meridian` distro, Codex CLI 0.167.2 (`rust-v0.167.2` = `ce21072c90d32c40af7a55b60b2fb35c84a43a6a`). Stars and last push are `gh api repos/<repo>` values at that time. Advisories are each repository's published GitHub security advisories (`gh api repos/<repo>/security-advisories`) and, for npm packages, GitHub's advisory database (`gh api '/advisories?ecosystem=npm&affects=<package>'`).

## Components (sections 2 to 4 and 8)

| Component | Upstream, pin | Stars, last push | Advisories | Installs and writes | Sends | Removal |
|---|---|---|---|---|---|---|
| Workflow layer | `Yeachan-Heo/oh-my-codex` 0.22.6, npm integrity `sha512-ZpMHipwnaiHV/T8rp/czmF5U+ugqVdUOb28obL5U61q9WQwvfKAmzP4k1V82EnUXYMvsBgZIzFl0I3HADBbFEQ==` (gitHead and tag `v0.22.6` = `610be90863964394fd311b5198e8324bf96157c0`, the newest release and `latest` dist-tag on 2026-11-13), MIT | 33,783; 2026-11-10 | none published for the repository or the npm package; its dependencies' advisories as in ADR 0008 | global npm package in `~/.local` without its postinstall (`--ignore-scripts`: no `omx-runtime` download); `omx setup` (user scope, legacy, `--mcp none`, `--team-mode disabled`) writes into `~/.codex/`: `AGENTS.md`, 22 skills, 31 prompts, 17 agent roles, `hooks.json` entries for 8 events beside Orca's 9, their trust entries, `notify`, `developer_instructions`, `[features] hooks` and `goals`, a `[tui] status_line`, `[shell_environment_policy.set]`, `.omx/`; and `~/.omx/backups/`. The script then writes `~/.codex/.omx-config.json` and the `.omx/` line in the repository's shared `info/exclude` | the hook path fetches nothing (ADR 0008); setup runs `gh auth status`; opt-in notifiers and the `omx` launcher's update check and star prompt are not used (Orca starts `codex`) | `omx uninstall --scope user --dry-run`, then without `--dry-run`; `npm uninstall -g oh-my-codex`; the rest as ADR 0008's Commands |
| Write-less-code plugin | `DietrichGebert/ponytail` v5.3.3, commit `7801d061243d7b753bad0e0b3c057cd250b11755` ("chore: release v5.3.3"), MIT | 190,432; 2026-10-29 | none published | its tree at the commit (no `.git`) in a local marketplace `meridian-ponytail` at `~/.local/share/meridian/codex-market` (the checkout in `~/.local/share/meridian/ponytail-src`); `codex plugin add` copies it into Codex's plugin cache and writes `[plugins."ponytail@meridian-ponytail"]` and `[marketplaces.meridian-ponytail]`. 6 skills, 3 hooks (SessionStart, SubagentStart, UserPromptSubmit), each `node` on a file of the plugin; under Codex they keep a mode flag in the plugin's data folder (`PLUGIN_DATA`) | nothing: no network call in the hook files; the board import that reads transcripts runs only under Claude Code | `codex plugin remove ponytail@meridian-ponytail`, `codex plugin marketplace remove meridian-ponytail`, delete both folders |
| Documentation MCP server | OpenAI's hosted server `https://developers.openai.com/mcp`, named `openaiDeveloperDocs` as Codex's `openai-docs` system skill expects (`references/mcp-diagnostics.md` at `rust-v0.167.2`) | n/a | n/a | `[mcp_servers.openaiDeveloperDocs] url = …` in `config.toml`; its name and URL in `/etc/codex/requirements.toml` | the model's documentation queries, to developers.openai.com; no key | delete the table and its requirements entry |
| Cost report | `kenn-io/agentsview` v0.47.0 (tag `8135fed8bf826cde94b1de5e9ff58e51bc7eab5d`), installed by the DeepSeek Harness stack (ADR 0016) | 6,436; 2026-11-14 | none published | nothing more: its README at v0.47.0 lists Codex's source as `~/.codex/sessions/` and `agentsview report usage` covers all agents (`--agent` filters) | prices from LiteLLM and OpenRouter rates when it computes cost (README) | as ADR 0016 |
| Code intelligence | `oraios/serena` | 31,368; 2026-11-09 | 3 published | follows the DeepSeek Harness stack: not in `setup.sh` here | n/a | n/a |
| Skills `test-driven-development`, `systematic-debugging`, `verification-before-completion` | `obra/superpowers` v7.0.2, commit `22f0b463e7a5e579904dd6211a520321035526f7`, the DeepSeek Harness stack's checkout | 317,295; 2026-11-03 | none published | follows the DeepSeek Harness stack: to be copied to `~/.codex/skills/` | nothing | delete the three folders |

`source-driven-development` (`addyosmani/agent-skills`) is left out: oh-my-codex's `best-practice-research` skill holds its job at the pin (official and upstream evidence before deciding). oh-my-codex has no test-driven skill, and for debugging and verification only roles (`debugger`, `verifier`), not skills, so the three above stay.

Install: `deploy/wsl/setup.sh codex-requirements`, then `deploy/wsl/setup.sh codex`, then `deploy/wsl/setup.sh agents-check`, from `~/src/meridian` with no Codex worker running. The owner's one step: open `codex`, run `/hooks`, trust ponytail's three hooks. `check_codex` fails on any of these:
- `config.toml`: a setting above differs, `[features] apps` is not false or `plugins` not true, an MCP server other than `openaiDeveloperDocs` or with another URL, an enabled plugin other than `ponytail@meridian-ponytail`, a profile that sets features, MCP servers or plugins;
- `hooks.json`: an entry that is neither Orca's (`orca-agent-hook-form`) nor oh-my-codex's, other than 9 and 8 of them, or one without its `[hooks.state]` trust entry (`<hooks.json>:<event>:<group>:<handler>`);
- `.omx-config.json`: team mode or prompt triage not off;
- `/etc/codex/requirements.toml` is not the text in `meridian.user-data`, byte for byte;
- oh-my-codex is not 0.22.6, or `omx doctor` does not print `Results: … 0 failed` (its exit code is 0 whatever it finds).
Ponytail's hooks without trust entries (`ponytail@meridian-ponytail:<file>:<event>:0:0`) are reported as waiting for the owner, not as a failure.

### What was checked at source, and how

- oh-my-codex at `v0.22.6`: `--team-mode` (`src/cli/index.ts` L376, L755); team mode is read from `.omx/setup-scope.json` in the working folder, then `$CODEX_HOME/.omx-config.json` (`src/config/team-mode.ts`); triage from `promptRouting.triage.enabled` in the same file (`src/hooks/triage-config.ts`); doctor's summary line (`src/cli/doctor.ts` L963).
- Its setup keeps an existing `model_reasoning_effort` (`src/config/generator.ts` L68, issue #3630) and writes `"medium"` only where the key is missing; the script sets `high` again after it either way.
- A run of the script's `codex_config` and `cmd_omx` in a throwaway home seeded with this machine's Orca hooks: oh-my-codex placed its 8 hooks after Orca's and trusted them by position, the check passed with `omx doctor` at 18 passed, 1 warning, 0 failed, and a second run left `config.toml` byte-identical.
- Codex at `rust-v0.167.2`: requirements identities compare the command or URL exactly (`codex-rs/config/src/mcp_requirements.rs`); a local marketplace is `.agents/plugins/marketplace.json` with `./`-relative plugin paths and a default policy of "available" (`codex-rs/core-plugins/src/marketplace.rs`); an installed plugin is `[plugins."<name>@<market>"] enabled` (`codex-rs/config/src/plugin_edit.rs`); a plugin's hooks are keyed `<plugin>:<file>` (`codex-rs/hooks/src/declarations.rs`).
- Not run here: `codex plugin add`. This machine's requirements still pin `plugins = false`, so Codex lists no marketplace plugin, even in a throwaway home (`manager.rs` L2474). The marketplace was built and added, and the commit fetched by its SHA. The lead's machine step is the first install.

## Deferred, each with its trigger

| Item | Why not now | Trigger |
|---|---|---|
| `rtk-ai/rtk` (86,520; 2026-11-13) | ADR 0017: its pytest wrapper drops the failing test's node id | a release that keeps it, or 2027-02-11 |
| `alibaba/open-code-review` (50,775; 2026-11-14), a second reviewer | one reviewer family is the rule today | after the first week of automated landings |
| `microsoft/playwright-cli` (15,186; 2026-11-11) and its skills | no page to test | the display milestone has a page |
| `microsoft/markitdown` (195,274; 2026-11-07) | no broker-document corpus | there is one |
| `gastownhall/beads` (28,722; 2026-11-14) | workers do not collide over task state | they do |
| Codex's own `memories` | never two memory layers at once | oh-my-codex's project memory used for a week |
| Codex 0.169 (`--trust` on `exec` and `review`) | the 7-day wait | the release is 7 days old |

## No pick, with the reason

- `DeusData/codebase-memory-mcp`, `GitNexus`, `claude-context`: the same job as serena.
- The whole `obra/superpowers` and `mattpocock/skills` plugins, `VoltAgent/awesome-codex-subagents`: oh-my-codex holds those jobs.
- Context7 and GitHub's MCP server: a hosted index and a second token, where the pinned package, the tagged source and `gh` decide (the verdict recorded for DeepSeek Harness).
- `ccusage/ccusage` (19,429; 2026-11-14): agentsview already reads `~/.codex/sessions/`.
- The catalogue's `github`, `coderabbit`, `circleci`, `codex-security` and `openai-developers` plugins: a new account or key each (ADR 0007 for `codex-security`).
- oh-my-codex's six MCP servers and its team mode: marked legacy upstream; Orca is the fleet.
- Excluded by the boundary: `openai/plugins` `public-equity-investing`, the one catalogue plugin with a broker connector (Alpaca), an app connector; `apps` stays pinned off.

## Always-on context (section 5)

Three `codex exec` "reply OK" runs before the machine step and three after (M1 of [ab-codex.md](ab-codex.md); 16,285 tokens before in ADR 0008): `ALWAYS_ON_BEFORE` and `ALWAYS_ON_AFTER`, measured by the lead on the machine.

## Removal of the whole stack

`omx uninstall --scope user` and `npm uninstall -g oh-my-codex`; `codex plugin remove ponytail@meridian-ponytail` and `codex plugin marketplace remove meridian-ponytail`; delete `~/.local/share/meridian/codex-market`, `ponytail-src` and the `[mcp_servers.openaiDeveloperDocs]` table; write back the previous requirements text (`git show 8ac888b:deploy/wsl/meridian.user-data`) and restore the previous `check_codex` from git.
