#!/usr/bin/env bash
# ab-dsh.sh PROFILE RUNDIR WORKDIR [dsh launcher flags and app args...]
#   stdin = the task (use "-" as the task argument), stdout/stderr = dsh's own.
# Runs dsh 0.2.2-rc.1 for one temporary "ab-" profile of the owner's dsh home, inside a mount
# namespace where that home is read-only except the profile folder itself. dsh loads its own
# $DSH_HOME/.env itself (packages/boot/app-boot/src/index.ts L236-257 at dsh-v0.2.2-rc.1);
# this script never opens, copies or exports it, and it removes any inherited DEEPSEEK_API_KEY.
# Bounds: AB_TIMEOUT seconds (default 1800), AB_KILL_AFTER seconds (default 60).
# Optional, off unless set (the scout's smoke run did not use them):
#   AB_HIDE   colon-separated absolute paths that become an empty folder (or empty file) inside
#             the namespace, e.g. /mnt:/run/WSL (Windows drives, Windows interop) or the real home.
#             Nothing in the dsh home can be named: the key file is never touched.
#   AB_SHOW   colon-separated absolute paths made visible again, read-only, after AB_HIDE
#             (with the real home hidden, $HOME/.local is needed: dsh, uv and pnpm live there).
#             RUNDIR and WORKDIR are always made visible again, read-write.
#   AB_CHECK=1  run no dsh profile: print what the namespace looks like and exit.
set -euo pipefail
p=$1 ev=$2 wd=$3; shift 3
case "$p" in ab-*) ;; *) echo "ab-dsh: profile name must start with ab-" >&2; exit 64 ;; esac
real=$(getent passwd "$(id -un)" | cut -d: -f6)   # the account's home, even when HOME is overridden
dh="$real/.dsh"; pd="$dh/profiles/$p"
[ -f "$pd/package.json" ] || { echo "ab-dsh: $pd is not a profile" >&2; exit 66; }
[ ! -e "$wd/.env" ] || { echo "ab-dsh: $wd/.env exists; it would outrank the home layer" >&2; exit 65; }
case "$ev/tmp/" in "$wd"/*) echo "ab-dsh: TMPDIR must lie outside the work folder" >&2; exit 67 ;; esac
install -d -m 0700 "$ev/home" "$ev/agents-home" "$ev/tmp" "$ev/sessions" "$ev/storages"
pre=() post=() hidden=()
if [ -n "${AB_HIDE:-}" ]; then
  IFS=: read -r -a hs <<<"$AB_HIDE"
  for h in "${hs[@]}"; do
    [ -n "$h" ] || continue
    case "$h" in /*) ;; *) echo "ab-dsh: AB_HIDE takes absolute paths" >&2; exit 68 ;; esac
    case "$h/" in "$dh"/*) echo "ab-dsh: AB_HIDE must not name $dh or anything in it" >&2; exit 68 ;; esac
    if [ -d "$h" ]; then pre+=(--tmpfs "$h"); hidden+=("$h")
    elif [ -e "$h" ]; then pre+=(--ro-bind /dev/null "$h"); hidden+=("$h"); fi
  done
  IFS=: read -r -a ss <<<"${AB_SHOW:-}"
  for s in "${ss[@]}"; do if [ -n "$s" ] && [ -e "$s" ]; then post+=(--ro-bind "$s" "$s"); fi; done
  post+=(--bind "$ev" "$ev" --bind "$wd" "$wd")
fi
ns=(bwrap --dev-bind / / "${pre[@]}" --ro-bind "$dh" "$dh" --bind "$pd" "$pd" "${post[@]}" --die-with-parent --)
cd "$wd"
if [ "${AB_CHECK:-}" = 1 ]; then
  exec "${ns[@]}" bash -c '
    dh=$1; pd=$2; shift 2
    echo "dsh home mount: $(findmnt -no OPTIONS --target "$dh" | cut -d, -f1); writable: $([ -w "$dh" ] && echo YES || echo no)"
    echo "profile mount: $(findmnt -no OPTIONS --target "$pd" | cut -d, -f1); writable: $([ -w "$pd" ] && echo yes || echo NO)"
    for h in "$@"; do if [ -d "$h" ]; then echo "hidden $h: $(ls -A "$h" | wc -l) entries"; else echo "hidden $h: $(wc -c <"$h") bytes"; fi; done
    echo "cwd: $(pwd); dsh --version: $(dsh --version </dev/null 2>&1 | head -n 1)"
  ' _ "$dh" "$pd" "${hidden[@]}"
fi
exec "${ns[@]}" \
  env -u DSH_PERMISSION_MODE -u DEEPSEEK_API_KEY -u DSH_SYSTEM_PROMPT -u DSH_TELEMETRY_MODE \
      -u DSH_TELEMETRY_OTLP_URL \
    HOME="$ev/home" DSH_HOME="$dh" DSH_AGENTS_HOME="$ev/agents-home" DSH_TELEMETRY_DISABLED=1 \
    TMPDIR="$ev/tmp" DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic \
  timeout --signal=INT --kill-after="${AB_KILL_AFTER:-60}" "${AB_TIMEOUT:-1800}" \
  dsh --profile "$p" "$@"
