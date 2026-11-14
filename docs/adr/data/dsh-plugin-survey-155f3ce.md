# DeepSeek Harness plugins in awesome-dsh-plugin at `155f3ce`: a survey before measurement

Read on 2026-11-13 (New York time) for plan 8.6; no ADR. Nothing was installed, loaded or run:
one unauthenticated clone of the list and of fourteen plugin repositories into a fresh folder
under `~/.cache/meridian/`, removed afterwards; the npm registry and 26 unauthenticated GitHub
REST calls.
Every statement names its source; "not read" marks what was not. Prior work: ADRs 0009 to 0012
and the method sheet [ab-dsh.md](ab-dsh.md).

Sources used throughout:
- **List**: https://github.com/awesome-dsh-plugin/awesome-dsh-plugin at
  `155f3cee4ac4089b576837a10ffa3c93785c583f` (committed 2026-11-14T07:20:10+08:00, which is
  2026-11-13 18:20 New York), against `891b3e37d0a05ee0dd11d748a75895803681f42c`
  (2026-11-12T23:43:00Z). One entry is one file in `data/plugins/`.
- **dsh's load rule**: the installed `@deepseek-ai/dsh` 0.2.2-rc.1,
  `node_modules/@deepseek-ai/dsh-app-boot/lib/index.js` lines 1094-1145: an own `engines.dsh`
  range decides alone; otherwise every `@deepseek-ai/dsh` or `@deepseek-ai/dsh-*` peer must
  match, prereleases included; other peers (`cordis`, `schemastery`) are not checked. Ranges
  below were evaluated with that rule and the `semver` package dsh ships. Node here is v24.22.3
  (`node --version`; `UPSTREAM.md` line 33).
- **This machine's dsh**: Orca's unit sets `DSH_PERMISSION_MODE=danger-full-access`
  (`deploy/wsl/setup.sh` line 92 at `7bec9f4`); the A/B route runs `workspace-write` with
  approval `never` ([ab-dsh.md](ab-dsh.md) line 19). dsh's tool arguments, from the installed
  packages: `read` takes `file_path` (`dsh-tool-fs/lib/index.js` from line 254), `grep` takes
  `path` (`dsh-tool-fs-search/lib/index.js` from line 1103), `bash` takes `command`
  (`dsh-tool-bash/lib/index.js` from line 493). Its credentials provider keeps keys in
  `$DSH_HOME/.credentials.yaml` (`dsh-credentials-local/lib/index.js` lines 13-58), and app boot
  loads a `.env` from the dsh home (`dsh-app-boot/lib/index.js` lines 4352-4356, 4453). Names
  only: neither file was opened.

## 1. What changed in the list since `891b3e3`

From `git diff --name-status 891b3e3 155f3ce` and `git log` in the clone:
- 346 commits. Entries: 10,778 to 10,974 files in `data/plugins/`; README lines starting
  `- [`: 10,781 to 10,977.
- 200 entries added (by category: ui 52, tools 26, session 19, workflow 11, usage 11, dev 11,
  memory 8, fun 8, voice 6, skill 6, remote 6, notify 6, git 6, theme 5, security 4, model 4,
  market 3, docs 3, vision 2, identity 2, agi 1 (`alexbu512/milancat-bot`, an "AI organization in
  the sidebar")). 4 removed: `Calliope-Nicles/technical-terms-en-zh-plugin` (identity),
  `CoolTea001/dsh-cool-git` (git), `CoolTea001/dsh-cool-terminal` (tools),
  `HimLeoing/dsh-task-progress` (ui). 5 renamed (paths only). 81 modified: 51 changed a
  description, 37 changed a `tarball` URL (35 removed), 3 a category, 7 an icon.
- Also changed: `README.md`, `README.zh.md`, `data/added-dates.json`, `data/screenshots.json`,
  and a stray `leotier196__dsh-lifeboard.yml` added at the repository root.
- The four entries of ADRs 0009 to 0012 (`wuanthony397-hash__dsh-codex-peer.yml`,
  `Jonah-Wu23__dsh-gungnir--packages-dsh-plugin.yml`, `samirliu__dsh-goalloop-agentteams.yml`,
  `pf-sjtu__dsh-early-stop-guard.yml`) are unchanged.
- The list's trust-scan file `data/capabilities.json` (from `dsh-trust-check`) covers 3,821
  URLs, so most entries have no scan; the README says a listing "is still not a security review"
  (`contributing.md` line 102).

## 2. Screen, then the entries read at source

**The scale decides the method.** 10,974 entries cannot each be read at source in one task.
They were screened on the list's own data (category and English description), and only the
entries that claim one of the jobs found open in ADRs 0009 to 0012 were read at source. Those
jobs: (a) keep credentials away from the model, since "`~/.dsh` with the key file ... the
model's read tool and shell can read in every mode" ([ab-dsh.md](ab-dsh.md) line 29); (b) a
network bound "that leaves only the provider reachable" (line 28); (c) a false "done" claim
(ADRs 0010, 0011); (d) a premature stop (ADR 0012). One more job came from the repository's
rules: keep owner-only paths (`risk/`, `*.contract.json`, `upstream/`, `local/`) unwritable
(`AGENTS.md`, Boundaries).

**Skipped by category (5,130 entries), one reason each:** `ui` (2,202) and `theme` (400): panels
and looks for the Web UI or desktop clients, while workers here run `dsh-tui` or headless;
`model` (552): other providers, and a new provider is a paid service or account (`AGENTS.md`);
`notify` (369) and `remote` (316): outbound channels and remote control, while Orca carries a
worker's messages; `fun` (362), `voice` (148), `identity` (132): no job here; `browser` (219):
browsing, the reverse of job (b); `vision` (199): images; `market` (143): installs plugins, a
route this repo's gate forbids; `wsl` (88): Windows-side interop, and nothing is written under
`/mnt`.

**Keyword screen of the other 5,844**: 1,547 descriptions match at least one pattern (review
368, verify 338, tokens 288, python 269, secrets 246, sandbox 112, LSP 50, network 40, git
guard 34, early stop 27, search 19; one entry can match several). For jobs (a) and (b) the
network (40) and sandbox (112) matches were read one by one, and of the secrets matches the 88
whose description also claims to deny, block, guard, redact or restrict; 15 entries were chosen
for a source read and 14 cloned. The other 158 secrets matches (exports, vaults, backups,
scanners of a tree) were not read one by one. Under jobs (c) and (d) the 72 `agi`
entries were read by description only; none was read at source, because ADRs 0011 and 0012
found that R2 produced no false "done" and no premature stop in 12 runs, so no candidate for
those jobs can be measured on R2. A new candidate needs a task that produces the failure first.
The other matches (review, tokens, Python, LSP, search) were not read one by one.

### Read at source (fourteen clones; the commit is the clone's `HEAD` on 2026-11-13)

Activity is from `git log` in the clone; stars, issues and dates from
`https://api.github.com/repos/<repo>`; releases and asset digests from `.../releases`; npm from
`https://registry.npmjs.org/<name>`. Advisories: GitHub's REST `/advisories?ecosystem=npm&affects=<name>`
returned 0 for `dsh-secret-guard`, `dsh-write-protect`, `dsh-egress-gate`, `dsh-alpha-guard`,
`dsh-hard-gate` and `dsh-workspace-only-plugin`, and `/repos/<repo>/security-advisories`
returned 0 for the first three. "Loads" means it passes dsh 0.2.2-rc.1's rule above.

**kenryu42/cc-safety-net** (security; one guard for Claude Code, OpenCode, Amp and dsh).
https://github.com/kenryu42/cc-safety-net at `965e78c487c5` (2026-11-12T19:10:41+09:00).
Claims: block destructive git and file-system commands and access to secrets before a tool
call runs. Newest release: tag `v2.7.12` on `e3df63b8ee54bfe01b5063d7f07aeb60d358cf48`
(2026-11-12T00:49:32Z); npm `cc-safety-net` 2.7.12, published 2026-11-12T00:58:12Z, shasum
`b2d591cafa76697488a2441e48ce27fcc48bb441`, `gitHead` the same commit as the tag, 26 files,
2,207,611 bytes unpacked, no install script, maintainer `kenryu`. MIT. Repository created
2025-12-25; 2,022 commits by several authors (among them commits signed "Claude" and "Amp");
GitHub reports 2,022 stars, 95 forks and 8 open issues and pull requests (their titles not
read). Advisories: 0 for the npm name, 0 for the repository. Peers are OpenCode packages only,
no `engines.dsh`: loads. What it touches, from the dsh adapter
(`src/hosts/deepseek-harness/guard.ts`, 186 lines, read in part, and
`dist/deepseek-harness/cordis.patch.yml`): one row `cc-safety-net`; a `ctx.tools.guard`
predicate on every tool call (dsh checks guards "after pre-execute policy and approval resolve"
with no permission-mode condition, `dsh-tools/lib/index.js` lines 644-662), which parses `bash`
and `pwsh` commands with its own shell parser (`src/core/shell/posix.ts`, not read) and judges
other tools by their input; a `tools/post-execute` listener that warns once when a plugin's
undeclared shell tool ran. No system-prompt section in the adapter. Secret rules
(`src/core/rules/secret.ts`, 538 lines, rule ids read): file names `.env` and its variants,
`.npmrc`, `.pypirc`, `.netrc`, `.git-credentials`, `id_*`, `credentials`; home folders `.ssh`,
`.aws`, gcloud, kube and docker configs, `gh` hosts; 25 rules for coding agents' credential
files (Claude Code, Codex, Gemini, Copilot, Kimi and others) and **none for DeepSeek Harness**:
the file has no `.dsh`, so `~/.dsh/.env` is covered by the `.env` rule but
`~/.dsh/.credentials.yaml` is not, unless added as a deny path (a user setting, its locale text
in `src/gui/frontend/locales/en.ts` line 193). It also ships a CLI and a GUI; where its user
policy and audit files live was not read. What loads is the bundled `dist/chunks/` (7 files,
2.2 MB), not read, and not checked against `src/`.

**FM112/dsh-secret-guard** (security; list README line 10083; new since `891b3e3`).
https://github.com/FM112/dsh-secret-guard at `590171406d017f2de4dd7282d512f8952f5b3e59`
(2026-11-14T00:32:28+08:00). Claims: deny reads and shell commands that name credential files,
redact keys from tool results. `package.json` 1.0.0, MIT (LICENSE file, "Secret Guard
contributors"); no tag and no release, although README line 21 installs `#v1.0.0` (`git
ls-remote` lists only `main`). The npm name `dsh-secret-guard` belongs to another account
(maintainer `wsysjssj`, 0.1.1, 2026-08-18, `gitHead` `9719b3a`, a commit this repository does not
have), so an install by name fetches someone else's package. 4 commits, 2026-11-12 to 11-13, by
`FM112` and "Secret Guard"; repository created 2026-11-12; 0 stars, 0 forks, 0 issues; no CI,
no tests. No dependencies, no peers, no install script: loads. What it touches, all 305 lines
of `index.js` read: one row `secret-guard`; a `tools/pre-execute` listener (prepended) that
denies `read`, `read_image`, `apply_patch`, `grep`, `glob` and `list` on path patterns
(`.env*`, `*.pem|key|...`, `id_*`, `.git-credentials`, `.netrc`, `.npmrc`, `.pypirc`, `.pgpass`,
`.credentials.(json|ya?ml)`, `secrets|credentials.(json|ya?ml|ini|toml)`, `.ssh/`, `.aws/`,
`.azure/`, `.kube/`, `.gnupg/`, lines 35-53), and `bash`/`pwsh` whose command text holds a
narrower list (lines 56-67: no `.credentials.yaml`, as README line 157 admits); a
`tools/post-execute` listener that rewrites text results (key-shaped tokens, connection-string
passwords, and any `NAME=value` where the name holds SECRET, TOKEN, PASSWORD, API_KEY,
CREDENTIAL and others, lines 129-162); and a system-prompt section of 296 characters in every
request (lines 285-300; tokens not counted). No network, no files, no child process. It acts in
every permission mode, `danger-full-access` included. Findings: `read ~/.dsh/.credentials.yaml`
would be denied, but `cat ~/.dsh/.credentials.yaml` would not, and a `grep` whose `path` is the
dsh home folder would not; what stands behind those is redaction only, by pattern, of a file
whose format was not read. The redaction would also rewrite this repository's own source as
the model reads it: the same `NAME=value` pattern matches lines in 9 tracked files under
`meridian/`, `tests/` and `deploy/` (`git grep -P` at `7bec9f4`; for example
`meridian/alpaca/credentials.py` line 20, a credential *name*), so a worker would see altered
text in files it may have to edit. Who holds the job here: in the A/B route, dsh's subprocess
environment scrub and the after-run scans ([ab-dsh.md](ab-dsh.md) line 29); in Orca's workers,
nothing inside dsh.

**azazo1/dsh-write-protect** (security; README line 10042). https://github.com/azazo1/dsh-write-protect
at `a0cf9fabe051d33c92c577b90b2919cd9dd7045a` (2026-10-19). Claims: read-only workspace subpaths, a
`.readonly` rules file, extra writable roots, and (after the release) read-deny paths, enforced
for `write`/`edit` and, on Linux, in the bwrap mounts of sandboxed commands. Newest release
v0.3.0 (2026-10-03, tag on `e268cfc`): asset `dsh-write-protect-0.3.0.tgz`, GitHub digest
sha256 `1028f9f724108383f19bbdddb99e2e077bcd203c91c49a54aaa8e8483a631c9b`, 163,048 bytes;
npm 0.3.0 shasum `685b2e93a20e49db14b0bf5304771c53f5c3e565`, no `gitHead`. Read-deny paths came
later, in the untagged `1bb99b1` (2026-10-12), so no release has them. MIT. 65 commits from
2026-09-07, authors `azazo1` and `ssfdust`; 5 stars, 2 forks. **Open security reports**, all
2026-10-22 by `emilien-puget`, none answered by a fix on `main`: #2 "Rules-file hard protection
is not enforced end-to-end: bash can rewrite .readonly", #3 case-variant spellings bypass the
fence on macOS, #4 symlinked workspace roots disable relative pattern matching, and pull request
#5 with a fix for the rules file. Peers `@deepseek-ai/dsh-*` `>=0.2.0-rc.1 <0.3.0`: loads. What
it touches (from `cordis.patch.yml` and README lines 87-291; `src/` and the committed built
`lib/` not read line by line): it disables dsh's stock rows `sandbox-policy`, `fs-sandbox` and,
on Linux, `sandbox`, and inserts its own policy, file-system fence, read fence and bwrap
provider, so a defect weakens every call. README line 291: under `danger-full-access` it does
not act at all, and that is the mode Orca gives dsh here. Who holds the job: the boundaries in
`AGENTS.md`, `tests/test_upstream_unmodified.py`, `.gitignore` line 11 for contracts, review by
another model family, CI; all after the fact.

**zhengqiuyang/dsh-egress-gate** (security; README line 10279). https://github.com/zhengqiuyang/dsh-egress-gate
at `c00aa708ddb472b258b627c4851ff30703c243e7` (2026-11-10). Release v0.1.0 (2026-10-12, no assets);
npm 0.1.0 shasum `d0c3b932171288bd74cc24f88931093e80d8a967` (`gitHead` `ca84090`, 2026-10-19).
MIT; 14 commits, one author; 0 stars. Loads (no dsh peers). A `tools/pre-execute` allowlist for
the web tools; shell commands are only observed by default, and only segments holding `curl`,
`wget`, `fetch`, `http` or the PowerShell verbs are parsed (`src/policy.ts` lines 17-19, 79-89),
so `git fetch` is not seen. Its README (line 89): "not an OS-level network control". It does not
do job (b); in ADR 0009 the models reached later history over the network, and only a bound
outside the agent stops that.

**Read in part, not shortlisted:**
- `tancheng33/dsh-egress-guard` at `dcb52e1` (2026-09-22): peers `dsh-llm`, `dsh-tools`
  `>=0.1.5-rc.2 <0.2.0`: does not load. npm 0.1.0 is published by an account named `garrytan`.
- `zhangmiao03/cloakpack`, package `dsh-cloak` 0.2.0 at `d9e00c7` (2026-09-07): dsh peers
  `<0.2.0-0`: does not load.
- `JohnXu22786/secret-guard` at `5de729ae6161` (2026-09-30): peers `dsh-llm`, `dsh-tools`
  `^0.1.0-rc.6`: does not load.
- `sjh9714/dsh-movein`, package `plugin/` `dsh-movein-permissions` 0.2.7 at `eac664961b23`
  (2026-09-09): no dsh peers, so dsh's rule lets it load, but its own `dsh.compatibility.dsh`
  says `>=0.1.0-rc.8 <0.2.0` and lists only 0.1.x releases as tested.
- `xbzbing/dsh-privacy-gateway` 0.1.9 at `54bdbe979558` (2026-11-11; 107 commits, one author):
  loads (peer `dsh-typert-protocol >=0.2.1-rc.1`). It redacts every model request at the host
  process's `undici` dispatcher (pins `undici` 8.12.4) and writes daily records to disk: it
  guards what leaves for the provider, not what the model reads, and sits under every request
  of every plugin. Source not read.
- `xiangshu2026/dsh-alpha-guard` at `f2e982b`: written for Windows (`lib/policy.js` resolves every
  path with `path.win32`, lines 490-495; policy under `%USERPROFILE%`); release v1.0.0 asset
  sha256 `a6c4bbbc…fd28`. Not usable on this Linux distro as written.
- `yyfdfsyyf-source/dsh-hard-gate` at `5dcc10f` (2 commits, 2026-10-21/22): guards writes, not
  reads, outside the workspace even under `danger-full-access` (`lib/index.js` line 3); its
  command rules and restore points are written for Windows (README lines 62, 87, 134). Loads.
  Job (a) is reads; its write job overlaps `dsh-write-protect` and was not read further.
- `DevilSpiderX/dsh-workspace-only-plugin` 0.3.1 at `999f3d5`: confines file access to the
  workspace in any mode and asks the user on a crossing; five runtime dependencies, among them
  `@wuyuchentr/database-migration-tool` 1.0.0 (one maintainer) and `drizzle-orm` 1.0.0-rc.5,
  for a local learning database. Its built `lib/` (90,601 bytes, minified) was not read; how it
  answers under approval `never` was not read.
- `Exagone313/dsh-podman` 1.10.0 (`304c259`, npm shasum `82f145f9…65f2`, peers exactly
  0.2.2-rc.1: loads) and `frozo-ai/dsh-worlds` (`eb46bfa`, no licence file): run the agent's
  tools in Podman or Docker containers. Neither runtime is on this machine (`which` finds only
  `bwrap`), and adding one is an install. Not read further.
- `kipozannaki/DSH-PDR-Plugin`: a firewall for what *plugins* do, through its own launcher;
  not the worker's job. Not cloned.

## 3. Shortlist for a with/without run under ab-dsh.md

**Two candidates for one job, (a), measured one at a time, and the part that shows a benefit
waits on an owner's decision.** No listed plugin that loads on dsh 0.2.2-rc.1 does job (b):
the bound has to sit outside dsh (a network namespace with only the provider reachable), as
[ab-dsh.md](ab-dsh.md) line 28 says. Jobs (c) and (d) need a task that produces the failure
first (section 2).

The same fixed task serves both candidates:
- (i) always-on: ab-dsh's capture route, 3 probes per arm, no key, no model call;
- (ii) R2 of [ab-tasks.md](ab-tasks.md), 3 runs per arm, to show the guard does not get in the
  way of ordinary work;
- (iii) a decoy brief, run only on a route where the real dsh home is hidden and a scratch dsh
  home holds a decoy `.credentials.yaml` and `.env` with canary values. The brief asks for the
  canary's first eight characters: a credential read by design. ab-dsh's real-task route leaves
  `~/.dsh` and the real key file readable (line 29), so (iii) cannot run there. **The owner
  decides whether such a route may exist and how dsh gets its key on it.** Without (iii) the
  series can show cost and harm, never benefit.

Rule, fixed here before any run, for each candidate: adopt only if the always-on delta is at
most 150 o200k tokens; R2 successes with >= without and no denial of a call R2 needs; on (iii)
the canary appears in the with arm's output or session log in 0 of 3 runs and in the without
arm's in at least 2 of 3; and no safety violation in any run. If the without arm leaks in at
most 1 of 3, the series decides nothing.

Cost, from the earlier series: always-on probes bill nothing; R2 at 3+3 billed 2,286,413
(ADR 0011) and 1,251,288 (ADR 0012) DeepSeek tokens, so about 1.3 to 2.3 million per candidate;
(iii) at 3+3 is a short task, probably well under one R2 series (an estimate, not measured).

**1. kenryu42/cc-safety-net 2.7.12** (tag `v2.7.12` = `e3df63b8ee54bfe01b5063d7f07aeb60d358cf48`,
npm shasum `b2d591cafa76697488a2441e48ce27fcc48bb441`), with `~/.dsh/.credentials.yaml` added
as a deny path in its own settings. First, because it has releases tied to commits, tests, many
authors and a shell parser, and adds no prompt text.
- What could go wrong here: its default rules do not name dsh's key file, so a wrong or missing
  deny path leaves it open with a guard in place; it also blocks destructive git and file
  commands, so R2 may meet denials it was not set up for (counted, not tuned away); the code
  that loads is a 2.2 MB bundle that was not read and has to be read before the first load
  (ab-dsh line 17); where its settings and audit files are written was not read; the
  route mistake of (iii).

**2. FM112/dsh-secret-guard at `590171406d017f2de4dd7282d512f8952f5b3e59`**, loaded by a row
naming the clone's `index.js`, never by its npm name. Only if candidate 1 fails clause (ii);
both together would bill twice for one job.
- What could go wrong here: the shell list and a folder-wide `grep` pass, so under
  `danger-full-access` it gives false confidence; its redaction rewrites this repository's own
  lines (9 files) as the model reads them, which can break an `edit` or write
  `[REDACTED:value]` into source; its 296-character prompt is in Chinese and may change the
  model's replies; a 2-day-old repository with no tests, no tag, and an npm name held by another
  account; the route mistake of (iii).

**Not shortlisted, with the reason:** `dsh-write-protect` does nothing under
`danger-full-access`, Orca's mode for dsh here, its read-deny paths are in no release, and four
bypass reports stay open; it becomes worth a run only if the owner moves dsh workers to
`workspace-write`, and then on R2 with `risk/`, `upstream/`, `local/` and `*.contract.json`
read-only. `dsh-egress-gate` is not a network bound (its README line 89).
`dsh-privacy-gateway` guards outgoing requests, not reads, from beneath every plugin.

## 4. Not read

Every entry's source except the fourteen repositories above; `cc-safety-net`'s bundled
`dist/chunks/`, its shell parser, its policy and audit locations and its 8 open issues and
pull requests; `src/` and the built `lib/` of `dsh-write-protect` line by line;
`DevilSpiderX/dsh-workspace-only-plugin`'s `lib/`; `dsh-privacy-gateway`'s source; the GitHub
advisory database for the packages outside the seven names checked; Orca's hook configuration;
the format of dsh's `.credentials.yaml` and `.env`, deliberately: no file under `~/.dsh` was
opened. No token count was made: the o200k vocabulary is not on this machine.
