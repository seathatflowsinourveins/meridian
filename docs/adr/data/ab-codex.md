# Codex CLI with/without method for ADRs 0007 and 0008 (plan 8.6)

Descriptions, revised on 2026-11-13 after the series; each ADR's pre-registration and scripts record what its series ran, and win where this sheet differs. For Codex CLI 0.167.2 (`openai/codex` tag `rust-v0.167.2` = `ce21072c`) in the `meridian` distro, signed in by the owner with ChatGPT, as ADRs 0007 and 0008 ran it; an independent check on 2026-11-13 verified the pre-run notes against the source at that tag, `codex --help` and runs in an empty scratch home. The tasks and the Gateway guard are in [ab-tasks.md](ab-tasks.md); the Claude Code method is [ab-claude-code.md](ab-claude-code.md).

## Every run

```bash
codex --version   # 0.167.2 in every run of a series; drop a pair that straddles an update (0.168.0 was tagged 2026-11-13 03:54 UTC)
codex features list | grep -E '^(plugins|apps|memories|skill_mcp_dependency_install|hooks|goals|multi_agent) '   # plugins, apps, memories, skill_mcp_dependency_install false (pinned); hooks, goals, multi_agent true
GITC() { GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.https://github.com.helper= "$@"; }
ADR=<nnnn>; BASE=9c5daaae9d32acf259f965fd7b95b458604503b6; OUT=~/src/meridian-ab/$ADR; WT=$OUT/wt-ctx; mkdir -p "$OUT"
GITC clone -q --no-checkout https://github.com/seathatflowsinourveins/meridian "$WT" && git -C "$WT" checkout -q --detach "$BASE"
TRUST=(-c "projects={\"$WT\"={trust_level=\"trusted\"}}")   # both arms, every codex exec in the owner's ~/.codex
P='Reply with exactly the word OK. Do not run any command or call any tool.'
```

- A fresh unauthenticated clone for every run, never `git -C ~/src/meridian worktree add`, which writes the main checkout's `.git/worktrees`. A full clone holds `main`'s history and with it both fixes: for a task run, either fetch only the base into a new `git init` repository (ADR 0007) or scan every call for history reads (ADR 0008).
- `TRUST` is required. A `codex exec` thread started with `-C` under full access, in a project with no trust level, writes `trust_level = "trusted"` for its git root into `$CODEX_HOME/config.toml` (`app-server/src/request_processors/thread_processor.rs` lines 1479-1494 at the tag; shown by ADR 0008 in a scratch home). ADR 0007's runs went without the flag, and the owner's `config.toml` has held `[projects]` tables since (four on 2026-11-13, last written at 04:07:40 ET, the start of its run a3). With it, ADR 0008's 12 runs wrote no trust entry; they still wrote rollouts and Codex's state databases in that home.

## Enabling an addition for one run ($ARMFLAGS; no owner file, sign-in or policy changes)

- A skill: copy it into `$WT/.agents/skills/<s>/`; the arm without it adds `-c 'skills.config=[{name="<s>",enabled=false}]'`.
- An `AGENTS.md` change: edit `$WT/AGENTS.md` between the arms, at the same path.
- A project `.codex/config.toml`, `.codex/hooks.json` or `.rules`: `TRUST` makes Codex load them. Project hooks with no stored trust hash also need `--dangerously-bypass-hook-trust`, in both arms (ADR 0008).
- Orca's hooks (`~/.codex/hooks.json`, 9 events) run in the owner's home: both arms add `--disable hooks`. When the addition is a hook, switch off Orca's alone, as ADR 0008 did: `-c 'hooks.state={"<path of ~/.codex/hooks.json>:<event>:0:0"={enabled=false}, ...}'` for each event, labels such as `session_start` or `pre_tool_use` (`hooks/src/lib.rs` `hook_key`; `enabled = false` wins, `hooks/src/engine/discovery.rs` line 1020).
- A user-scope addition needs a signed-in throwaway `CODEX_HOME`, the owner's sign-in, so ADR 0008 measured oh-my-codex in project scope only.
- Blocked here: plugins, MCP servers, ChatGPT apps, memories and skill-requested MCP installs, all pinned off in every home by `/etc/codex/requirements.toml` (ADR 0007's candidate could not be loaded); and any model run outside the owner's `~/.codex`, because a scratch `CODEX_HOME` has no sign-in and no agent copies `auth.json`.

## M2: prompt bytes by section (no model call, no sign-in)

```bash
H=$(mktemp -d)   # empty scratch CODEX_HOME: bundled catalog, ephemeral, no hooks, writes only under $H
CODEX_HOME="$H" codex --dangerously-bypass-approvals-and-sandbox -C "$WT" -m gpt-6-astra -c model_reasoning_effort=high $ARMFLAGS debug prompt-input "$P" > "$OUT/prompt-$ARM.json"; rm -rf "$H"
jq '[.[]|select(.type=="message")|.content[]|.text|utf8bytelength]|add' "$OUT/prompt-$ARM.json"           # message text
jq '[.[]|select(.type=="additional_tools")|.tools|tojson|utf8bytelength]|add' "$OUT/prompt-$ARM.json"   # tool declarations
```

- Compare texts only: item ids and `create_time` change per render, and two renders were otherwise byte-identical. At `9c5daaa`, in the check's clone: 60,440 bytes in 7 items, among them tools 21,832, model instructions 21,428, the `AGENTS.md` block 8,529, the skills catalog 4,002, `<multi_agent_role>` 2,400, `<collaboration_mode>` 920 and `<environment_context>` 624.
- A lower bound, never the always-on figure: it leaves out the goal tools, web search, image generation and the other extension tools, and all hook context. The text holds the path and the date, so a path one character longer adds a byte.

## M1: always-on tokens, the figure the ADR states

The owner's signed-in `~/.codex`, the same day and the same `$WT`, 3 runs per arm, without then with:

```bash
for N in 1 2 3; do codex exec --json --color never -m gpt-6-astra -c model_reasoning_effort=high --dangerously-bypass-approvals-and-sandbox -C "$WT" "${TRUST[@]}" $ARMFLAGS "$P" < /dev/null > "$OUT/ctx-$ARM-$N.jsonl" 2> "$OUT/ctx-$ARM-$N.stderr"; done
jq -c 'select(.type=="turn.completed")|.usage' "$OUT"/ctx-*.jsonl
```

- `< /dev/null` is required: given a prompt argument, `codex exec` still reads piped stdin to its end and appends it (under a `bash -s` heredoc, the rest of the script).
- A valid run has only `agent_message` items (a reasoning item is harmless), and its rollout `~/.codex/sessions/**/rollout-*-<thread_id>.jsonl` has exactly one `token_usage_record`. Find rollouts by thread id, never by time: parallel series and Claude Code's codex plugin write rollouts there too.
- Always-on = the median `turn.completed.usage.input_tokens` per arm, cached part included; the 3 runs should match. Delta = with − without. Measured at `9c5daaa` without an addition: 16,281 (ADR 0007) and 16,285 (ADR 0008, a longer path), identical within each series.

## Real task (3 runs per arm, order a1 b1 b2 a2 a3 b3)

- Clone per run as above at the task's base, then `git -C "$WT" checkout "$TESTS_FROM" -- tests/` and `uv sync --locked` (R1 and R2 commits in ab-tasks.md). Record a `uv run pytest -q` baseline in each clone first: the public-tree scan reads untracked files, the addition's included.
- `timeout --signal=INT 60m codex exec --json --color never -m gpt-6-astra -c model_reasoning_effort=high --dangerously-bypass-approvals-and-sandbox -C "$WT" "${TRUST[@]}" -o "$OUT/last-message.md" $ARMFLAGS - < "$OUT/prompt.txt" > "$OUT/events.jsonl" 2> "$OUT/stderr.log"`: exit 0, 1 (failed or interrupted) or 124 (timed out).
- ADR 0007 gave the agent a stand-in `HOME` (links to the shell profiles, `.local`, `.cache` and `.config/uv`). Under bypass, absolute paths stay reachable, so it is a seatbelt: the scan of every call decides.
- `events.jsonl` keeps only nine item kinds, so count and scan tool calls in the rollouts, the root's and every sub-agent's: `response_item` lines of type `custom_tool_call` or `function_call` (in code mode they are `exec`). `session_meta.cli_version`, model, effort, approval and sandbox must match across arms.
- Sub-agents may run at another effort than the root (ADR 0008's ran at medium): add the token sums of every rollout whose `session_meta.session_id` is the run's thread, and report them separately.
- Task checks as in ab-tasks.md; the scope check leaves out the addition's own paths. A run passes when its turn completed and every check holds. Compare pass counts, then tokens with sub-agents, then wall time.
- Remove the clone. Events and rollouts carry `session_meta.creator_account_id`: they never go into this repository (ADRs 0007 and 0008 kept them on the owner's machine).

