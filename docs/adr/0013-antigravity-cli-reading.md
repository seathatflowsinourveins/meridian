# ADR 0013: Antigravity CLI documentation reading (plan 8.6)

**Status: not adopted, 2026-11-13.** This ADR covers five additions from one source, as plan 8.6's candidate list names it (line 183: read Antigravity's official CLI documentation before adding anything), and decides each separately: plugins, MCP servers, hooks, Google's bundles, and a `GEMINI.md` or rule file. Nothing was measured: no with/without task was run for any of them, and each was decided on the documentation reading, which an independent check on 2026-11-12 (83 checks: 74 confirmed, 9 corrected, 0 refuted) agreed with. Figures and sources: [results](data/0013-results.json); the always-on text figures are rebuilt by [`0013_always_on.py`](data/0013_always_on.py) with the [counter](data/0013_count_tokens.py).

## Candidate

`agy` **1.5.7** by Google, the newest of 88 releases at the read on 2026-11-12 (the first on 2026-06-01). Release repository [google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli): changelog, README and examples, no source. Tag `1.5.7` (lightweight) = `87bd97327a72d62d553c3aede8cf77752ae4c59a`, a commit that only edits `CHANGELOG.md`. Documentation: https://antigravity.google/docs, unversioned, each page also served as `.md` (index `/llms.txt`, 102 pages, searched 2026-11-12). No licence (GitHub: null, no LICENSE file): a proprietary binary under Google's Terms of Service, the [Antigravity Additional Terms](https://antigravity.google/terms) and the Privacy Policy (README lines 75-85). Maintainer: the organisation `google-antigravity` (not verified by GitHub, 2 public repositories); 921 open issues and 25 open pull requests on 2026-11-12.

## Decision

Not adopted: add nothing to agy. Each addition, decided on the reading:
- Plugins (the marketplace, `agy plugin import`, the built-in `migrate-agent-settings` and `plugin` skills): no version pin, and `agents-check` fails on a plugins folder under `~/.gemini/config` or `.agents`.
- MCP servers: `agents-check` fails once `mcp_config.json` names a server or `.agents/mcp_config.json` exists, and the reading names no need one would fill.
- Hooks: `agents-check` fails on `.agents/hooks.json`, and the reading names no need one would fill.
- Google's bundles: documented for the Antigravity App, and they meet no need here.
- A `GEMINI.md` or `.agents/rules/` file: rules add up, so it would only repeat `AGENTS.md`.

Overlap, as fact: agy's `/swarm`, `/teamwork`, `/boost`, `/schedule`, subagents, Remote Control and `swarm` plugin need nothing installed and do part of what Orca does here (worker orchestration, automations, driving sessions). Already on `main`: `check_agy` (`deploy/wsl/setup.sh` lines 587-612) accepts agy's empty `mcp_config.json` only while it names no server and fails on `.agents/{mcp_config.json,plugins,hooks.json}` in any worktree; `tests/test_agent_config.py` fails on any file git lists under `.agents/` (skills apart) or `.gemini/`. Not covered by either: the global rule and skill folders under `~/.gemini`, the other `~/.gemini/config/*.json` files, and `.agent/`, `_agents/`, `_agent/` and `GEMINI.md` in a worktree.

Full record: [data/0013-record.md](data/0013-record.md)
