# ADR 0004: mattpocock/skills tdd and diagnosing-bugs (plan 8.6)

**Status: not adopted.** Decided 2026-11-13.

## Candidate

[mattpocock/skills](https://github.com/mattpocock/skills) **v1.3.2**: annotated tag `85cbec972d7a79c278c793d272f7fc715850fad4` on commit `d1478fcb140db0b93c0c8df17bcfd311844749d0` (2026-10-29, the newest release; `main` was 5 commits ahead on 2026-11-13 and touched neither folder). MIT. Maintainer: the GitHub user `mattpocock` (Matt Pocock); 130 commits on `main` since 2026-08-14, 217 open issues; no security policy. Only two of its 38 skills, `skills/engineering/tdd` and `skills/engineering/diagnosing-bugs`, copied file by file. Not the plugin route: `mattpocock-skills@claude-plugins-official` brings all 27 plugin skills, takes no version and updates itself, and upstream's own marketplace also brings all 27.

## Decision

Not adopted, each skill on its own measurement. `tdd`: both arms passed R3 0 of 3, and it was invoked in 0 of 3 with-runs. `diagnosing-bugs`: both arms passed R1 3 of 3 at 115.6% of the without arm's median tokens, and it was invoked in 0 of 3 with-runs. The always-on delta, 182, is over the 150 limit for both. Upstream publishes no outcome evidence ("There is no automated eval.", `docs/productivity/writing-for-agents.md` line 47). A later look needs tasks that ask for diagnosis and for test-first work in so many words, the same Orca skills in both arms, and the always-on runs with the copies committed.

Full record: [data/0004-record.md](data/0004-record.md)
