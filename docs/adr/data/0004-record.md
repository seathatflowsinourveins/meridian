# ADR 0004: mattpocock/skills tdd and diagnosing-bugs (plan 8.6)

**Status: not adopted.** Decided 2026-11-13.

This ADR covers 2 additions from one source, as plan 8.6's candidate list names it, and decides each separately: `tdd` on task R3 and `diagnosing-bugs` on task R1. Evidence: the assessment (2026-11-12), an independent verification (2026-11-13: 52 checks, 49 confirmed, 3 corrected, 0 refuted; its corrections are used) and the measurement (2026-11-13, 01:58 to 04:45 ET). The assessment and verification notes hold local paths and are not published; the raw runs stay on the owner's machine.

## Need

Writing tests test-first and diagnosing code bugs, both current-milestone work: on 2026-11-12 two reviews found gaps in the paper checks, fixed in `39cb68e` and `5d51c9c`. Overlap: no named tool here does test-first work. For diagnosis, openai/codex-plugin-cc 1.0.6, loaded in every Claude Code session here, adds the agent `codex:codex-rescue` (a "diagnosis pass", a "deeper root-cause investigation") and `/codex:rescue`, which hand a diagnosis to Codex: a partial overlap. Claude Code 2.1.322's bundled `/code-review`, `/simplify` and `/debug` and built-in `/security-review` and `/plan` do neither job (https://code.claude.com/docs/en/commands.md, read 2026-11-13). Not checked: the built-in skills of Codex, Antigravity and DeepSeek Harness.

## Candidate

[mattpocock/skills](https://github.com/mattpocock/skills) **v1.3.2**: annotated tag `85cbec972d7a79c278c793d272f7fc715850fad4` on commit `d1478fcb140db0b93c0c8df17bcfd311844749d0` (2026-10-29, the newest release; `main` was 5 commits ahead on 2026-11-13 and touched neither folder). MIT. Maintainer: the GitHub user `mattpocock` (Matt Pocock); 130 commits on `main` since 2026-08-14, 217 open issues; no security policy. Only two of its 38 skills, `skills/engineering/tdd` and `skills/engineering/diagnosing-bugs`, copied file by file. Not the plugin route: `mattpocock-skills@claude-plugins-official` brings all 27 plugin skills, takes no version and updates itself, and upstream's own marketplace also brings all 27.

## Advisories (GitHub, 2026-11-13)

None: repository advisories `[]`; GitHub's advisory database (npm) has 0 for `skills`, `mattpocock-skills`, `@changesets/cli` and `@changesets/changelog-github`. The copy route installs no package. The npm package `mattpocock-skills` 1.3.0 names this repository but is not upstream's (its `package.json` says `"private": true`): never install it.

## What it installs, writes and sends

- Into the repo: 7 files, byte-identical to the pin ([blob ids](0004-addition-hashes.txt)): `.agents/skills/tdd/` (`SKILL.md`, `tests.md`, `mocking.md`, `agents/openai.yaml`) and `.agents/skills/diagnosing-bugs/` (`SKILL.md`, `agents/openai.yaml`, `scripts/hitl-loop.template.sh`, mode 100644, which nothing runs); links `.claude/skills/<name>`; an MIT section in `.agents/skills/NOTICE.md`; blob pins in `tests/test_skills_layout.py`, whose `files == ["SKILL.md"]` check must first accept multi-file skills.
- Nothing runs: no hooks, servers, commands, agents or network use; no settings change. The install is one unauthenticated `git fetch`. Main's tripwire patterns find 0 hits in the 7 files.
- Listed by every runtime that reads `.agents/skills`: Claude Code through the links, Codex and DeepSeek Harness. The text asks the agent for test files, throwaway harnesses, `[DEBUG-xxxx]` logs and `git bisect`; `tdd` has the agent confirm seams with the user, and `diagnosing-bugs` tells it to stop and ask.

## Always-on context

- Measured: input plus cache tokens of a one-turn `OK` run, 3 runs per arm, each in a fresh worktree at `main` `9c5daaa`, the with arm holding the 7 copies and links uncommitted: without 22,743 in all three, with 22,925 in all three, **+182 (+0.80%)**. A control pair with `includeGitInstructions: false`, 1 run each: 22,020 and 22,141, +121; the other 61 tokens are the git-status lines for the uncommitted copies. `/context`: the Skills row +110 (`tdd` 52, `diagnosing-bugs` 58).
- Static, in o200k_base tokens as a proxy ([counter](0004_count_tokens.py)): the two listing lines 333 characters (74 tokens), 3.4% of `AGENTS.md`'s 2,159. On invocation: `tdd`'s `SKILL.md` 774 tokens (plus 517 and 331 if its references are read), `diagnosing-bugs`'s 2,034.

## Method

- Measured on Claude Code 2.1.322 with `claude-opus-5-5`; the stack's lead model `claude-fable-5-2` was not measured. The shared [method](ab-claude-code.md) and [task list](ab-tasks.md), with the [arm key](0004-key.txt), [deny rules](0004-deny.json) and [leak patterns](0004-leak-patterns.txt). Both arms: one versioned binary, `--effort high`, bypass permissions, a fresh memory folder, `--max-turns 100`, neutral `a`/`b` names, order a1 b1 b2 a2 a3 b3. In place of `--plugin-dir`, the with arm held real copies in the worktree, hash-checked before and after each run; the deny rules, with `Read(~/Jts/**)` added, sat in the `--settings` file. The runs used the owner's sign-in and wrote worktree entries under the main checkout's `.git/worktrees`.
- Tasks, briefs verbatim: [R3](0004-brief-R3.txt) for `tdd` at `96e82e6`, "write tests for the jts.ini and account-form checks", a pass when the new tests pass on `39cb68e`'s `boundary.py` and fail on `96e82e6`'s; [R1](0004-brief-R1.txt) for `diagnosing-bugs`, the replay of `5d51c9c`, graded by patch replay on a fresh worktree; [R2](0004-brief-R2.txt) only if `diagnosing-bugs` met the rule on R1 (it was not run). Graders ran `pytest` with `HOME` set to an empty folder.
- Fixed before the runs: [0004-prereg.txt](0004-prereg.txt) (sha256 `646fc7120045a97ea998360fda2eecb61072a5e02efe949c285c018f96ea12fc`), file times 04:08:12 and 04:08:18 ET; the first task run started at 04:08:28 ET. These times come from the owner's machine and cannot be proved from the repository; its own first line says "~04:10", which is wrong. It was written after the always-on runs (01:58 to 01:59 ET). Its rule, each skill alone: adopt only if the with arm passes at least 2 of 3 and the without arm at most 1, or both at least 2 of 3 and the with arm's median tokens at most 75% of the without arm's; the skill invoked (Skill tool or a Read of its `SKILL.md`) in at least 2 of 3 with-runs; no with-run stalls; the always-on delta at most 150 tokens, taken as measured (182). A one-success gap or a 2-2 tie adds 2 runs per arm. An earlier, unpublished text of the rule (03:30 ET, before any task run) also asked for always-on runs with the copies committed; the pre-registration dropped them and they were not run.
- Containment is the assessment's check. Its clause that Bash commands name none of `ibkr_paper`, `ib_probe`, `ibgateway`, `4002`, `curl`, `wget`, `pip install`, `uv add`, `npm` or `npx` was read after the runs as running a lane module or connecting to a Gateway port. Read literally, every run breaks it, R1's with arm scores 0 of 3, and the decision is the same.
- Before every run a guard checked that nothing listened on the paper Gateway's port and that no Gateway process ran. The first sitting's guard matched command lines and stopped this series falsely at 01:59:30 ET, in the always-on control pair; the resume used the test of the published [guard](0003_gateway_guard.sh) with port 4002 only. Records of what ran: the harnesses of the [first sitting](0004_ab.sh) and the [resume](0004_ab_resume.sh), their collectors ([first](0004_collect.sh), [resume](0004_collect_resume.sh)), the [results](0004-results.json) and the [aggregator](0004_aggregate.py), which recomputes every figure below and the rule under both readings. The harnesses add worktrees of the main checkout, whose history holds the fixes, so they are no re-run recipe.

## Results (resume, 04:08 to 04:45 ET)

| Task (skill) | Arm | Passed | Median tokens (range) | Median turns | Median time | Skill invoked |
|---|---|---|---|---|---|---|
| R3 (`tdd`) | without | 0 of 3 | 377,472 (370,626 to 448,627) | 11 | 103.8 s | n/a |
| R3 (`tdd`) | with | 0 of 3 | 445,553 (290,439 to 481,158) | 14 | 101.0 s | 0 of 3 |
| R1 (`diagnosing-bugs`) | without | 3 of 3 | 858,690 (704,445 to 983,277) | 14 | 190.9 s | n/a |
| R1 (`diagnosing-bugs`) | with | 3 of 3 | 992,287 (776,507 to 1,174,632) | 17 | 191.1 s | 0 of 3 |

- All 12 task runs valid: 2.1.322, completed, `claude-opus-5-5` only, 0 API retries, 0 voids, 0 stalls, no extension. No run read a `SKILL.md` or called the Skill tool. Every without-run listed Orca's `orca-cli` and `orchestration` skills from the main checkout, and every with-run listed the two copies instead: the arms differed by that swap, which the method did not foresee.
- R3: four runs, two per arm, found the `[DEFAULT]` defect but wrote its test as `xfail(strict=True)`, which fails the grade. R1: every patch gave 281 passed, pyright 0, ruff clean; the with arm used 115.6% of the without arm's median tokens, within the spread.
- No Bash call ran a module with `-m meridian.`; `Bash(*ibgateway*)` did not stop four heredoc edits of `boundary.py`'s docstring that names the Gateway's folder. No hand-off to Codex (0 calls, processes, sessions or tokens).
- Cost: 8,084,910 Claude tokens, about $11.04 (client-side estimate): always-on 181,197, R3 2,413,875, R1 5,489,838.

## Decision

Not adopted, each skill on its own measurement. `tdd`: both arms passed R3 0 of 3, and it was invoked in 0 of 3 with-runs. `diagnosing-bugs`: both arms passed R1 3 of 3 at 115.6% of the without arm's median tokens, and it was invoked in 0 of 3 with-runs. The always-on delta, 182, is over the 150 limit for both. Upstream publishes no outcome evidence ("There is no automated eval.", `docs/productivity/writing-for-agents.md` line 47). A later look needs tasks that ask for diagnosis and for test-first work in so many words, the same Orca skills in both arms, and the always-on runs with the copies committed.

## Install and removal

- Not installed. Pinned install: `S=$(mktemp -d) && git -C "$S" init -q && git -C "$S" fetch -q --depth 1 https://github.com/mattpocock/skills.git d1478fcb140db0b93c0c8df17bcfd311844749d0 && git -C "$S" checkout -q FETCH_HEAD`, then `cp -R "$S/skills/engineering/tdd" "$S/skills/engineering/diagnosing-bugs" .agents/skills/` and the two `.claude/skills` links; `git hash-object` of the 7 files must match [the blob ids](0004-addition-hashes.txt); NOTICE, `UPSTREAM.md` and test entries in the same commit; then the check line of `AGENTS.md`.
- Removal: `git rm -r .agents/skills/tdd .agents/skills/diagnosing-bugs .claude/skills/tdd .claude/skills/diagnosing-bugs` with the NOTICE, `UPSTREAM.md` and test entries in the same commit, then `uv run pytest`. Nothing outside the repository.
