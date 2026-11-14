# Architecture decision records

One ADR per addition to an agent runtime's ecosystem, or per stack admitted by selection
(plan 8.6; below), and per memory or retrieval layer (plan 8.7): the evidence for adding it,
or for not adding it. A decision that is not an addition goes in `docs/HANDBOOK.md` instead.

## Format

- File `docs/adr/NNNN-short-title.md`: the next free four-digit number, then a title in
  lowercase words joined by hyphens. Data and scripts the ADR measures with go in
  `docs/adr/data/`, named with the same number. A method sheet shared by several ADRs goes
  there too, named `ab-<what it covers>.md` and linked from each ADR that uses it.
- **At most 60 lines.** `tests/test_size_budget.py` checks the length, the name, that no two
  ADRs share a number, and that each ADR has a row in the index table below.
- First lines: `# ADR NNNN: title`, then its status (proposed, adopted, not adopted, deferred,
  or superseded by NNNN) with the date it was decided.

It covers, in this order (plan 8.6), under these headings or plainer ones:

1. **Need**: what the work lacks without it. A memory or retrieval ADR (plan 8.7) also gives
   the prior evidence for or against such layers.
2. **Candidate**: upstream URL, version or commit, licence, maintainer.
3. **Advisories**: the advisories page that was checked, with its date, and what it lists.
4. **What it installs**: exactly what goes on the machine or into the repo: hooks, MCP
   servers, files, settings it writes, anything it sends.
5. **Always-on context**: what every session loads because of it, measured before and after.
6. **With and without**: one real task done both ways, and what was measured (a method fixed
   before the run, and its results).
7. **Decision**: one of the status words above, and why.
8. **Install and removal**: the pinned install command, and the command that removes it
   completely.

An ADR that adds something also adds its row to `UPSTREAM.md`, in the same commit.

A stack ADR (the owner's decision, 2026-11-13) covers several additions to one runtime, one
maintained, leading upstream per job, admitted on upstream quality without a with-and-without
run per item. Its section 6 is **Selection**; sections 2 to 4 and 8 are one row per component
in `data/NNNN-stack.md`; section 5 is measured once for the whole stack.

Revisits append a dated kept/replaced/re-measured line in `data/NNNN-revisits.md`, then
update this index; never silently edit prior evidence. Dates check the Decision prerequisites.

## Index

Numbers 0001 to 0013 are taken by work in progress: 0001 for the retrieval layer (plan 8.7)
and 0002 to 0013 for the first candidates of plan 8.6. Each ADR's pull request adds its row to
this table; the row's first cell links the file by name, as in `[NNNN](NNNN-short-title.md)`.

| ADR | Title | Status | Last checked | Revisit |
|---|---|---|---|---|
| [0001](0001-semble-code-search.md) | semble for code search (plan 8.7, retrieval slot 2) | not adopted, 2026-11-12 | 2026-11-12 | 2027-02-10 |
| [0002](0002-claude-pyright-lsp.md) | pyright-lsp for Claude Code (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0003](0003-trailofbits-property-testing-supply-chain.md) | Trail of Bits property-based-testing and supply-chain-risk-auditor for Claude Code (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0004](0004-mattpocock-tdd-diagnosing-bugs.md) | mattpocock/skills tdd and diagnosing-bugs (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0005](0005-claude-code-superpowers.md) | obra/superpowers for Claude Code (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0006](0006-claude-compound-engineering.md) | compound-engineering plugin for Claude Code (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0007](0007-codex-openai-plugins.md) | openai/plugins, the official Codex plugins (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0008](0008-codex-oh-my-codex.md) | oh-my-codex for Codex CLI (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0009](0009-dsh-codex-peer.md) | dsh-codex-peer, Codex as a peer of DeepSeek Harness (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0010](0010-dsh-gungnir.md) | dsh-gungnir goal verification for DeepSeek Harness (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0011](0011-dsh-goalloop-agentteams.md) | dsh-goalloop-agentteams completion gate for DeepSeek Harness (plan 8.6) | deferred, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0012](0012-dsh-early-stop-guard.md) | dsh-early-stop-guard for DeepSeek Harness (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0013](0013-antigravity-cli-reading.md) | Antigravity CLI documentation reading (plan 8.6) | not adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0014](0014-claude-you-should-know.md) | You should know for Claude Code (plan 8.6) | adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0015](0015-claude-hud.md) | claude-hud status line for Claude Code (plan 8.6) | adopted, 2026-11-13 | 2026-11-13 | 2027-02-11 |
| [0019](0019-claude-omc-stack.md) | Claude lifecycle stack | adopted by selection, 2026-11-13 | 2026-11-14 | 2027-02-12 |
