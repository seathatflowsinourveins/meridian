# ADR 0018: Codex worker stack (stack ADR)
**Status: adopted on the owner's instruction.** Decided 2026-11-13 (plan `can-you-enhanced-codex-eventual-raccoon`; admitted by upstream quality, no with-and-without run per item).

**Need:** Codex becomes a full worker runtime for the lead. Until now it ran bare: no plugin, no MCP server, no skills beyond Orca's two and its own five, no hooks but Orca's nine.

**Components, advisories, what each installs and sends, install and removal (sections 2 to 4 and 8):** one row per component in [data/0018-stack.md](data/0018-stack.md), with the pins `deploy/wsl/setup.sh codex` installs and `agents-check` verifies.

**Always-on context (measured once, by the lead on the machine; the M1 method of [ab-codex.md](data/ab-codex.md)):** before the stack `ALWAYS_ON_BEFORE` tokens, after it `ALWAYS_ON_AFTER` tokens. ADR 0008 measured oh-my-codex alone at +7,611 to +8,075.

**Selection:** one maintained, leading upstream per job.
- `Yeachan-Heo/oh-my-codex` 0.22.6 for workflows (plans, long goals, review, verification), user scope, no MCP, team mode and prompt triage off.
- `DietrichGebert/ponytail` 5.3.3 at its release commit, as a Codex plugin from a local marketplace.
- OpenAI's documentation server, `openaiDeveloperDocs`, as the one MCP server; `kenn-io/agentsview` reads `~/.codex/sessions/`, so it is Codex's cost report too.
- serena and three single skill folders follow the DeepSeek Harness stack (ADR 0016). Deferred, refused and no-pick items, with reasons and triggers, are in the data file.

**Decision:** adopted. `/etc/codex/requirements.toml` names every MCP server allowed and pins ChatGPT apps off, and `check_codex` fails on an unnamed server or plugin: no order tool or broker connector reaches Codex. Supersedes ADR 0008 ([revisit](data/0008-revisits.md)); ADR 0007's decision stands ([revisit](data/0007-revisits.md)).
