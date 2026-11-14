# ADR 0016: DeepSeek Harness worker stack (stack ADR)
**Status: adopted.** Decided 2026-11-13 by the owner (full worker, admitted by upstream quality).

**Need:** dsh became a full worker on 2026-11-13. Until now it had no code navigation (no LSP), no skills beyond Orca's two, no structural search, no usage report and no check before "done".

**Components, advisories, what each installs and sends, install and removal (sections 2 to 4 and 8):** one row per component in [data/0016-stack.md](data/0016-stack.md), with the pins `deploy/wsl/setup.sh dsh` installs and `agents-check` verifies.

**Always-on context (measured once):** dsh's first request in a scratch dsh home with no key and no network (the capture route of [ab-dsh.md](data/ab-dsh.md)) grows from 7,296 to 7,891 o200k tokens (+595). The `lsp` tool adds 170, the eight skills' list 365 and the system text 60. Three runs per arm gave identical bodies. Method and figures are in the data file.

**Selection:** one maintained, leading upstream per job; the official package first.
- Eight skill folders from addyosmani/agent-skills, obra/superpowers and mattpocock/skills, each at its latest release's commit, every file read at the pin.
- DeepSeek's own `dsh-lsp` packages for code navigation, with `oraios/serena` as the runner-up.
- `ast-grep` for structural search; `agentsview` for token and cost reports (it reads `~/.dsh/sessions/`).
- A completion gate of own design on a second mount of the hook bridge.

Every starred repository in the agent groups, the plugin-list pass, the refused and deferred items and the jobs left to built-ins are in the data file.

**Decision:** adopted.
- The gate ships: a second mount of `@deepseek-ai/dsh-hooks-claude-code` ran beside the first in one dsh process, and its block forced one more turn.
- `skill-creator` is refused: its scripts start `claude -p` (sending skill text and queries to Anthropic), its viewer kills whatever process listens on its port, and its page loads a script from a CDN.
- serena is not installed: the official `lsp` tool answered a definition query on the worktree's own pyright at 170 tokens, against 2,927 for serena.

The stack loads in the `dsh-tui` profile, which Orca launches. The headless line keeps exit-code grading, and another model family still reviews dsh's work.
