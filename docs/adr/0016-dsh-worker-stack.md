# ADR 0016: DeepSeek Harness worker stack (stack ADR)
**Status: adopted.** Decided 2026-11-13 by the owner (full worker, admitted by upstream quality).

**Need:** dsh became a full worker on 2026-11-13. It had no code navigation (no LSP), no skills beyond Orca's two, no structural search, no usage report and no check before "done".

**Components, advisories, installs and sends, install and removal (sections 2 to 4 and 8):** one row per component in [data/0016-stack.md](data/0016-stack.md), with the pins that `deploy/wsl/setup.sh dsh` installs and `agents-check` verifies.

**Always-on context (measured once):** dsh's first request grows from 7,296 to 7,891 o200k tokens (+595), measured with no key and no network on the capture route of [ab-dsh.md](data/ab-dsh.md). Method and parts are in the data file.

**Selection:** one maintained, leading upstream per job, the official package first:
- eight skill folders from addyosmani/agent-skills, obra/superpowers and mattpocock/skills, each at its release commit, every file read;
- DeepSeek's own `dsh-lsp` packages for code navigation (runner-up: `oraios/serena`);
- `ast-grep`, and `agentsview` for token and cost reports;
- a completion gate of own design.

Every starred repository in the agent groups, the plugin-list pass and the deferred items are in the data file.

**Decision:** adopted. The gate ships: a second mount of the hook bridge ran beside the first in one dsh process. `skill-creator` is refused: its scripts start `claude -p` and kill by port. The stack loads in the `dsh-tui` profile Orca launches; another model family still reviews dsh's work.
