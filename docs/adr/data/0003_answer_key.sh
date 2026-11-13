#!/usr/bin/env bash
# Published copy (docs/adr/data/0003_answer_key.sh): ran on 2026-11-13 as scripts/answer_key.sh in the operator's
# work folder, written here as $WORK (a Windows temp folder, seen from WSL under /mnt/c; set WORK
# before running); the operator's home directory is written as $HOME. Otherwise unchanged.
# Gather registry and advisory data for the R5 answer key (public endpoints, no auth).
# Output: ~/src/meridian-ab/0003/answer-key/
set -u
K="$HOME/src/meridian-ab/0003/answer-key"; mkdir -p "$K/npm" "$K/pypi" "$K/osv"
UA='User-Agent: ab-answer-key/0.1'
PYPI="colorama 0.4.6
iniconfig 2.3.1
nautilus-trader 2.0.0rc9
nodeenv 1.12.0
nodejs-wheel-binaries 24.19.0
packaging 26.3
pluggy 1.7.0
pygments 2.21.0
pyright 1.1.414
pytest 9.2.0
ruff 0.17.3
typing-extensions 4.16.0"
NPM="@openai/codex 0.167.2
@openai/codex 0.167.2-linux-x64
pnpm 11.28.9
@deepseek-ai/dsh 0.2.2-rc.1
@deepseek-harness-tui/dsh-tui 0.20.0
@deepseek-ai/dsh-hooks-claude-code 0.2.2-rc.1
@deepseek-ai/dsh-hook-protocol 0.2.2-rc.1"

# OSV: versioned and unversioned queries in one batch
{
  echo "$PYPI" | while read -r n v; do printf '{"package":{"ecosystem":"PyPI","name":"%s"},"version":"%s"}\n' "$n" "$v"; printf '{"package":{"ecosystem":"PyPI","name":"%s"}}\n' "$n"; done
  echo "$NPM" | grep -v linux-x64 | while read -r n v; do printf '{"package":{"ecosystem":"npm","name":"%s"},"version":"%s"}\n' "$n" "$v"; printf '{"package":{"ecosystem":"npm","name":"%s"}}\n' "$n"; done
} | jq -s '{queries:.}' > "$K/osv/query.json"
curl -sS -H "$UA" -H 'Content-Type: application/json' --data @"$K/osv/query.json" https://api.osv.dev/v1/querybatch > "$K/osv/result.json"
jq -r --slurpfile q "$K/osv/query.json" '.results as $r | range(0; $r|length) as $i | "\($q[0].queries[$i].package.ecosystem)\t\($q[0].queries[$i].package.name)\t\($q[0].queries[$i].version // "ALL")\t\([($r[$i].vulns // [])[].id] | length)\t\([($r[$i].vulns // [])[].id] | join(","))"' "$K/osv/result.json" > "$K/osv/summary.tsv"

# PyPI per-version JSON
echo "$PYPI" | while read -r n v; do
  curl -sS -H "$UA" "https://pypi.org/pypi/$n/$v/json" > "$K/pypi/$n-$v.json"
  jq -c --arg n "$n" --arg v "$v" '{name:$n, version:$v, yanked:.info.yanked, yanked_reason:.info.yanked_reason, upload:([.urls[].upload_time_iso_8601]|min), files:([.urls[].packagetype]|group_by(.)|map({(.[0]):length})|add), vulns:[.vulnerabilities[]?.id], requires_dist:.info.requires_dist, license:(.info.license_expression // .info.license), project_urls:.info.project_urls}' "$K/pypi/$n-$v.json"
done > "$K/pypi/summary.jsonl"

# npm: per-version document and packument facts
echo "$NPM" | while read -r n v; do
  enc=$(printf '%s' "$n" | sed 's#/#%2F#')
  f=$(printf '%s' "$n" | tr '/@' '__')
  curl -sS -H "$UA" "https://registry.npmjs.org/$enc/$v" > "$K/npm/$f-$v.json"
  curl -sS -H "$UA" "https://registry.npmjs.org/$enc" | jq --arg v "$v" '{name, distTags:."dist-tags", maintainers, created:.time.created, modified:.time.modified, published:.time[$v], deprecated_pkg:.deprecated, repository, license, nversions:(.versions|length)}' > "$K/npm/$f-$v.packument.json"
  jq -c --arg n "$n" --arg v "$v" --slurpfile p "$K/npm/$f-$v.packument.json" '{name:$n, version:$v, published:$p[0].published, latest:$p[0].distTags.latest, distTags:$p[0].distTags, maintainers:[$p[0].maintainers[]?.name], npmUser:._npmUser.name, deprecated:.deprecated, scripts:(.scripts // {} | with_entries(select(.key|test("install|prepare")))), hasInstallScript:.hasInstallScript, integrity:.dist.integrity, attestations:(.dist.attestations != null), provenance_type:(.dist.attestations.provenance.predicateType // null), deps:(.dependencies // {}), optdeps:(.optionalDependencies // {} | keys), peer:(.peerDependencies // {} | keys), bin:.bin, license:.license, repository:.repository.url, nversions:$p[0].nversions, created:$p[0].created}' "$K/npm/$f-$v.json"
done > "$K/npm/summary.jsonl"
ls -la "$K" "$K/osv"; cat "$K/osv/summary.tsv"
