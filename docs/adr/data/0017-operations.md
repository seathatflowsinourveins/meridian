# Reproduction and contained setup

These commands are a follow-up recipe, not an adoption. Run from the repository root. They use the [v1.2.0 release](https://github.com/rtk-ai/rtk/releases/tag/v1.2.0) pinned by SHA-256 in [fetch](0017-fetch.py), and the project setup/removal implemented by [codex.rs](https://github.com/rtk-ai/rtk/blob/v1.2.0/src/hooks/init/codex.rs). The fetch script records the download operation used in this audit; it was assembled after the initial equivalent downloads. It refuses an existing download folder.

```bash
python3 docs/adr/data/0017-fetch.py
python3 docs/adr/data/0001_count_tokens.py --vocab-dir "$HOME/.cache/meridian/adr-0017/vocab" --self-test
python3 docs/adr/data/0017-measure.py
python3 docs/adr/data/0017-context.py
```

The measurement script clones only committed public files into scratch; the command branch is fixed at `61536fc`. It reads the real PR #31 checks once through `gh`, then replays that recorded public output in both states. Other commands actually run twice, through the normal command and RTK's declared rewrite; RTK may request a structured output format internally. The output token counts are o200k_base, not RTK's character-based estimate. Paths are replaced before counting/publication. Timings, progress formatting and recall hashes can vary on reproduction. No absolute output count should be expected to reproduce byte-for-byte across machines.

Project-only Codex integration, in a disposable project `$ADR_PROJECT` with no symlinked instruction/config files:

```bash
ADR_RTK="$HOME/.cache/meridian/adr-0017"
mkdir -p "$ADR_RTK/init-home"
(cd "$ADR_PROJECT" && env -i HOME="$ADR_RTK/init-home" PATH=/usr/bin:/bin "$ADR_RTK/binary/rtk" init --codex)
```

This writes only the project's `.codex/hooks.json`, `RTK.md` and the reference in `AGENTS.md` (plus backups where needed). It registers `rtk hook codex`, so the future Codex process needs the binary directory in **its own** PATH; no profile edit or shared PATH change. The original signed-in [probe](0017-probe.py) stopped at the Gateway guard before any Codex session. It is retained as historical evidence and is not part of the current reproduction recipe: the owner subsequently retired the model A/B requirement. The replacement [protocol probe](0017-hooks.py) invokes the hook processors directly, then executes the returned safe commands; it starts no model session.

Remove the project integration before deleting the binary:

```bash
(cd "$ADR_PROJECT" && env -i HOME="$ADR_RTK/init-home" PATH=/usr/bin:/bin "$ADR_RTK/binary/rtk" init --codex --uninstall)
```

Compare the project's `AGENTS.md` and hook configuration with its baseline, preserve any unrelated hooks, and remove only scratch-owned backup files. Delete the disposable project and `~/.cache/meridian/adr-0017/` when finished; that removes the binary, downloads, vocabulary, scratch homes, history/recall databases and scratch checkouts. No global uninstall is needed. The audit itself removes its entire download folder after collecting the public evidence.

Measurement corrections, without threshold changes: the first failing fixture had an extra blank line after its docstring and unexpectedly failed formatting. Its partial captures are retained in [fixture correction](0017-fixture-correction.json); only that owned runner was stopped, whitespace was fixed, and the failing arm was restarted with `0017-measure.py --resume-failing`. Passing captures were retained. The fidelity extractor was then extended to include Pyright's non-breaking-space-indented continuation message and to count diagnostic locations only in check output (not incidental source citations in the PR diff). All final raw captures are re-evaluated by `0017-verify.py <vocab-directory> --refresh-diagnostics`, then verified again without refresh. The scripts include these corrections; no command output was rewritten to improve fidelity.

The removal command was tested in the scratch context checkout ([result](0017-removal.json)): exit 0, RTK.md removed, hook entry removed, but `.codex/hooks.json` remains with an empty PreToolUse array, `hooks.json.bak` remains, and AGENTS.md loses its terminal newline. For a disposable checkout, deleting that checkout completes removal. In a retained checkout, restore that newline and delete only the empty RTK-created hooks file and its RTK-created backup after comparison; never remove unrelated hooks. Removal is not byte-for-byte restoration by itself.

The [recorded gh output](0017-gh-pr-checks.json) is stored as a JSON string to preserve its terminal tab fields without literal trailing whitespace in the public file. Decoding yields the exact replayed bytes; the measurement script uses that representation on reproduction.
