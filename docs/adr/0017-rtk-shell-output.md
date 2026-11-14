# ADR 0017: rtk shell-output compression for agents

**Status: not adopted.** Decided 2026-11-13 under the owner’s revised upstream-quality/runtime rule: the failure-output fidelity veto applies. [Pre-registration](data/0017-prereg.txt), [source audit](data/0017-source-audit.md), [captures](data/0017-outputs.json), [measurement script](data/0017-measure.py), [context](data/0017-context.json).

## Need

Layer 7 of the [approved ecosystem manifest](data/ecosystem-manifest.md) originally placed rtk at “measure”. The owner requested token efficiency; on 2026-11-13 the coordinator relayed a change to admission by upstream quality plus runtime compatibility, retiring per-item model A/B series. The [pre-registration amendments](data/0017-prereg.txt) preserve the original method and both changes.

## Candidate

[rtk-ai/rtk v1.2.0](https://github.com/rtk-ai/rtk/releases/tag/v1.2.0), latest stable, released 2026-11-08 10:46 UTC, commit `e288a18c04452fd26192f59132e5324a8bb6924d`; last push observed 2026-11-13 17:09:37 UTC. RTK AI Labs; Patrick Szymkowiak and four named core contributors. CLI Apache-2.0, linked compression engine BUSL-1.1 with an additional production-use grant. Full Linux musl binary measured; exact source, licence, team and artifact checksum links in the [audit](data/0017-source-audit.md).

Quality: 86,516 stars, 5,544 forks, five named core team members, a same-day push and stable releases on October 13/14/25 and November 8 support an actively maintained specialist candidate for the manifest’s single shell-compression slot. These are adoption/maintenance signals, not proof of lossless output or a comparative ranking; the fidelity test below decides. [Source snapshots and cadence](data/0017-source-audit.md#quality-assessment-under-the-revised-admission-rule).

## Advisories

[GitHub advisories](https://github.com/rtk-ai/rtk/security/advisories), checked 2026-11-13: three published, covering untrusted filters, permission-gate bypass and injection in the separate OpenClaw npm plugin. None lists CLI 1.2.0 in its affected range; the permission advisory's patched-version notation is inconsistent. [Exact ranges and links](data/0017-source-audit.md#identity-release-and-advisories); no dependency-wide audit claimed.

## What it installs

One executable; init is separate. Codex project init writes `.codex/hooks.json` (PreToolUse/Bash → `rtk hook codex`), `RTK.md` and its `AGENTS.md` reference; global init writes under the Codex home. No Codex config.toml edit. Other runtimes' hooks, settings and instruction files are enumerated from pinned source in the [audit](data/0017-source-audit.md#runtime-integration-opt-in-init-not-automatic-from-extraction). Only disposable configurations were written.
Local SQLite command history and raw-output recall are on by default. Network telemetry requires explicit consent and is off by default; wrapped programs keep their own network behavior. RTK and local prompt-render invocations used scratch homes and a per-process PATH; no owner settings or shell profiles were changed, and the download folder is removed at completion.

## Always-on context

[Local M2 render](data/0017-context.json), Codex 0.167.2, same project path, empty Codex home, no model call: message text 37,976 → 37,985 bytes; o200k tokens 8,177 → 8,182 (**+5**). The render includes `@RTK.md` but does not expand its body; the separately counted RTK.md is 547 bytes/127 tokens. This excludes hook context and extension tools; it is not M1. M1 was initially blocked by the Gateway guard and subsequently retired by the owner’s rule change; no model-token claim is made.

## With and without

[Method](data/0017-prereg.txt) fixed before measurement: eight commands on passing and planted-failure trees at `61536fc`, o200k counter from ADR 0001, >=25% aggregate saving, exact retention of every failing node id, diagnostic location/message and exit status. Four checks, status/log, the real merged PR #31 diff and recorded PR checks; only gh output is replayed. [Reproduction and caveats](data/0017-operations.md).
The original [Codex method](data/ab-codex.md) and [R2 task](data/ab-tasks.md) stopped at the Gateway guard before any model session. The later owner instruction retired those runs permanently; they are not missing and no Gateway action is pending. [Run status](data/0017-run-status.json).
**Compression:** 37,462 → 14,801 tokens across 16 cells (**60.491% fewer**); all exit codes retained. Passing pytest: 1,423 passed. Planted tree: only pytest and Pyright fail; lint/format pass. [Counts](data/0017-compression.json), [summary](data/0017-summary.json), [recount/fidelity verifier](data/0017-verify.py). The large PR diff dominates this command mix; these are output-token savings, not model-input savings.
**Fidelity:** 6/7 diagnostic strings retained (85.714%); pytest loses `tests/test_adr0017_planted.py::test_adr0017_planted_failure`. The function, file:line and assertion remain separately, but the exact node id is absent; the recall pointer does not satisfy the registered criterion. The pinned [pytest wrapper](https://github.com/rtk-ai/rtk/blob/v1.2.0/src/cmds/python/pytest_cmd.rs) injects `--tb=short -q -rxX`, suppressing the raw FAILED-node summary. The first fixture’s extra blank line and the extractor’s whitespace correction are [disclosed](data/0017-operations.md); thresholds were not relaxed.
**Runtime protocol:** [six no-model probes](data/0017-hooks.json), Codex first then Claude, feed their own schema/documented Bash input shape to the native RTK processors and execute returned status/lint/type-check commands with expected exits. [Sources and limits](data/0017-hook-method.md): synthetic input values, not captured live sessions; no proof of host discovery/trust. Codex config is project-local; Claude’s tested hook-only config is user-scope inside a scratch HOME. DeepSeek Harness is excluded by coordinator direction.

## Decision

**Not adopted for any runtime:** the missing pytest node id fails the owner’s unchanged 100% failure-fidelity condition despite useful compression and successful processor probes. No setup, UPSTREAM or map addition. [Dated revisit](data/0017-revisits.md): next release restoring full node ids, or 2027-02-11; repeat offline/protocol checks, not model task runs.

## Install and removal

No shared install. Pinned download: `python3 docs/adr/data/0017-fetch.py`, which verifies the release SHA-256. In a disposable project, with scratch HOME and the absolute pinned binary: `rtk init --codex`; remove with `rtk init --codex --uninstall`, compare project files with baseline, then delete the disposable project and cache folder. [Exact contained commands](data/0017-operations.md), including the per-process PATH requirements, are retained for a future fidelity revisit. [Removal probe](data/0017-removal.json) found an empty hooks file, backup and lost terminal newline; deleting the disposable checkout completes cleanup. No machine integration was installed.
