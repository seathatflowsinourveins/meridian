# ADR 0003: Trail of Bits property-based-testing and supply-chain-risk-auditor for Claude Code (plan 8.6)

**Status: not adopted.** Decided 2026-11-13.

## Candidate

[trailofbits/skills](https://github.com/trailofbits/skills/tree/149d7b21f4067765b82e67029730b42d228ef4b4), plugins **property-based-testing 1.2.3** and **supply-chain-risk-auditor 2.0.4**, pinned by commit `149d7b21f4067765b82e67029730b42d228ef4b4` (head of `main`, 2026-11-12; no tags or releases, so a commit is the only exact pin). CC-BY-SA-4.0. Maintainer: Trail of Bits; plugin authors Henrik Brodin and Eric Quintero; 237 commits, 36 open issues and 123 open pull requests on 2026-11-13. Published evidence: supply-chain-risk-auditor about 92% against 60% of assertions on three fixtures, one run each (PR #227); property-based-testing's ablation, 3 runs per arm, Δ0.00 and Δ+0.50, which its README says does not establish better property tests (PR #235). Upstream also gives a Codex install; plan 8.6 lists this candidate under Claude Code, and that route is out of scope here.

## Decision

Not adopted, both plugins. supply-chain-risk-auditor: its arm passed 0 of 3 against 0 of 3, so neither branch of the rule holds and the 32.1% token saving does not count; its always-on delta (+142) was within the limit. In 3 of 3 with-runs it left its output in `/tmp`, and it cannot read the npm set that is the open part of the job. property-based-testing: no with/without task was run for it; its always-on delta, +316, is over the 200-token limit set for these plugins, it lowers the effort to low for the rest of the turn that invokes it, it needs a new dev dependency, and its published ablation does not show better tests.

Full record: [data/0003-record.md](data/0003-record.md)
