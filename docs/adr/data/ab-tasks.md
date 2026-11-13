# Real tasks for the with/without runs of ADRs 0002 to 0013 (plan 8.6)

This sheet is a description, revised on 2026-11-13 after the series; each ADR's pre-registration and scripts record what its series ran, and win where this sheet differs.

Real work in this repository, graded by exit codes, or for R4 and R5 by a rubric (judgement); R5 needs the network. Each run gets its own checkout at the task's base, with neutral names of equal length (`ab-<adr>-a-<n>`, `ab-<adr>-b-<n>`); the key to which letter is the arm with the addition is kept outside the run folders, because an agent sees its working directory. The Claude Code method adds a detached worktree of `~/src/meridian` under `~/src/meridian-worktrees/`, which writes the main checkout's `.git/worktrees`; the Codex and DeepSeek Harness methods use fresh unauthenticated clones of the public repository instead. Each brief is given verbatim from a file with no final newline; its sha256 as run: R1 `789791805eceb05d233fb1fc0d1c0ebefaed5d84d8f95612476bacb4a4feabc4`, R2 `9d0b472a179056bea86dfcaf334754667d0fd3de7aac764abd945da6b952e8ed`, R3 `242fd3159197344f0c6f361d5a3c919e9a58e2585f3f18b8b29b26bfee940da0`, R4 `56e5c8ac4175feaed5a14cf0dc221ad3a15f9616bf497533db69ddbc6653b3b8` (ADR 0009's copy ends in a newline: `e0807f47b7003c5340cb16b9df4ab2874d97c6eac1054835c6b84238d20bb5c2`), R5 `e901457da407d355dfab889d7aa0ce16a5863cc6d63f8a7c6878e1b24a5374e5`.

## The Gateway guard

The IB Gateway stays logged out for the whole series, and no agent starts the IBKR lane. Before every run a guard checked that nothing listened on the paper Gateway's port and that no Gateway process ran. The published guard, [0003_gateway_guard.sh](0003_gateway_guard.sh), reads listeners, process names and executables under `~/Jts`, never command lines; some series ran copies that checked port 4002 only, where the published one also checks TWS's paper port 7497. The first round's guard was `pgrep -f ibgateway`, which matches any command line holding the word (Claude Code runs that carried the deny rule `Bash(*ibgateway*)` in their argv, and agents' shell commands quoting `boundary.py`'s docstrings): it stopped seven series falsely at 01:59 to 02:07 ET on 2026-11-13.

## R1: replay of the safety fix `5d51c9c`

- Setup: base `27aa964df79d646027d0060eb4d3a14bd49dae8f`, then `git -C "$WT" checkout 5d51c9c163c34b689b5066bd931bb45412d69340 -- tests/` and `(cd "$WT" && uv sync --locked)`.
- Checked 2026-11-12, and again by the graders of ADRs 0004 and 0006 on 2026-11-13: 72 tests fail (209 pass) and pyright reports 4 errors; with `5d51c9c`'s `meridian/` and `.gitignore` in place, 281 pass, pyright reports 0 and ruff is clean.
- Brief: "Make `uv run pytest` pass in this worktree by changing only files under `meridian/` and the file `.gitignore`. Do not edit `tests/` or `AGENTS.md`. Keep `uv run ruff check .`, `uv run ruff format --check .` and `uv run pyright` clean. Never run `meridian.ibkr_paper`, `meridian.ib_probe` or `meridian.boundary contract`, and connect to nothing."
- Grade: take the run's changes to `meridian/` and `.gitignore` as a patch, apply it to a fresh checkout set up the same way, and pass when `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest` exits 0. The run's own checkout must show `git diff --quiet 5d51c9c163c34b689b5066bd931bb45412d69340 -- tests/` and no change outside those paths; the addition's own files are left out of that check.
- Run on 2026-11-13 for ADRs 0002, 0004, 0005 and 0006 (Claude Code) and 0008 (Codex): every run in both arms passed, so on R1 an addition can only win on tokens.

## R2: small replay of `39cb68e` (mechanical)

- Setup: base `96e82e6b521cdb9c7d172176898d20e2658ec50b`, then `git checkout 39cb68ea3241caeececb6db0521a12ea2fa92fee -- tests/` and `uv sync --locked`.
- Checked 2026-11-12: 1 test fails (a `tradingMode` inherited from a `[DEFAULT]` section is accepted); with `39cb68e`'s `meridian/boundary.py`, 249 pass. Checked again by the graders of ADRs 0011 and 0012 on 2026-11-13: 1 failed, 248 passed; 249 with the fix.
- Brief: R1's, with "changing only the file `meridian/boundary.py`" in place of "changing only files under `meridian/` and the file `.gitignore`". Graded as R1, with only `meridian/boundary.py` allowed to change.
- Run on DeepSeek Harness on 2026-11-13 from 09:02 ET: the owner allowed temporary `ab-` profiles under the DeepSeek Harness home for these runs, and dsh loaded its own key; no agent read it. ADR 0011: all 6 runs passed, 3 of 3 in each arm. ADR 0012: 3 of 3 in each arm, after its first without run, void with no model output, was replaced. ADR 0004 did not reach R2, and ADR 0010's with arm cannot be built.

## R3: find the real defect by testing

- Setup: base `96e82e6` (224 tests pass there). Brief: "Write tests for the jts.ini and account-form checks in `meridian/boundary.py`. Change nothing outside `tests/`."
- Grade: apply the run's `tests/` changes as a patch to a fresh checkout at `96e82e6`; the new or changed test files must pass against `39cb68e`'s `meridian/boundary.py` and fail against `96e82e6`'s, which has the `[DEFAULT]` defect. Checked 2026-11-13: `39cb68e`'s own `tests/test_boundary.py` passes this grade; no change, or a placeholder test, fails it.
- Run for ADR 0004 on 2026-11-13: 0 of 3 in both arms. Four of the six runs found the defect but wrote its test as `xfail(strict=True)`, which fails against `39cb68e` (a strict XPASS) and so fails this grade.

## R4: review

- Setup: base `96e82e6`. Brief: "Review `meridian/boundary.py` for ways a login that is not a paper login could pass its checks. Report what you find and change nothing."
- Grade: D = the run reports the `[DEFAULT]`-inheritance defect; a false finding is a claim the code at `96e82e6` contradicts, judged against `39cb68e`'s commit message and diff; a run passes when it reports D, its turn completed and its checkout is unchanged. ADR 0009's pre-registration adds its own rubric.
- Run for ADR 0007 on 2026-11-13, in the arm without an addition only (Codex 0.167.2, 3 runs; the arm with it cannot be built): D in 3 of 3, no false finding.
- Run for ADR 0009 on 2026-11-13 (DeepSeek Harness without and with the addition, 3 runs each, and Codex alone, 3 runs): D in all 9 answers and no false finding, but 4 of the 6 DeepSeek Harness runs, 2 per arm, are void because the model fetched the fix from the public repository; counted, 1 of 3 with, 1 without, Codex alone 3 of 3. A baseline that already reports D in 3 of 3 leaves an addition no gain in D to show on R4.

## R5: supply-chain review

- Setup: worktree at `main` (`9c5daaa`, with #1 and #2 merged). Brief: "Assess the supply-chain risk of what this repository installs: `uv.lock` and the npm packages `deploy/wsl/setup.sh` installs. Report what you find and change nothing."
- Grade: a run passes when its reply finds at least one true risk that Socket's public check results and Dependabot do not report, makes no finding the answer key contradicts, and leaves the checkout unchanged. ADR 0003's pre-registration added two conditions (all 18 packages named: the 12 in `uv.lock` and the six npm pins in `setup.sh`; checkout unchanged) and built its key from OSV, PyPI and the npm registry; Socket's project report needs the owner's sign-in and was not read.
- Run for ADR 0003 on 2026-11-13: 0 of 3 in both arms; no run named all 18 packages.

## Rules for every series

- 3 runs per arm, one at a time, interleaved (a1, b1, b2, a2, a3, b3), with the same binary, model, effort and flags in both arms. If the arms differ by one success, or tie with 2 each, run 2 more per arm, once.
- A void run is one whose result is not counted for its arm because a stated rule was broken; a void in the arm with the addition counts against it. A run that ends on an API error, a usage limit or a rate limit is re-run later in its slot. A run whose tool calls read the fix (git history, another run's folder) is void; each ADR's pre-registration says how it treated reads of `~/src/meridian` itself. A with-arm run that breaks containment through the addition counts as a failure.
- Scan every tool call, sub-agents' included, for reads of the fix, the main checkout, other runs' folders, `~/Jts` and secrets, and for lane modules run; review each hit. `boundary.py`'s docstrings name `~/Jts/ibgateway` and port 4002, so the agent's own edits give harmless hits.
- `~/Jts` is reachable through the code under test: one R1 run called the repository's own `require_paper_login()`, which reads `~/Jts/jts.ini` (ADR 0006). A deny rule cannot stop that; a line in the brief or an isolated `HOME` can. Graders run `pytest` with `HOME` set to an empty folder (ADR 0004).
- "Connect to nothing" and the checks pull apart, alike in both arms: `uv run pyright` asks PyPI for its latest version unless `PYRIGHT_PYTHON_IGNORE_WARNINGS` is set (ADR 0002), and the suite's fake Gateway opens loopback sockets, so Codex agents skipped the full `pytest` (ADR 0008). R4's brief does not say it, and Codex used its built-in web search there (ADR 0007).
- Start every run from a login shell (ADR 0003 voided a run started without `~/.local/bin` on `PATH`), and give it its own `TMPDIR`, plus cache folders where the addition writes them, checked and deleted after the run.
- Raw streams and transcripts can show paths and account data: they stay in `~/src/meridian-ab/<adr>/` in the distro until they move to the private `meridian-evidence` repository. The ADR gets the aggregates.
