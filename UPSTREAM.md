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
| apt packages | git 1:2.53.0-1ubuntu1.1, gh 2.46.0-4, build-essential 12.12ubuntu2.26.04.2, curl 8.18.0-1ubuntu2.8, jq 1.8.1-4ubuntu2, unzip 6.0-29ubuntu1 | https://packages.ubuntu.com/resolute/ | 2026-11-12 | base tools named in the plan | upstream |
| Node.js | v24.22.3 (LTS "Krypton"), `node-v24.22.3-linux-x64.tar.xz`, sha256 `4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb` | https://nodejs.org/dist/v24.22.3/SHASUMS256.txt ; https://nodejs.org/dist/index.json | 2026-11-12 | pinned Node >= 18.18 for the agent CLIs of the next sitting; nothing in this repo runs on it yet | upstream |
| uv | 0.13.7, installer sha256 `d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4` | https://astral.sh/uv/0.13.7/install.sh ; https://docs.astral.sh/uv/getting-started/installation/ ; https://github.com/astral-sh/uv/releases/tag/0.13.7 | 2026-11-12 | Python project, lockfile, managed CPython | upstream |
| Claude Code (native installer; **not installed yet**: `setup.sh claude` runs after the harvest of plan 8.3 is done or skipped) | 2.1.322 to be asked for at install; it updates itself afterwards | https://code.claude.com/docs/en/setup ; https://claude.ai/install.sh ; https://downloads.claude.ai/claude-code-releases/latest | 2026-11-12 | the lead agent in the distro | upstream |
| Claude Code setting `disableClaudeAiConnectors` | n/a | https://code.claude.com/docs/en/settings | 2026-11-12 | set to `true` in `~/.claude/settings.json` so claude.ai connectors (including an Interactive Brokers one) do not load in Claude Code started in the distro. Set twice: in the owner's `~/.claude/settings.json` and machine-wide in `/etc/claude-code/managed-settings.json`, which also holds when a tool starts Claude Code with its own config home. It does not cover connectors the Claude desktop app itself attaches to a session | upstream |
| Claude Code managed settings path on Linux and WSL | n/a | https://code.claude.com/docs/en/managed-settings.md | 2026-11-12 | where the machine-wide copy of that setting lives | upstream |
| apt packages for the IB Gateway window | libgtk-3-0t64 3.24.52-0ubuntu1, libnss3 2:3.120-1ubuntu2.2, libnspr4 2:4.38.2-1ubuntu1, libasound2t64 1.2.15.3-1ubuntu1.1, libatk1.0-0t64 2.60.4-0ubuntu0.1, libatk-bridge2.0-0t64 2.60.4-0ubuntu0.1, libatspi2.0-0t64 2.60.4-0ubuntu0.1, libcups2t64 2.4.16-1ubuntu1.3, xdg-utils 1.2.1-2ubuntu2 | https://teamdev.com/jxbrowser/docs/guides/introduction/requirements/ (the browser component on the Gateway's classpath); https://packages.ubuntu.com/resolute/ | 2026-11-12 | IBKR publishes no Linux package list, so this list is an inference from that component's requirements. Checked by starting the installed Gateway under WSLg: it was still running after 35 seconds, with no error in its output (not logged in) | upstream |
| Ubuntu Insights consent (in the image, not installed by this repo) | ubuntu-insights 0.9.3ubuntu | `ubuntu-insights --help` and `ubuntu-insights consent --help` in the distro; `/usr/lib/wsl/ubuntu-insights.sh` in the image; https://raw.githubusercontent.com/ubuntu/ubuntu-insights/main/README.md | 2026-11-12 | recorded as "no" for the owner user, the way Ubuntu's own WSL script records a "no". Per the README, a declined client sends only `{"OptOut": true}`. The Windows registry value that script can also write is left alone | upstream |
| Orca `orca.yaml` file format | v1.4.257, commit `b0570d90fc9af8c9e7e3566c0fb841d0884e2462` | https://github.com/stablyai/orca/blob/v1.4.257/docs/site/content/docs/model/orca-yaml.mdx | 2026-11-12 | `orca.yaml` (`scripts.setup`). Orca itself is not installed in this sitting | upstream |
| `deploy/wsl/meridian.user-data`, `deploy/wsl/setup.sh` | this repo | n/a | 2026-11-12 | the distro definition and the user-level setup steps | own design |

## Trading (IBKR paper lane, milestone M1)

| Component | Version or commit | Source URL (read) | Date read | Used for | Origin |
|---|---|---|---|---|---|
| NautilusTrader | 2.0.0rc9 from PyPI (tag `v2.0.0rc9`, commit `da6b57aefdd62b44f675e434ffcfefca7f4025dd`), licence LGPL-3.0-only; wheel hashes in `uv.lock` | https://pypi.org/pypi/nautilus_trader/2.0.0rc9/json ; https://github.com/nautechsystems/nautilus_trader/releases/tag/v2.0.0rc9 | 2026-11-12 | the engine: live node, Interactive Brokers adapter, startup reconciliation | upstream |
| NautilusTrader IB integration guide and reconciliation concept | at tag `v2.0.0rc9` | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/v2.0.0rc9/docs/integrations/interactive_brokers.md ; https://raw.githubusercontent.com/nautechsystems/nautilus_trader/v2.0.0rc9/docs/concepts/execution/reconciliation.md | 2026-11-12 | ports, client ids, what startup reconciliation does and when it aborts | upstream |
| `upstream/.../interactive_brokers/_common.py` | git blob `c3ce3319514926dbbe29d46dd458168dfd385d79` at the tag commit | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/da6b57aefdd62b44f675e434ffcfefca7f4025dd/examples/live/interactive_brokers/_common.py | 2026-11-12 | `build_ib_live_node`, `instrument_provider_config`, `schedule_node_stop`, `default_aapl_instrument_id`. Verbatim copy | upstream |
| `upstream/.../interactive_brokers/ib_v2_order_strategies.py` | git blob `80c8bcca0eca0ea2b76714c3af67a2406d6c4885` at the tag commit | https://raw.githubusercontent.com/nautechsystems/nautilus_trader/da6b57aefdd62b44f675e434ffcfefca7f4025dd/examples/live/interactive_brokers/ib_v2_order_strategies.py | 2026-11-12 | `IbV2OrderStrategy`: waits for a quote, submits once, cancels on acceptance, cancels its own orders on stop. Its close-on-stop is switched off by the lane. Verbatim copy | upstream |
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
- **Upstream example files are LGPL-3.0.** They are kept verbatim with their headers.
