#!/bin/bash
# ADR 0008, measurement M2: Codex's own prompt render with and without oh-my-codex (OMX), with
# no model call and no sign-in. Run in the distro on 2026-11-13 with codex-cli 0.167.2. The
# measurement's home-directory paths are arguments here. Results: 0008-m2.json.
#
#   bash 0008_m2.sh render <label> <scratch CODEX_HOME> <clone> <out dir>   3 renders, as M2 ran
#   bash 0008_m2.sh split <render.json>       bytes per section and hashes (written for the ADR)
#   bash 0008_m2.sh roles <render.json>       the spawn_agent role list, entry by entry (same)
#   bash 0008_m2.sh guard                     the IB Gateway check M1 ran first (it fired)
#
# Arm a: an empty scratch CODEX_HOME. Arm b: a scratch CODEX_HOME filled by
#   omx setup --scope user --install-mode legacy --mcp none
# with HOME, CODEX_HOME and the working folder all throwaway. <clone>: one fresh standalone clone
# of the repository at main 9c5daaa, the same path for both arms. The raw renders are not in the
# repository: they hold home-directory paths. The original script also built M1's flag list
# (unused by M2) and read its folders from a sourced helper; both are left out here.
set -u

P='Reply with exactly the word OK. Do not run any command or call any tool.'

render() {
  local label=$1 H=$2 WT=$3 OUT=$4 n
  mkdir -p "$OUT"
  for n in 1 2 3; do
    CODEX_HOME="$H" codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust \
      -C "$WT" -m gpt-6-astra -c model_reasoning_effort=high \
      -c "projects={\"$WT\"={trust_level=\"trusted\"}}" debug prompt-input "$P" \
      < /dev/null > "$OUT/prompt-$label-$n.json" 2> "$OUT/prompt-$label-$n.stderr"
    echo "$label-$n exit=$? msg_bytes=$(jq '[.[]|select(.type=="message")|.content[]|.text|utf8bytelength]|add' "$OUT/prompt-$label-$n.json") tool_bytes=$(jq '[.[]|select(.type=="additional_tools")|.tools|tojson|utf8bytelength]|add // 0' "$OUT/prompt-$label-$n.json")"
  done
}

# Message parts (index, role, part, bytes), tool groups (name, JSON bytes), spawn_agent's
# parameters (name, JSON bytes), then sha256 of all message texts (joined by newlines) and of the
# tool declarations: the parts M2 counts. The raw files also differ in item ids and metadata.
split() {
  local f=$1
  jq -r '[.[]|select(.type=="message")]|to_entries[]|.key as $i|.value.role as $r
    |.value.content|to_entries[]|["message", $i, $r, .key, (.value.text|utf8bytelength)]|@tsv' "$f"
  jq -r '.[]|select(.type=="additional_tools")|.tools[]|["tool", .name, (tojson|utf8bytelength)]|@tsv' "$f"
  jq -r '.[]|select(.type=="additional_tools")|.tools[]|select(.name=="collaboration")|.tools[]
    |select(.name=="spawn_agent")|.parameters.properties|to_entries[]
    |["spawn_agent.parameter", .key, (.value|tojson|utf8bytelength)]|@tsv' "$f"
  printf 'messages_sha256\t%s\n' "$(jq -j '[.[]|select(.type=="message")|.content[]|.text]|join("\n")' "$f" | sha256sum | cut -d' ' -f1)"
  printf 'tools_sha256\t%s\n' "$(jq -j '[.[]|select(.type=="additional_tools")|.tools|tojson]|join("")' "$f" | sha256sum | cut -d' ' -f1)"
}

# Entries of the role list in spawn_agent's agent_type parameter, which only arm b has.
roles() {
  jq -r '.[]|select(.type=="additional_tools")|.tools[]|select(.name=="collaboration")|.tools[]
    |select(.name=="spawn_agent")|.parameters.properties.agent_type.description // ""' "$1" |
    python3 -I -c '
import re, sys
t = sys.stdin.read().rstrip("\n")
i = t.find("Available roles")
print("characters", len(t), "header", i)
for m in re.finditer(r"(?ms)^([A-Za-z0-9_-]+): \{\n.*?\n\}", t[i:] if i >= 0 else ""):
    print(m.group(1), len(m.group(0)))
'
}

# M1's check before each run. At 02:07 ET it printed GATEWAY-UP with nothing listening on 4002:
# pgrep -f matched another agent's command line, which carried the deny rule Bash(*ibgateway*).
guard() {
  [ "$(ss -Hltn 'sport = :4002' | wc -l)" = 0 ] && ! pgrep -f ibgateway >/dev/null || { echo GATEWAY-UP; exit 3; }
}

"$@"
