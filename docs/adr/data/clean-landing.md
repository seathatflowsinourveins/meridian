# Clean landing implementation evidence — 2026-11-14

Task scope: approved plan sections 3 and 4; no machine agent setup, automation, real PR,
push, landing, trading lane, or credential access. Local merges of origin/main into this
worker branch are the task's explicit exception to the prohibition on merging pull requests.

## Review record

The gate writes `<sha256(branch)>.review.json` beside its trial state in the common git
folder's `meridian-gate/`; raw final output and the reviewer log stay there too. The JSON
fields are `version`, `builder`, `reviewer`, `model`, `tested`, `summary`, `findings`.
Each finding has `text` and `status`. Generated findings start `open`, which refuses review
completion and publication. The final record contains only the current review round:
its findings must be empty or `closed: reason`; `fixed` is rejected on that same commit.
Fixed code needs another trial and review of the new commit, replacing the old round.
Earlier findings are not carried forward as purported fixes on the current commit. `open` validates explicit files
and the default record identically before any push. Unknown output goes to the lead.

This example wraps the actual Codex final message observed on this branch at
958859cddc716eaf819f5b34437d601a5735ee24, before edits. It demonstrates the real output
format; it is not a gate-issued landing certificate for this implementation.

```json
{
  "version": 1,
  "builder": "claude",
  "reviewer": "codex",
  "model": "gpt-6-astra",
  "tested": "958859cddc716eaf819f5b34437d601a5735ee24",
  "summary": "The requested git diff is empty: HEAD matches the specified merge base, and the working tree is clean. There are no code changes to review.",
  "findings": []
}
```

The real command was `codex exec review --base origin/main --ignore-user-config
-m gpt-6-astra -c model_reasoning_effort=high --json --ephemeral -o FILE`. It exited 0;
JSONL contained `item.completed` with `item.type=agent_message`, followed by
`turn.completed`. FILE was plain prose, not JSON. The gate deliberately does not use
`--output-schema`: the task identifies review as ignoring it; that specific behavior was
not independently exercised in this one permitted real run. Nonempty native priority
bullets become separate open findings; unsupported prose needs lead classification.

The permitted real Claude command used `claude -p "/code-review high
seathatflowsinourveins/clean-landing" --model claude-opus-5-5 --output-format json`, plus
`--no-session-persistence`, plan permissions, Read/Grep/Glob/Bash tools, and a read-only,
no-delegation system instruction. Exit 0 returned a `type=result`, `subtype=success`,
`is_error=false` JSON envelope, string `result`, and `modelUsage` naming claude-opus-5-5.
Its string had prose and a fenced JSON array of ten findings. The gate can preserve each
array item separately. This exploratory review was of the old gate: on an empty branch
diff Claude chose HEAD~1 instead. The implemented prompt explicitly scopes HEAD against
origin/main and requests a findings object. The real run does not certify the new code.

## Lock and failure behavior

One shared kernel flock: `~/.cache/meridian/landing.lock`. A detached Python holder
retains its open descriptor across hand-run client exits. Adjacent `landing.owner.json`
and a mode-0600 Unix socket name the common git directory and branch. Each gate command
keeps one socket connection while executing; auto keeps that connection across all four
steps. The holder serializes commands, including commands for the same branch. Different
repositories cannot reuse a branch name to take the reservation. Legacy flock-only scripts
are excluded even between commands; an owner record alone would not accomplish that.

Land and explicit release remove the owner/socket and relinquish flock before acknowledging
completion. Failed or interrupted manual clients leave the reservation for retry or explicit
release, without killing processes. Automatic clients release on every exit; the holder also
releases on an automatic client disconnect, including abrupt process termination. If the holder itself dies, the flock is released;
open/land refuse and trial must reacquire and retest. This is a local cooperative lock,
not a replacement for GitHub's up-to-date branch protection. The gate retains its existing
last-moment main comparison and loud post-merge tree check.

Tests cover a separate trial client exiting, a subsequent external `flock -n` still
failing, another branch and another repository being refused, an external flock blocking
the gate, and release making flock available. Auto is tested through a complete fake-backed
landing and at each failure stage, with no real PR or push involved.

## Pending-task precheck and dispatch mapping

Read `orca orchestration task-list --help` and both concise and `--full` real completed
listings. Concise rows have `id`, `status`, `title`; full rows add run/creator fields,
`task_title`, `display_name`, dependencies, timestamps, spec and result. Neither has the
worker agent or branch. Consequently the lead calls `register BRANCH --builder ...
--task TASK_ID` at dispatch. Pending intersects those registrations with completed task IDs,
fetches main, checks git ancestry, and checks merged PR head OIDs for squash merges.
New commits beyond an old merged PR remain pending. Deleted branches are skipped.

The bare task-list call in this dispatched worker returned `run_required`; adding
`--run run_69d24a63bdd7` returned the completed Codex-stack task. Pending therefore accepts
`--run` for an explicit automation/coordinator context. It exits 0 only on a registered
completed unmerged task; idle and failed queries exit nonzero. No automation was created.

## Trigger detector and sources

Installed only into `/tmp/meridian-clean-landing-evidence/omx` using
`npm install --ignore-scripts --prefix ... oh-my-codex@0.22.6`. The Python wrapper imports
that package's `dist/hooks/keyword-detector.js` and calls `detectKeywords` in Node; it does
not copy the registry or call a model. The first match is reported as `selected`, and all
matches are preserved. This is keyword selection, not simulation of runtime workflow state.
Absent package exits nonzero with an explicit message.

All eight named phrases selected their documented workflow. Backtick and double-quoted
phrases and a plain build task selected none. The standard lead rules and a real completed
Codex-stack dispatch also selected none. Eleven phrase cases plus that real dispatch ran
against the installed package; offline unit coverage checks missing-package refusal and
that the wrapper delegates to the package detector.

Sources read:

- [Claude headless documentation](https://code.claude.com/docs/en/headless): `-p`, JSON
  result output, slash skill expansion, and no-session-persistence; local `claude --help`
  confirms flags. The documented slash prompt form works in the real run.
- Local `codex exec review --help` confirms the requested base, model, config, JSON,
  final-message, ignore-user-config, and ephemeral flags; the real run confirms their use.
- [Detector at v0.22.6](https://github.com/Yeachan-Heo/oh-my-codex/blob/v0.22.6/src/hooks/keyword-detector.ts)
  and [registry](https://github.com/Yeachan-Heo/oh-my-codex/blob/v0.22.6/src/hooks/keyword-registry.ts):
  the exported detector, priority order and specified phrases; installed-package smoke
  verifies quotation handling. The registry contains more triggers than the eight examples.
- Local `orca orchestration worker-start --help` confirms `--model`/`--effort`; task-list
  help and real JSON establish the registration requirement. No worker was started.
- Local `gitleaks git --help` confirms `--log-opts`; the gate uses
  `--log-opts=origin/main..HEAD` in the branch worktree.

Plan corrections: its verification section says to run headless review "without a model
call", but review necessarily calls the model (the task explicitly permits it). Review
output is not guaranteed structured; failures and unknown prose cannot count as approval.
The simple owner-file proposal cannot exclude unrelated flock-only scripts between
commands, so a holder is necessary. The real task listing supplies neither builder nor
branch, and Claude's empty-diff fallback requires explicit scope in the prompt. No claim
is made that the new auto command was exercised against real GitHub: that is forbidden
for this worker and is the lead's later smoke test.

## Four fixes added from the first production landing

The coordinator's first real landing of #37 exposed four defects in the old gate; this
worker did not reproduce them against real GitHub. Each has an offline regression test:

1. GitHub may not have registered checks immediately after a push. JSON checks map only
   gh's specific missing-checks error to an empty list; both open and land retry until a
   check appears, for at most 120 seconds, with an explicit timeout. Open watches only
   after registration. Authentication errors are not retried as missing checks. The fake
   can return no checks on its first calls; tests cover both delayed success and timeout.
2. Child checks remove inherited `VIRTUAL_ENV` and set `NO_COLOR=1`. Recorded summaries
   prefer stdout, falling back to stderr for stderr-only commands such as gitleaks.
   All PR body/review/title/squash text is copied through a home-path and ANSI scrubber;
   original review evidence remains local. Tests inject an unrelated virtual environment,
   a stderr warning, and Linux/macOS/tilde paths in every outbound text channel.
3. Reopening an existing PR invokes `gh pr edit` with the current title and body. Local
   `gh pr edit --help` confirms those flags; the regression asserts the edited file's text.
4. Gitleaks' stderr summary and local check log have ANSI colour escapes removed. The
   regression emits actual escapes and checks the stored summary/log are plain text.

## Review follow-up

Dispatch registration now wins over trial/auto/review arguments; attempts to change its
builder are refused before any merge/check/model call. The selector-based holder continues
accepting handshakes during a command and refuses contenders immediately; malformed JSON
values cannot drop its flock. Auto has one catch site: code/check defects go to the worker,
while contention, registration and infrastructure/landing conditions stay with the lead.

Current-round `fixed` is rejected both before publication and before landing; a new code
commit requires a new trial/review and replaces the current record. All unresolved findings
are returned together. Claude's task prompt names `git diff origin/main...HEAD`, forbids
local-main/upstream/HEAD~1 fallbacks and specifies that an empty diff has no findings.
Review citations become repository-relative while building the record; other home paths
are scrubbed. Pending exits 0 for work, 1 for idle, and 2 for query/fetch failure.

After a successful merge the reservation is released even if the post-merge fetch fails;
state records that the merge happened, retries cannot merge it again, and the failure names
the tested tree for recovery. The provenance row is now inside the runtime table with the
correct number of columns. The upstream gate's area schema only admits meridian/ and
deploy/ files; adding an area for .agents/ fails its unused-area check, so no such entry is
invented for this branch.

A flock must have a living open file description, so an owner record or separate short-lived
commands cannot exclude another session's plain flock between commands. A persistent shell
holding an inherited descriptor would require a different hand-run interface and the same
lifetime coordination; the small detached holder is retained as the simpler solution for
the required independent commands.

## Second review follow-up

An empty findings array can establish a clean review with prose around the JSON fence,
provided it does not contradict priority findings; common
clean prose is recognized too. Unclassified output stays in the local review log and goes
to LEAD ACTION, never a fabricated worker finding. Closing reasons that claim a fix are
refused just like a bare fixed disposition. JSON CI polling routes named red checks to
the worker while gh/transport failures stay with the lead; pending checks are awaited.

Release cleans stale owner/socket files only while holding the shared flock, including
a corrupt owner record; it still refuses an active command or somebody else's live lock.
Tests kill only their own holder process by its Popen handle and recover with release or
the next trial. Auto validates BODY before reservation, names any unexpected exception as
a lead action, and marks dispatch registration landed when the remote merge is recorded.
Pending skips landed registrations before per-branch GitHub calls; a new dispatch resets it.

Check summaries retain worktree-relative filenames; local check logs retain full paths
with only ANSI controls removed. Publication scrubs decoded JSON values before serializing,
recognizes bare home directories, and preserves HTTP URLs with home-like path components.
Review resolves its worktree once and validates dispatch/request/trial builder provenance
in one helper, retaining the before/after HEAD and worktree checks around the model call.


## Third review: unattended failures and retries

Automatic attempts write a separate `.attempt.json` with `commit`, `step`, and `outcome`
(`running`, `worker_failure`, `lead_action`, or `landed`). Trial updates the commit after
merging main and before running checks. Pending skips the recorded commit without a GitHub
query; a new worker commit becomes eligible, and the lead can explicitly retry auto after
resolving a service failure. A disconnected automatic client releases its lease; the running
attempt still suppresses an unchanged commit after an abrupt interruption. Manual commands
retain their existing across-process reservation. Holder acknowledgements distinguish an
actual release from a lost connection; cleanup cannot mask an existing command exception.

An empty findings array that contradicts priority findings is unclassified and goes to the
lead. Closing reasons may describe fixed-width parsing or explicitly say an issue was not
addressed; reasons claiming a fix still require a new trial and review. Cancelled CI requests
a lead rerun, rejected non-fast-forward pushes return to the worker, and transport failures
stay with the lead. Failed check summaries include tails from both stdout and stderr, with
repository-relative locations and complete local logs. Windows home paths are scrubbed too.

A separate `.posted.json` ledger records each successful review comment by PR and tested
commit before waiting for CI, surviving retrial state replacement. Normal retries update
PR title/body without reposting that comment. A crash between GitHub accepting a comment and
writing the local ledger remains a distributed-transaction window; no atomic operation spans
the local filesystem and GitHub.

## Fourth review: lead triage and structured results (supersedes retry rules above)

Candidates are not verified defects. Open review findings now produce one LEAD ACTION with
stable one-based numbers, and auto releases its reservation. The lead verifies candidates,
sends real defects to the worker, and records other dispositions using `close BRANCH NUMBER
REASON`, with repeated `--also NUMBER REASON` for a batch. Invalid numbers, empty reasons and
fix claims refuse the whole batch. Close validates the tested head and family; it retains an
existing manual reservation or releases its own short reservation. A same-head auto retry
reuses a passed trial when main is unchanged and reuses its validated, fully closed review.
A changed commit or a merge of new main requires a new trial and review.

Pending names waits for worker changes and lead dispositions. It retries dead running
attempts and transient lead actions, with a default limit of three transient failures per
head (`pending --retry-limit`). At that limit it names the required lead action; explicit
auto retries remain possible. It trusts Orca's completed-status filter and fetches main only
when a candidate survives the local checks. An old `meridian-gate/lock` refuses new landings,
naming its path and holder; the old gate must finish or release it, then a fresh trial is
required because historical state filenames are not migrated.

Reviewer subprocesses have a 900-second ceiling (`--review-timeout`); CI watching has an
1800-second total ceiling (`--ci-timeout`), including bounded gh queries. Deadline failures
go to the lead and release reservations, including manual commands. Raw partial reviewer
output stays in the local review log. Empty-handshake ValueError now gets the same stale
release recovery as socket errors. Rejected push stderr is sanitized before worker delivery.

Claude now uses `--json-schema` with an object containing a findings array of objects with
`file`, `line`, `summary`, and `failure_scenario`. The gate requires the successful envelope's
`structured_output` field and validates its fields; neither result prose nor fenced JSON is
a substitute. The existing record format retains each structured item as finding text plus
its disposition. Medium-depth review is the default; `--review-level high` is available.
Codex parses only native `- [P#] title — path:line` bullets outside fenced blocks; all other
output, including prose-only clean conclusions, is unclassified and goes to the lead with
raw output retained locally, as required by the stricter parsing contract.

`claude --help` confirms json-schema, dontAsk, tools, allowedTools and disallowedTools.
[The headless documentation](https://code.claude.com/docs/en/headless) confirms that schema
output belongs in structured_output, and that supplying the diff on stdin avoids needing
Bash. The command uses dontAsk, exposes only Read/Grep/Glob, preapproves those readers and
disallows Bash/Edit/Write/Agent/Task/MCP tools. Thus there is no editing or shell tool and no
plan-mode instruction to produce a plan or ask questions; git supplies the exact diff.

Two observed CLI constraints changed the command: strict-mcp-config was rejected before a
model call because an enterprise MCP config is present, so the gate denies MCP tools instead.
More significantly, `/code-review medium ... --json-schema ...` returned a successful local
command envelope with `local_command: code_review`, `num_turns: 0`, and `result: Command
completed`, but no structured_output. Its metadata recorded a model call, so it was not a
valid certificate. A direct medium-depth review prompt with the same fields and schema then
returned this actual result (exit 0, model claude-opus-5-5, no spawned subagents or permission
denials):

```json
{
  "subtype": "success",
  "is_error": false,
  "structured_output": {"findings": []}
}
```

The supplied diff was origin/main...HEAD at b122b494845e2f6f3292da21fdfe9517c6c0b27f.
This confirms the transport/format, not a review certificate of the later implementation.
Exact command, full envelopes, stderr and a sanitized metadata excerpt are retained in
`/tmp/meridian-clean-landing-review4/`; no subagent or helper worker was spawned.
