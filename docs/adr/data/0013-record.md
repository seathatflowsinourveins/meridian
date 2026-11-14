# ADR 0013: Antigravity CLI documentation reading (plan 8.6)

**Status: not adopted, 2026-11-13.** This ADR covers five additions from one source, as plan 8.6's candidate list names it (line 183: read Antigravity's official CLI documentation before adding anything), and decides each separately: plugins, MCP servers, hooks, Google's bundles, and a `GEMINI.md` or rule file. Nothing was measured: no with/without task was run for any of them, and each was decided on the documentation reading, which an independent check on 2026-11-12 (83 checks: 74 confirmed, 9 corrected, 0 refuted) agreed with. Figures and sources: [results](0013-results.json); the always-on text figures are rebuilt by [`0013_always_on.py`](0013_always_on.py) with the [counter](0013_count_tokens.py).

## Need

Plan 8.6 adds nothing to Antigravity before a reading of its official CLI documentation: what agy loads by itself (non-interactive mode, `AGENTS.md`, extensions) and whether an official extension fills a need here. Already in place: the shared `AGENTS.md`, Orca's two skills in `.agents/skills`, and Orca, which launches agy.

## Candidate

`agy` **1.5.7** by Google, the newest of 88 releases at the read on 2026-11-12 (the first on 2026-06-01). Release repository [google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli): changelog, README and examples, no source. Tag `1.5.7` (lightweight) = `87bd97327a72d62d553c3aede8cf77752ae4c59a`, a commit that only edits `CHANGELOG.md`. Documentation: https://antigravity.google/docs, unversioned, each page also served as `.md` (index `/llms.txt`, 102 pages, searched 2026-11-12). No licence (GitHub: null, no LICENSE file): a proprietary binary under Google's Terms of Service, the [Antigravity Additional Terms](https://antigravity.google/terms) and the Privacy Policy (README lines 75-85). Maintainer: the organisation `google-antigravity` (not verified by GitHub, 2 public repositories); 921 open issues and 25 open pull requests on 2026-11-12.

Tags are not fixed points: 64 of 89 tags point at commits dated after their release was published (56 by 10 s or less, `1.5.7` by 3 s; 7 by 2.6 to 27.5 minutes; `1.5.2` by 22.4 hours), and none of the 89 releases is immutable (counted 2026-11-13). The pin is the asset's sha256, and only for the first install: agy updates itself from Google's manifest (builds on `storage.googleapis.com`, SHA-512), and `setup.sh agents-check` accepts 1.5.7 or newer.

Since the read (GitHub releases API, 2026-11-13): `1.5.8`, published 2026-11-13T05:00:42Z, tag `1554cf9fc71ddbcd9e0d176c8f65000612bba3c2`, asset sha256 `905d4acc…ab98`; 89 releases, 25 since 2026-10-13. Its notes fix path-based network rules of the terminal sandbox's proxy bypassed with `%2F`, backslashes or `..`, always-allow rules that Windows shells could bypass, and permission rules ignored for eager MCP tools (release body lines 6-8). Re-pinning agy is a `setup.sh` and `UPSTREAM.md` Agent runtimes change, outside this ADR; the installed binary was the 1.5.7 build (sha256 `5df525a2…4642`) on 2026-11-13.

## Advisories (GitHub, OSV, NVD; 2026-11-12, repository again 2026-11-13)

None. Repository advisories: `[]`. GitHub's advisory database: 0 for npm `agy`, `antigravity-cli`, `@google/antigravity`, `@google/antigravity-cli`, `antigravity`; pip `google-antigravity`, `antigravity`; Go `github.com/google-antigravity/antigravity-cli`. OSV: 0. NVD, keyword `antigravity`: 0. agy is on none of those registries (the npm names are unrelated placeholders or do not exist; PyPI `google-antigravity` is Google's Apache-2.0 SDK), so no feed covers it: Google discloses security fixes only as changelog lines (1.5.2, 1.5.3, 1.5.7, 1.5.8).

## What it installs, writes and sends

This ADR installs nothing. What agy 1.5.7 does by itself, from its documentation and from the distro after the owner's sign-in on 2026-11-12:
- Instructions: the whole `AGENTS.md` (or `GEMINI.md`, `.agents/{AGENTS,GEMINI}.md`, `.agents/rules/*.md`) from the start folder up to the repository root, in the system prompt on every turn (`rules.md` 17-23, 40, 83). Rules add up; 24,000 bytes per file, a 20,000-token budget (146-147). `CLAUDE.md` is named on none of the 102 pages. Skills: the name and description of each `.agents/skills/<name>/SKILL.md` on every turn (`skills.md` 15, 129-135). `.agent/`, `_agents/` and `_agent/` are read like `.agents/` (`customization-discovery.md`).
- `/learn` writes, once the user approves its proposal, a rule to the workspace or global `AGENTS.md`, `GEMINI.md` or rules folder, or a skill to `.agents/skills/` or `~/.gemini/config/skills/` (`commands/learn.md` 16, 55, 59-64). In 1.5.7 it could append to such a file past the rule size limit, after which the file's end was cut off on every turn (1.5.8 release body, line 21); here that file is the `AGENTS.md` all four runtimes share.
- Extensions: Gemini CLI extensions and Claude Code plugins convert to agy plugins (`agy plugin import`); plugins install as `agy plugin install <p>@antigravity-plugins-official`, with no version pin (`plugins.md`); MCP servers come from `~/.gemini/config/mcp_config.json` and `.agents/mcp_config.json` (`mcp.md` 61-64), hooks from `~/.gemini/config/hooks.json` and `.agents/hooks.json`. Google's ten bundles are documented for the Antigravity App (`build-with-google.md`); its MCP list includes finance-data and payment servers (`mcp.md` 464-490).
- Built in: 14 skills, and a plugin `swarm` (a Node sidecar with a web UI) that agy enabled in `~/.gemini/config/config.json` at its first full start, when it also wrote an empty `~/.gemini/config/mcp_config.json`. `/goal` is built in; what it does is in the Goals section of `docs/HANDBOOK.md` on `m2/handbook-size-budget`.
- Non-interactive: `agy -p "<prompt>" --output-format json` (or `stream-json`) reports input, output, thinking, cache-read and total tokens (`cli/headless.md` 67-73, 294-295). An approval it cannot get is denied and the run still exits 0 (454). `--dangerously-skip-permissions`, Orca's default, approves every call except deny rules and built-in protected commands (changelog, 1.5.2).
- Writes its state under `~/.gemini/antigravity-cli` (a credential file, not read; conversations, logs, the updater) and `~/.gemini/config`. Sends: Google sign-in, model and quota calls; telemetry unless switched off (an account setting no local file shows); a background self-updater, off with `AGY_CLI_DISABLE_AUTO_UPDATE=true`, which Orca 1.4.257 (`b0570d90`) sets for its TUI launches (`tui-agent-launch-command.ts` line 39). Orca also adds hooks on 5 events that inject no text and runs `agy -p /usage`, `agy --version` and `agy acp` itself.
- Terms: the Additional Terms count use of the Service "in connection with products not provided by us" as abuse and call third-party software that accesses it a breach; the FAQ calls wrapping agy in third-party coding agents or applications unsupported on consumer plans (`faq.md` 335-341). Both bear on Orca's `agy acp` chat host.

## Always-on context

- Added by this ADR: nothing, so before and after are the same.
- From this repository on `main` `9c5daaa`: `AGENTS.md`, 8,318 characters (2,159 tokens), plus Orca's two skill lines, 1,672 characters (395 tokens): 9,990 characters (2,554 tokens) together. At the reading (`f65d835`), `AGENTS.md` was 5,964 characters (1,516 tokens).
- agy's own: its built-in skill listing, at most 4,700 characters (998 tokens); which of the 14 reach the model is unverified. Its system prompt and tools are not published; the documentation's headless example spends 10,415 input tokens on a one-sentence answer (`cli/headless.md` 67-73). agy's own token count was not measured.
- Tokens are counted with o200k_base, OpenAI's vocabulary (sha256 `446a9538…1a2d`), as a proxy, because agy's tokenizer is not available offline; skill lines are written `- <name>: <description>`, since agy's framing is unpublished.

## With and without

Not run: no addition was taken up, so there is no task to run both ways, and no run of any kind was made. Whether agy does as well with the shared `AGENTS.md` and `.agents/skills` as without them was not measured; they are documented to load (`rules.md`, `skills.md`), not observed.

## Decision

Not adopted: add nothing to agy. Each addition, decided on the reading:
- Plugins (the marketplace, `agy plugin import`, the built-in `migrate-agent-settings` and `plugin` skills): no version pin, and `agents-check` fails on a plugins folder under `~/.gemini/config` or `.agents`.
- MCP servers: `agents-check` fails once `mcp_config.json` names a server or `.agents/mcp_config.json` exists, and the reading names no need one would fill.
- Hooks: `agents-check` fails on `.agents/hooks.json`, and the reading names no need one would fill.
- Google's bundles: documented for the Antigravity App, and they meet no need here.
- A `GEMINI.md` or `.agents/rules/` file: rules add up, so it would only repeat `AGENTS.md`.

Overlap, as fact: agy's `/swarm`, `/teamwork`, `/boost`, `/schedule`, subagents, Remote Control and `swarm` plugin need nothing installed and do part of what Orca does here (worker orchestration, automations, driving sessions). Already on `main`: `check_agy` (`deploy/wsl/setup.sh` lines 587-612) accepts agy's empty `mcp_config.json` only while it names no server and fails on `.agents/{mcp_config.json,plugins,hooks.json}` in any worktree; `tests/test_agent_config.py` fails on any file git lists under `.agents/` (skills apart) or `.gemini/`. Not covered by either: the global rule and skill folders under `~/.gemini`, the other `~/.gemini/config/*.json` files, and `.agent/`, `_agents/`, `_agent/` and `GEMINI.md` in a worktree.

## Commands

- Install: none. agy stays as `deploy/wsl/setup.sh` pins it (lines 103-105): the GitHub asset `agy_cli_linux_x64.tar.gz` of `1.5.7`, sha256 `d6150a8d2a9e29a3d171b2325d6f66b6e7059628f4799a20c069b8ed8f78fdbb`. Google documents only the unpinned `curl -fsSL https://antigravity.google/cli/install.sh | bash`.
- Removal: none. A later plugin would go with `agy plugin uninstall <name>`. No uninstall is documented for the binary; agy's state lives in `~/.gemini/antigravity-cli` and `~/.gemini/config` (archive owner data before deleting).
