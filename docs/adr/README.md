# Architecture decision records

One ADR per addition to an agent runtime's ecosystem (plan 8.6) and per memory or retrieval
layer (plan 8.7): the evidence for adding it, or for not adding it. A decision that is not an
addition goes in `docs/HANDBOOK.md` instead.

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

## Index

Numbers 0001 to 0013 are taken by work in progress: 0001 for the retrieval layer (plan 8.7)
and 0002 to 0013 for the first candidates of plan 8.6. Each ADR's pull request adds its row to
this table; the row's first cell links the file by name, as in `[NNNN](NNNN-short-title.md)`.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-semble-code-search.md) | semble for code search (plan 8.7, retrieval slot 2) | not adopted, 2026-11-12 |
