# ADR 0016: DeepSeek Harness worker stack (stack ADR)
**Status: adopted.** Decided 2026-11-13 by the owner (full worker, admitted by upstream quality).

**Need:** dsh became a full worker. It had no code navigation, no skills beyond Orca's two, no structural search, no usage report and no check before "done".
**Components, advisories, installs and sends, install and removal (sections 2 to 4 and 8):** one row each in [data/0016-stack.md](data/0016-stack.md); `setup.sh dsh` installs the pins, `agents-check` verifies them.
**Always-on context (measured once):** the first request grows from 7,296 to 7,891 o200k tokens (+595), measured with no key and no network ([ab-dsh.md](data/ab-dsh.md)).
**Selection:** one maintained, leading upstream per job, the official package first: eight skill folders (addyosmani/agent-skills, obra/superpowers, mattpocock/skills), DeepSeek's `dsh-lsp` packages (runner-up: `oraios/serena`), `ast-grep`, `agentsview`, and a completion gate of own design. Every starred repository in the agent groups and the deferred items are in the data file.
**Decision:** adopted. A second hook-bridge mount works, so the gate ships. `skill-creator` is refused: its scripts start `claude -p` and kill by port. The stack loads in both Orca's `dsh-tui` profile and the `headless` profile; another model family still reviews dsh's work.
