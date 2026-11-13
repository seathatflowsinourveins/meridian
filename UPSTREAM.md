# Upstream register

Every tool this repo installs or integrates has a row here: what it is, the exact version or
commit, the page it was read from, the date it was read, and what it is used for.
"upstream" means the thing is used as its maintainers ship it. "own design" means it was written
here and no upstream ships it.

A row is added in the same commit that adds the tool. Versions are taken from the running distro
or the lockfile, not from memory. Transitive Python packages are pinned with hashes in `uv.lock`.

## Distro (`deploy/wsl/`)

| Component | Version or commit | Source URL (read) | Date read | Used for | Origin |
|---|---|---|---|---|---|
| WSL (already on the host, not installed by this repo) | 3.0.3.0 | `wsl --help` and `wsl --version` on this machine; https://learn.microsoft.com/windows/wsl/basic-commands | 2026-11-12 | the commands in the header of `deploy/wsl/meridian.user-data`: `--install --name --location --vhd-size --no-launch`, `-d <distro> -u root`, `--terminate`, `--set-default` | upstream |
| Ubuntu WSL image | Ubuntu 26.04.1 LTS (resolute), installed as `Ubuntu-26.04` | https://documentation.ubuntu.com/wsl/stable/howto/cloud-init/ | 2026-11-12 | the `meridian` distro | upstream |
| cloud-init, WSL datasource | 26.1-0ubuntu3~26.04.1 (in the image) | https://cloudinit.readthedocs.io/en/latest/reference/datasources/wsl.html | 2026-11-12 | applies `deploy/wsl/meridian.user-data` on first boot, looked up as `%USERPROFILE%\.cloud-init\meridian.user-data` | upstream |
| `/etc/wsl.conf` keys | n/a (WSL 3.0.3.0) | https://learn.microsoft.com/windows/wsl/wsl-config | 2026-11-12 | `[boot] systemd=true`, `[user] default`, `[interop] appendWindowsPath=false`, `[time] useWindowsTimezone=false` | upstream |
| cloud-init `timezone` key | cloud-init 26.1 | checked with `cloud-init schema --config-file` on the installed cloud-init; https://cloudinit.readthedocs.io/en/latest/reference/datasources/wsl.html | 2026-11-12 | the distro's time zone is America/New_York by definition, not inherited from Windows | upstream |
| apt packages | installed by the definition: gh 2.46.0-4, build-essential 12.12ubuntu2.26.04.2, jq 1.8.1-4ubuntu2, unzip 6.0-29ubuntu1. In the image already (dpkg log: installed 2026-08-27, when the image was built): git 1:2.53.0-1ubuntu1.1, curl 8.18.0-1ubuntu2.8 | https://packages.ubuntu.com/resolute/ ; `/var/log/dpkg.log` in the distro | 2026-11-12 | base tools named in the plan. apt's default applies, so recommended packages come too | upstream |
| Node.js | v24.22.3 (LTS "Krypton"), `node-v24.22.3-linux-x64.tar.xz`, sha256 `4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb` | https://nodejs.org/dist/v24.22.3/SHASUMS256.txt ; https://nodejs.org/dist/index.json | 2026-11-12 | pinned Node >= 18.18 for the agent CLIs of the next sitting; nothing in this repo runs on it yet | upstream |
| uv | 0.13.7, installer sha256 `d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4` | https://astral.sh/uv/0.13.7/install.sh ; https://docs.astral.sh/uv/getting-started/installation/ ; https://github.com/astral-sh/uv/releases/tag/0.13.7 | 2026-11-12 | Python project, lockfile, managed CPython. Installed with `UV_NO_MODIFY_PATH=1` (read in that installer script), so no shell file is edited; Ubuntu's default `~/.profile` puts `~/.local/bin` on PATH | upstream |
| Claude Code setting `disableClaudeAiConnectors` | n/a | https://code.claude.com/docs/en/settings | 2026-11-12 | set to `true` in `~/.claude/settings.json` so claude.ai connectors (including an Interactive Brokers one) do not load in Claude Code started in the distro. Set twice: in the owner's `~/.claude/settings.json` and machine-wide in `/etc/claude-code/managed-settings.json`, which also holds when a tool starts Claude Code with its own config home. It does not cover connectors the Claude desktop app itself attaches to a session | upstream |
| Claude Code managed settings path on Linux and WSL | n/a | https://code.claude.com/docs/en/managed-settings.md | 2026-11-12 | where the machine-wide copy of that setting lives | upstream |
| apt packages for the IB Gateway window | libgtk-3-0t64 3.24.52-0ubuntu1, libnss3 2:3.120-1ubuntu2.2, libnspr4 2:4.38.2-1ubuntu1, libasound2t64 1.2.15.3-1ubuntu1.1, libatk1.0-0t64 2.60.4-0ubuntu0.1, libatk-bridge2.0-0t64 2.60.4-0ubuntu0.1, libatspi2.0-0t64 2.60.4-0ubuntu0.1, libcups2t64 2.4.16-1ubuntu1.3, xdg-utils 1.2.1-2ubuntu2 | https://teamdev.com/jxbrowser/docs/guides/introduction/requirements/ (the browser component on the Gateway's classpath); https://packages.ubuntu.com/resolute/ | 2026-11-12 | IBKR publishes no Linux package list, so this list is an inference from that component's requirements. Checked by starting the installed Gateway under WSLg: it was still running after 35 seconds, with no error in its output (not logged in) | upstream |
| Ubuntu Insights consent (in the image, not installed by this repo) | ubuntu-insights 0.9.3ubuntu | `ubuntu-insights --help` and `ubuntu-insights consent --help` in the distro; `/usr/lib/wsl/ubuntu-insights.sh` in the image; https://raw.githubusercontent.com/ubuntu/ubuntu-insights/main/README.md | 2026-11-12 | recorded as "no" for the owner user, the way Ubuntu's own WSL script records a "no". Per the README, a declined client sends only `{"OptOut": true}`. The Windows registry value that script can also write is left alone | upstream |
| Ubuntu Insights timers (in the image) | `ubuntu-insights-collect.timer`, `ubuntu-insights-upload.timer`, ubuntu-insights 0.9.3ubuntu | `/usr/lib/systemd/user/` in the image; `systemctl --user cat` of both | 2026-11-12 | the image enables both for every user by preset; the definition disables them with `systemctl --global disable`, and `setup.sh check` verifies it | upstream |
| cloud-init `users` keys `homedir`, `no_create_home`; `package_upgrade` | cloud-init 26.1 | checked with `cloud-init schema --config-file` on the installed cloud-init; https://cloudinit.readthedocs.io/en/latest/reference/modules.html | 2026-11-12 | the `paper` service user has no home (`/nonexistent`); packages are brought up to date on first boot | upstream |
| systemd lingering for the owner (`loginctl enable-linger apoth`) | systemd in the image | `orca-ide serve service install --help` in the distro ("the service stops at logout unless lingering is on") | 2026-11-12 | the Orca server, a user service, runs without a login session | upstream |
| `deploy/wsl/meridian.user-data`, `deploy/wsl/setup.sh` | this repo | n/a | 2026-11-12 | the distro definition and the user-level setup steps | own design |

## Agent runtimes (`deploy/wsl/setup.sh agents`)

By the owner's decision of 2026-11-12 the agent runtimes update themselves where the tool can,
and each was installed at its newest release. The 7-day wait for new releases applies to the
Python dependencies only (`pyproject.toml`). A pin here is the release a rebuilt distro starts
from, checked against the publisher's checksum before anything runs; `setup.sh agents-check`
accepts that version or newer. Sign-ins are the owner's.

| Component | Version or commit, checksum | Licence | Source URL (read) | Date read | Used for | Origin |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.322; linux-x64 sha256 `bfb3703ad5380242328459bc62ada4bde8ae7ba57c6e1eeadb9c00e08874c478`, listed in the release manifest signed by Anthropic's key `31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE` | proprietary (Anthropic Commercial Terms) | https://code.claude.com/docs/en/setup.md ; https://downloads.claude.ai/claude-code-releases/2.1.322/manifest.json ; https://code.claude.com/docs/en/legal-and-compliance.md | 2026-11-12 | the lead agent. 2.1.321 is the first release that runs `claude-fable-5-2`. The pinned binary installs itself (`claude install`); `install.sh` is not used because it runs the newest release to do the install. Updates itself on the `latest` channel, never below 2.1.322 | upstream |
| Claude Code settings (`~/.claude/settings.json`) | Claude Code 2.1.322 | n/a | https://code.claude.com/docs/en/settings-reference.md ; https://code.claude.com/docs/en/permission-modes.md ; https://code.claude.com/docs/en/model-config.md | 2026-11-12 | `model` `claude-fable-5-2` with `modelSettings` effort `high`; `permissions.defaultMode` `bypassPermissions` and `skipDangerousModePermissionPrompt` (the owner's bypass choice); `syncClaudeAiSkills` and `syncClaudeAiPlugins` `false`, because a synced plugin can bring MCP servers that `disableClaudeAiConnectors` does not cover; `autoUpdatesChannel` `latest` with `minimumVersion`; deny rules for `risk/`, `*.contract.json` and `.env`. Merged into the file, so Orca's hooks stay | upstream |
| Codex CLI | 0.167.2 (tag `rust-v0.167.2`); npm `@openai/codex` integrity `sha512-6OFkr2ndzTdFb32OEiUlM9BgpeY8+wnMe8vRhuvt+22TnxVR39KnJ22Ghay98IY9OmEltoNgFN4GALUkxFQCOw==`, its linux-x64 build `sha512-2Rw3VkWonMxwCSgOw+NkiKLOuOzyoQNWmxU7x8GniesdMfhKc4asNqOzTgQwJLKCrSlPc4/6fYTaH7fYcuGWGQ==` | Apache-2.0 | https://registry.npmjs.org/@openai/codex ; https://github.com/openai/codex/releases/tag/rust-v0.167.2 ; https://github.com/openai/codex/tree/rust-v0.166.0/docs | 2026-11-12 | worker and reviewer (`gpt-6-astra`; `codex -m gpt-6.1-sol` for bulk work). Updates itself two ways, both left on: it offers an update at start (`check_for_update_on_startup`), and a plain interactive start runs its own daemon, whose updater installs the newest release from `https://chatgpt.com/codex/install.sh` into `~/.codex/packages` (Orca's launches skip both) | upstream |
| Codex settings (`~/.codex/config.toml`) | keys read in `codex-rs/core/config.schema.json` at `rust-v0.166.0`; loaded without error by 0.167.2 (`codex login status`, `codex features list`) | n/a | https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/core/config.schema.json | 2026-11-12 | `model`, `model_reasoning_effort` `high`, `approval_policy` `never` with `sandbox_mode` `danger-full-access` (bypass), `[features] apps = false` (ChatGPT account connectors off, as for Claude Code: with apps on, a signed-in Codex registers a hosted `codex_apps` MCP server), `plugins = false` and `skill_mcp_dependency_install = false` (no plugin, and no MCP server a skill asks for, until an evidence record adds one), `[analytics]` and `[feedback]` off, `[otel] metrics_exporter = "none"`, no `[mcp_servers]`. Orca adds its hook and project tables | upstream |
| Antigravity CLI (`agy`) | 1.5.7; release asset `agy_cli_linux_x64.tar.gz` sha256 `d6150a8d2a9e29a3d171b2325d6f66b6e7059628f4799a20c069b8ed8f78fdbb`; the binary inside sha256 `5df525a2d6908989c57b897723caea66e00d7c4d2e24411f91ad306989574642` | proprietary (no licence file; Google Antigravity Additional Terms of Service) | https://antigravity.google/docs/getting-started.md ; https://antigravity.google/docs/cli/troubleshooting.md ; https://antigravity.google/cli/install.sh (read, not run) ; https://github.com/google-antigravity/antigravity-cli/releases/tag/1.5.7 ; https://antigravity.google/terms | 2026-11-12 | worker and reviewer. The asset Google's `install.sh` downloads, unpacked by hand: the script always takes the newest release and then edits shell profiles. Updates itself in the background. No MCP server, plugin or Gemini CLI config | upstream |
| DeepSeek Harness (`dsh`) | 0.2.2-rc.1 (npm `latest`; tag `dsh-v0.2.2-rc.1`, commit `66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db`); integrity `sha512-ijR9UEVYkG15Q/Q79JzvzLBzQOQfc63VLr9n6flpwHPhr5IKn2UxthnSoto/P9l7qGd7pPvI1Ra6TW7LH3oKpg==` | MIT (some sub-packages carry their own licence) | https://github.com/deepseek-ai/deepseek-harness ; https://registry.npmjs.org/@deepseek-ai/dsh | 2026-11-12 | mechanical tasks; a developer preview without a security audit. Installed with `--strict-allow-scripts`: only `node-pty`, `koffi`, `@deepseek-ai/dsh-subprocess-local`, `@google/genai` and `protobufjs` may run install scripts | upstream |
| pnpm | 11.28.9 (`latest-11`; dsh pins the 11 line); integrity `sha512-NUIc6icg7KP1rXIrZ+jvGPTTzUdF7S/P6w3CiNTpQ3+tOHDZHuboPyaPD29+D2JyMxexlhe7Re5DMxcu9RFZ+A==` | MIT | https://registry.npmjs.org/pnpm | 2026-11-12 | what `dsh plugin` installs profiles with. The profile sets no `minimumReleaseAge`: under pnpm's default a release younger than a day still installs and is recorded under `minimumReleaseAgeExclude`. Every `dsh plugin add` runs with stdin closed, so pnpm cannot stop at a question | upstream |
| dsh-tui | 0.20.0; integrity `sha512-04K4E9nGBiefTerV2SaRjLYcDRGjwYXVNL0+tH/FCEdRhTnVDwMEADyC3a/etQ/NzoM2Sh1B+inb23T5Aqxcqw==` | MIT | https://github.com/ccch1mneyyy/dsh-TUI ; https://registry.npmjs.org/@deepseek-harness-tui/dsh-tui ; Orca `src/shared/agent-launch/catalog/tui-agent-config.ts` at v1.4.250 | 2026-11-12 | the terminal UI Orca launches for DeepSeek Harness (`dsh-tui .`), which Orca requires. A community package from a personal account, not DeepSeek's. 0.18.0 and 0.19.0 were read; 0.20.0 was compared with 0.19.0: no new URL, launcher unchanged, changes in credential-reference handling and notifications. Installed in its own dsh profile, plus the launcher on PATH | upstream |
| DeepSeek Harness hook packages | `@deepseek-ai/dsh-hooks-claude-code` and `@deepseek-ai/dsh-hook-protocol` 0.2.2-rc.1, the engine's version (their npm `latest` is an older line) | MIT (at 0.2.2-rc.1; the registry's top-level BSD-3-Clause belongs to the old line) | https://registry.npmjs.org/@deepseek-ai/dsh-hooks-claude-code ; Orca's status text for DSH profiles at v1.4.250 | 2026-11-12 | let Orca's status hooks load in the `dsh-tui` profile | upstream |
| DeepSeek Harness home patch (`~/.dsh/cordis.patch.yml`) | rows `session-log-deepseek` and `plugin-package-inventory-deepseek` (`enabled: false`), `session-telemetry-otel` (`mode: DISABLED`) | n/a | plugin config schemas at tag `dsh-v0.2.2-rc.1`; checked with `dsh --profile dsh-tui --dump-config` | 2026-11-12 | stops the session-log and plugin-inventory uploads to DeepSeek and the OTel feedback upload, all on by default. Orca appends its own marked hooks block | upstream |
| Orca server | 1.4.257 (tag commit `b0570d90fc9af8c9e7e3566c0fb841d0884e2462`); `orca-server-linux-x64.tar.gz` sha256 `72f42c1f5e66d828375d70a54fda5a5f910b90471948d93eedbc3a9ed19bc840` (the release's checksum file); bundles Node 24.22.1 and ripgrep | MIT | https://github.com/stablyai/orca/releases/tag/v1.4.257 ; `orca-ide serve --help`, `serve service install --help` and `pair --help` from that build | 2026-11-12 | the Orca runtime in the distro, with the Windows app as its window: user service `orca-serve` with `--bind 127.0.0.1 --port 6790 --refuse-public`, telemetry off (`ORCA_TELEMETRY_DISABLED=1`). It does not update itself; a new pin in `setup.sh` does. The Windows app (1.4.255) is in the same runtime protocol range. Checked by creating a worktree per agent through it | upstream |
| Orca skills `orca-cli`, `orchestration` | from Orca 1.4.257: git blobs `3b201f777ad807d104e8f87893f1e980f236c6c9` and `8083c49535c17311585c7bffd177a8683464de46` | MIT (`.agents/skills/NOTICE.md`) | https://github.com/stablyai/orca/tree/v1.4.257/skills ; `orca-ide skills install --help` | 2026-11-12 | written to `.agents/skills/` (Codex, Antigravity and DeepSeek Harness read it) with relative links in `.claude/skills/` by `orca-ide skills install --skill orca-cli --skill orchestration --local`; `tests/test_skills_layout.py` checks both. Each stub loads the guide of the installed Orca (`orca-ide skills get`) | upstream |
| Orca `orca.yaml`, `.worktreeinclude` | Orca 1.4.257 format | n/a | https://github.com/stablyai/orca/blob/v1.4.257/docs/site/content/docs/model/orca-yaml.mdx | 2026-11-12 | `scripts.setup` (`uv sync --locked`), `setupAgentStartupPolicy: wait-for-setup`, `defaultTabs`. `.worktreeinclude` lists nothing, on purpose (its comments say why). Setup exited 0 in each of three worktrees Orca created | upstream |
| openai/codex-plugin-cc (Claude Code plugin) | first installed at commit `db52e28f4d9ded852ab3942cea316258ae4ef346` (tag `v1.0.6`, plugin 1.0.6, tree `plugins/codex` `6008c0a418894220e89c2c9e4dc8b5d3c1a2ce4c`) | Apache-2.0 | https://github.com/openai/codex-plugin-cc/tree/v1.0.6 ; https://code.claude.com/docs/en/plugins/marketplace-reference.md | 2026-11-12 | `/codex:review` before merge. User scope; follows the default branch (`autoUpdate`, the owner's choice). Its automatic review gate (a Stop hook) stays off: only `/codex:setup --enable-review-gate` turns it on, and `agents-check` fails if it is on. Its `codex:codex-rescue` subagent can hand Codex write work | upstream |
| npm settings | npm 11.19.1: `prefix`, `--strict-allow-scripts`, `--allow-scripts` | n/a | `lib/node_modules/npm/docs/content/using-npm/config.md` in the distro's Node | 2026-11-12 | global installs, and the tools' own updates, go to `~/.local` with no sudo; an install fails if a package outside the allow-list has install scripts | upstream |

Notes on the agent runtimes:

- **Orca's defaults are kept.** Agents start in bypass mode (`--dangerously-skip-permissions`,
  `--dangerously-bypass-approvals-and-sandbox`), Orca writes its status hooks into each agent's
  own configuration and pre-trusts each worktree. `orca-ide agent hooks off` removes the hooks.
- **Loopback only.** With mirrored networking a listener on every interface is reachable from
  the network, so the server binds 127.0.0.1 and refuses public addresses, and
  `agents-check` fails if any socket of the service listens elsewhere. The Windows app reaches
  it at `ws://127.0.0.1:6790`. `orca-ide pair` would first open the server to the network (the
  service refuses), so the owner pairs once with `setup.sh orca-pair`, a foreground run on
  loopback. A headless pairing link does not expire and grants shell access as the owner: it is
  printed to the owner's terminal only, never logged or committed.
- **Orca and sign-ins.** Orca's docs say it reads the existing Claude Code login to ask
  Anthropic for usage figures when a window is focused. That is Orca's own feature, not set up
  here; whether to keep it is the owner's decision.
- **No account-linked tools.** claude.ai connectors and synced plugins (Claude Code) and ChatGPT
  apps (Codex) are off, so no account connector, a broker one included, reaches an agent here.
- **Subscription sign-ins stay in their own tools.** `dsh-tui` offers to sign in with ChatGPT,
  Claude or Grok subscriptions; that is not used here (Anthropic's terms forbid third-party
  tools routing requests through plan credentials). DeepSeek Harness uses a DeepSeek API key.
- **Antigravity's terms** call third-party software that accesses the service a breach, and its
  FAQ says wrapping `agy` inside third-party applications is not supported on consumer plans.
  Orca runs the official binary in its terminal and reads its usage; whether that is acceptable
  is the owner's decision.

## Trading (IBKR paper lane, milestone M1)

| Component | Version or commit | Source URL (read) | Date read | Used for | Origin |
|---|---|---|---|---|---|
| NautilusTrader | 2.0.0rc9 from PyPI (tag `v2.0.0rc9`, commit `da6b57aefdd62b44f675e434ffcfefca7f4025dd`), licence LGPL-3.0-only; wheel hashes in `uv.lock` | https://pypi.org/pypi/nautilus_trader/2.0.0rc9/json ; https://github.com/nautechsystems/nautilus_trader/releases/tag/v2.0.0rc9 | 2026-11-12 | the engine: live node, Interactive Brokers adapter, startup reconciliation | upstream |
| NautilusTrader IB integration guide and reconciliation concept | at tag `v2.0.0rc9` | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/v2.0.0rc9/docs/integrations/interactive_brokers.md ; https://raw.githubusercontent.com/nautechsystems/nautilus_trader/v2.0.0rc9/docs/concepts/execution/reconciliation.md | 2026-11-12 | ports, client ids, what startup reconciliation does and when it aborts | upstream |
| `upstream/.../interactive_brokers/_common.py` | git blob `c3ce3319514926dbbe29d46dd458168dfd385d79` at the tag commit | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/da6b57aefdd62b44f675e434ffcfefca7f4025dd/examples/live/interactive_brokers/_common.py | 2026-11-12 | `build_ib_live_node`, `instrument_provider_config`, `schedule_node_stop`, `default_aapl_instrument_id`. Verbatim copy | upstream |
| `upstream/.../interactive_brokers/ib_v2_order_strategies.py` | git blob `80c8bcca0eca0ea2b76714c3af67a2406d6c4885` at the tag commit | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/da6b57aefdd62b44f675e434ffcfefca7f4025dd/examples/live/interactive_brokers/ib_v2_order_strategies.py | 2026-11-12 | `IbV2OrderStrategy`: waits for a quote, submits once, cancels on acceptance, cancels its own orders on stop. Its close-on-stop is switched off by the lane. Verbatim copy | upstream |
| `upstream/nautilus_trader/v2.0.0rc9/LICENSE` | git blob `5550e2db15f239ea8d3cf54bfa3b035eab8d3174` at tag `v2.0.0rc9` (GitHub detects LGPL-3.0) | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/v2.0.0rc9/LICENSE | 2026-11-12 | the licence of the two vendored files (LGPL-3.0-only). Verbatim copy | upstream |
| `upstream/nautilus_trader/v2.0.0rc9/COPYING` (GPL-3.0 text) | sha256 `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` | https://www.gnu.org/licenses/gpl-3.0.txt | 2026-11-12 | the licence the LGPL adds its permissions to, shipped next to it as the LGPL asks | upstream |
| `upstream/nautilus_trader/v2.0.0rc9/NOTICE.md` | this repo | n/a | 2026-11-12 | names the source, version and licence of the vendored files | own design |
| Upstream example `notebooks/market_order_example.py` (read, not copied) | at the tag commit | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/da6b57aefdd62b44f675e434ffcfefca7f4025dd/examples/live/interactive_brokers/notebooks/market_order_example.py | 2026-11-12 | the pattern `meridian/ibkr_node.py` follows: subclass the base strategy, build the node with upstream's helper | upstream |
| CPython | 3.14.10, installed and managed by uv | https://docs.astral.sh/uv/concepts/python-versions/ | 2026-11-12 | the interpreter (`.python-version` is `3.14`) | upstream |
| uv settings `exclude-newer`, `exclude-newer-package` | uv 0.13.7 | https://docs.astral.sh/uv/reference/settings/ ; https://docs.astral.sh/uv/concepts/resolution/ | 2026-11-12 | 7-day cooldown on new releases, with `nautilus-trader` exempt by name | upstream |
| ruff | 0.17.3 | https://pypi.org/pypi/ruff/json | 2026-11-12 | lint and format | upstream |
| pyright (with `nodejs-wheel-binaries` 24.19.0) | 1.1.414 | https://pypi.org/pypi/pyright/json | 2026-11-12 | type check, with no download at run time | upstream |
| pytest | 9.2.0 | https://pypi.org/pypi/pytest/json | 2026-11-12 | tests | upstream |
| `actions/checkout` | v7.0.1, commit `3d3c42e5aac5ba805825da76410c181273ba90b1` | https://github.com/actions/checkout/releases/tag/v7.0.1 | 2026-11-12 | CI | upstream |
| `astral-sh/setup-uv` | v10.3.3, commit `68559e99cc807c1eb7e9238fd43a15bba460eec2` | https://github.com/astral-sh/setup-uv/releases/tag/v10.3.3 | 2026-11-12 | CI | upstream |
| gitleaks (CI only, not installed in the distro) | 8.30.1, `gitleaks_8.30.1_linux_x64.tar.gz`, sha256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` | https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_checksums.txt | 2026-11-12 | secret scan of the git history in CI | upstream |
| Dependabot (`uv` and `github-actions` ecosystems, `cooldown`) | n/a | https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference | 2026-11-12 | weekly update pull requests, 7-day cooldown | upstream |
| IBKR TWS API: managed accounts | n/a | https://www.interactivebrokers.com/docs/tws-api/doc/accounts/managed-accounts.md | 2026-11-12 | the Gateway sends the list of accounts it manages when a client connects; this is what the allowlist is checked against | upstream |
| IBKR Python API client source, read as text and not installed | `nautilus-ibapi` 10.45.1: `client.py`, `comm.py`, `message.py`, `server_versions.py` | https://pypi.org/project/nautilus-ibapi/10.45.1/ | 2026-11-12 | the wire constants `meridian/ib_probe.py` uses: `API\0` prefix, length-prefixed NUL-separated fields, `START_API` 71, `MANAGED_ACCTS` 15, text framing below protocol 201 | upstream |
| IB Gateway (installed by `deploy/wsl/setup.sh gateway`; logged in by the owner) | stable 10.50.1g, build 20261109 16:10:13; `ibgateway-stable-standalone-linux-x64.sh`, 342,194,063 bytes, sha256 `13dc8bb05cbcec8d1b0bb0b25748447cf85863fb4b94361f57fcd350f35c7a9c` (taken at download: IBKR publishes no checksum; its MD5 equals the server's ETag prefix). Bundles its own Java runtime (Zulu 25.0.2) | https://www.interactivebrokers.com/en/trading/ibgateway-latest.php?p=stable ; https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/version.json | 2026-11-12 | the paper session the lane connects to on 127.0.0.1:4002. Installed in `~/Jts/ibgateway/1050` | upstream |
| install4j installer options `-q`, `-dir` | install4j 12.0.5 (the version inside the Gateway installer) | https://www.ej-technologies.com/resources/install4j/help/doc/installers/options.html | 2026-11-12 | the unattended Gateway install in `setup.sh gateway`. IBKR documents only the interactive wizard | upstream |
| How the lane tells a paper login (no web rule found) | IB Gateway 10.50.1g on this machine; NautilusTrader docs at `v2.0.0rc9` | the Gateway's own state, read locally: `~/Jts/jts.ini` (`tradingMode` under `[Logon]` was rewritten to `p` at the owner's Paper Trading login, 16:38 ET) and the process's listening ports in `/proc`. The only web citation: https://raw.githubusercontent.com/nautechsystems/nautilus_trader/v2.0.0rc9/docs/integrations/interactive_brokers.md (its default-port table gives 4002 for a paper Gateway; its examples use `DU`-prefixed account codes; it states no id rule) | 2026-11-12 | the paper checks in `meridian/boundary.py`. The D-prefix account form is an observed convention, not a documented guarantee. A search of IBKR's own pages found no stated rule; that search was stopped before it finished, and pages it could not read were skipped | upstream |
| `meridian/boundary.py` | this repo | n/a | 2026-11-12 | fail-closed paper checks: jts.ini `tradingMode=p`, the Gateway listening on port 4002 only, exactly one account of the paper form, and the owner's optional allowlist in `risk/boundary.contract.json` on top; plus the owner's `contract` command, which prints a contract for the reported account after the owner types PAPER | own design |
| `meridian/ib_probe.py` | this repo | n/a | 2026-11-12 | asks the Gateway which accounts it manages; sends only the version handshake and `START_API` | own design |
| `meridian/ibkr_paper.py` | this repo | n/a | 2026-11-12 | the gate before the engine and again after the run, the owner's typed confirmation, and the scrubbed run record | own design |
| `meridian/ibkr_node.py` | this repo; it subclasses and calls the two upstream files above | n/a | 2026-11-12 | one DAY LIMIT order through upstream's base strategy, and the calls that feed the run record | own design |

## Notes on choices

- **Node 24 rather than 26.** Both are LTS lines with a release on 2026-11-10. v24 is the older
  line, picked so the agent CLIs installed next sitting are less likely to meet an unsupported
  runtime. This is a judgement, not an upstream recommendation. v26.13.1 would be
  sha256 `5c063e46bab0fbc1c17cc445d7ff129cbdcd0471be6ed83b6ab864f8143bc864`.
- **uv 0.13.7 rather than 0.13.8.** 0.13.8 was published on 2026-11-12, the day of this sitting.
  The project applies a 7-day cooldown to new releases, so the tool that enforces it is held to
  the same rule.
- **`gh` from the Ubuntu archive.** It is far behind GitHub's own releases. It is enough for
  sign-in, clone and pull requests. If a newer one is needed, use GitHub's apt repository and add
  a row here.
- **The engine is a release candidate.** Upstream says release candidates are for testing and
  not for real capital. That fits a paper-only harness; it also means the API can change between
  candidates, so the pin is exact.
- **The adapter does not check the account.** NautilusTrader 2.0.0rc9's Interactive Brokers
  adapter takes the configured account id on trust and never reads the Gateway's account list.
  That is why `meridian/ib_probe.py` and `meridian/boundary.py` exist and run first.
- **Upstream's order-placing examples were read and not used as they are.** `exec_tester.py`
  opens a futures position on start. The built-in `ExecTester` strategy does not cancel on
  acceptance, so its order reaches a terminal state only at stop, and it submits again if the
  order is rejected or cancelled during the run. `IbV2OrderStrategy` submits once and cancels
  on acceptance, which is what M1 needs.
- **A fill is a failure in this lane.** The adapter refuses reduce-only orders, so upstream's
  close-on-stop cannot close a position, and a plain market close would be a second order that
  M1 does not define. The lane switches close-on-stop off and reports a fill as a failed run.
- **The account check runs twice.** The adapter opens its own connections after the check, so
  the lane asks the Gateway again after the run and writes no evidence if the answer changed.
  It does not hold a connection open during the run.
- **Dependabot and uv.** `required-version` is not set in `pyproject.toml`, because Dependabot
  brings its own uv. uv is pinned where it is installed instead.
- **Upstream example files are LGPL-3.0.** They are kept verbatim with their headers, next to
  NautilusTrader's licence file, the GPL-3.0 text and a notice. No licence has been chosen for
  this repository's own code; that is the owner's decision.
- **This instance was brought to the definition by hand.** The running `meridian` distro was
  installed from an earlier version of `deploy/wsl/meridian.user-data`. Each later change to the
  definition was applied to it by hand on 2026-11-12: New York time, the machine-wide connector
  setting, the Gateway libraries, Ubuntu Insights consent and timers, the `paper` user's home
  entry, and undoing the uv installer's shell edits (backed up under `~/.cache/meridian/`). It has
  not been rebuilt from the definition since. `package_upgrade` has not been applied to it: 133
  package upgrades are pending until the Gateway session can be interrupted, and Ubuntu's
  unattended security upgrades stay on as the image ships them.
