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
| Claude Code (native installer; **not installed yet**: `setup.sh claude` runs after the harvest of plan 8.3 is done or skipped) | 2.1.322 to be asked for at install; it updates itself afterwards | https://code.claude.com/docs/en/setup ; https://claude.ai/install.sh ; https://downloads.claude.ai/claude-code-releases/latest | 2026-11-12 | the lead agent in the distro | upstream |
| Claude Code setting `disableClaudeAiConnectors` | n/a | https://code.claude.com/docs/en/settings | 2026-11-12 | set to `true` in `~/.claude/settings.json` so claude.ai connectors (including an Interactive Brokers one) do not load in Claude Code started in the distro. Set twice: in the owner's `~/.claude/settings.json` and machine-wide in `/etc/claude-code/managed-settings.json`, which also holds when a tool starts Claude Code with its own config home. It does not cover connectors the Claude desktop app itself attaches to a session | upstream |
| Claude Code managed settings path on Linux and WSL | n/a | https://code.claude.com/docs/en/managed-settings.md | 2026-11-12 | where the machine-wide copy of that setting lives | upstream |
| apt packages for the IB Gateway window | libgtk-3-0t64 3.24.52-0ubuntu1, libnss3 2:3.120-1ubuntu2.2, libnspr4 2:4.38.2-1ubuntu1, libasound2t64 1.2.15.3-1ubuntu1.1, libatk1.0-0t64 2.60.4-0ubuntu0.1, libatk-bridge2.0-0t64 2.60.4-0ubuntu0.1, libatspi2.0-0t64 2.60.4-0ubuntu0.1, libcups2t64 2.4.16-1ubuntu1.3, xdg-utils 1.2.1-2ubuntu2 | https://teamdev.com/jxbrowser/docs/guides/introduction/requirements/ (the browser component on the Gateway's classpath); https://packages.ubuntu.com/resolute/ | 2026-11-12 | IBKR publishes no Linux package list, so this list is an inference from that component's requirements. Checked by starting the installed Gateway under WSLg: it was still running after 35 seconds, with no error in its output (not logged in) | upstream |
| Ubuntu Insights consent (in the image, not installed by this repo) | ubuntu-insights 0.9.3ubuntu | `ubuntu-insights --help` and `ubuntu-insights consent --help` in the distro; `/usr/lib/wsl/ubuntu-insights.sh` in the image; https://raw.githubusercontent.com/ubuntu/ubuntu-insights/main/README.md | 2026-11-12 | recorded as "no" for the owner user, the way Ubuntu's own WSL script records a "no". Per the README, a declined client sends only `{"OptOut": true}`. The Windows registry value that script can also write is left alone | upstream |
| Ubuntu Insights timers (in the image) | `ubuntu-insights-collect.timer`, `ubuntu-insights-upload.timer`, ubuntu-insights 0.9.3ubuntu | `/usr/lib/systemd/user/` in the image; `systemctl --user cat` of both | 2026-11-12 | the image enables both for every user by preset; the definition disables them with `systemctl --global disable`, and `setup.sh check` verifies it | upstream |
| cloud-init `users` keys `homedir`, `no_create_home`; `package_upgrade` | cloud-init 26.1 | checked with `cloud-init schema --config-file` on the installed cloud-init; https://cloudinit.readthedocs.io/en/latest/reference/modules.html | 2026-11-12 | the `paper` service user has no home (`/nonexistent`); packages are brought up to date on first boot | upstream |
| Orca `orca.yaml` file format | v1.4.257, commit `b0570d90fc9af8c9e7e3566c0fb841d0884e2462` | https://github.com/stablyai/orca/blob/v1.4.257/docs/site/content/docs/model/orca-yaml.mdx | 2026-11-12 | `orca.yaml` (`scripts.setup`). Orca itself is not installed in this sitting | upstream |
| `deploy/wsl/meridian.user-data`, `deploy/wsl/setup.sh` | this repo | n/a | 2026-11-12 | the distro definition and the user-level setup steps | own design |

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

## Order budget (milestone M2)

The budget is the owner's own design, harvested from the owner's repository
`seathatflowsinourveins/sextant`, read at head `33cdee7b65d53c93ab106b7b3196fc790b14a5a8`.
The same files are byte-identical in `seathatflowsinourveins/sextant-paper` at
`a991b73a7e3a2933384bc94f5092ad0e1f7e6445`. `tests/test_order_budget_harvest.py` checks that
each harvested file is the source but for the import lines listed there.

| Component | Version or commit | Source URL (read) | Date read | Used for | Origin |
|---|---|---|---|---|---|
| `meridian/order_budget/pacer.py` | `src/sextant/execution/pacer.py`, git blob `49a30e965aac62dea17cb3d6b4c09fee685e9742`, last changed in `49654edc56419a51445bff40b16ec3a12c8c3593` (2026-11-10). Changed here: the import line of the controls | https://github.com/seathatflowsinourveins/sextant/blob/33cdee7b65d53c93ab106b7b3196fc790b14a5a8/src/sextant/execution/pacer.py | 2026-11-12 | the order budget, one pacer per account. Every paced request (CANCEL, REDUCE, MODIFY, QUERY, SUBMIT) takes a token from a bucket of `request_budget x burst_fraction` tokens that refills one token per `window // (budget - burst) + 1` ns; waiting requests go out by kind in that order, first in first out within a kind; admission is checked again at send; a 429 empties the bucket and pauses every request | own design (the owner's, from Sextant) |
| `meridian/order_budget/controls.py` | `src/sextant/risk/controls.py`, blob `d7fed7b1c9252d425a8ec32ec985560a39231273`, last changed in `09c148480a0cc9dda2b5b6d0835fd9aea594f86e` (2026-11-10). Unchanged; its docstring points into the owner's earlier repositories | https://github.com/seathatflowsinourveins/sextant/blob/33cdee7b65d53c93ab106b7b3196fc790b14a5a8/src/sextant/risk/controls.py | 2026-11-12 | validates the control rows: every control named once, with source, unit, calibration and scope; fixture rows only with `fixture=True`; the budget at most the broker limit; `1 <= burst < budget`. It is not under a `risk/` folder here, because `risk/` belongs to the owner | own design (the owner's, from Sextant) |
| `tests/test_order_budget_pacer.py` | `tests/proofs/custody/test_pacer.py`, blob `97c32c1016f1343b929bd5f20ba7cd39c0677a3b`, last changed in `09c148480a0cc9dda2b5b6d0835fd9aea594f86e`. Changed here: its import lines | https://github.com/seathatflowsinourveins/sextant/blob/33cdee7b65d53c93ab106b7b3196fc790b14a5a8/tests/proofs/custody/test_pacer.py | 2026-11-12 | the pacer's own tests: priority and FIFO, no window over the budget, admission checked again after a wait, the 429 path, entry reserves, the wire hook used once, restore | own design (the owner's, from Sextant) |
| `meridian/order_budget/rows.py`, `tests/order_budget_fixtures.py` | this repo; the values and helpers are `control_rows()` and `controls()` in `tests/proofs/custody/conftest.py` (blob `0bdc6ac9cab4a154a4c661c95d59e8e5a716c129`), pinned by `tests/test_order_budget_harvest.py` | https://github.com/seathatflowsinourveins/sextant/blob/33cdee7b65d53c93ab106b7b3196fc790b14a5a8/tests/proofs/custody/conftest.py | 2026-11-12 | the soak's and the tests' control rows: budget 180, broker limit 200, window 60 s, burst fraction 0.1 (burst 18), reserves 1, all `FIXTURE_ONLY` and `UNCALIBRATED`. `Controls.from_rows` refuses them unless it is called with `fixture=True`, which only the soak and the tests do; a lane builds its controls without it, as Sextant's Alpaca execution factory does, and needs rows the owner has reviewed | own design |
| `meridian/order_budget/soak.py`, `tests/test_order_budget_soak.py`, `tests/test_order_budget_harvest.py` | this repo | n/a | 2026-11-12 | the offline soak against a simulated venue, its run record in `evidence/`, the checks that each of its conditions can fail, a test of the 429 pause, and the check of the harvested files | own design |
| Sextant's design notes on the budget (read, not copied) | `docs/adr/0009-order-rate-limits.md` (blob `27010a67a625483233f0fb8ccffa0fcbf7b88d74`), `docs/handbook/alpaca-execution.md` (blob `24e3d0491883fd1c12082756e180b11a159c5e86`) | https://github.com/seathatflowsinourveins/sextant/blob/33cdee7b65d53c93ab106b7b3196fc790b14a5a8/docs/adr/0009-order-rate-limits.md ; https://github.com/seathatflowsinourveins/sextant/blob/33cdee7b65d53c93ab106b7b3196fc790b14a5a8/docs/handbook/alpaca-execution.md | 2026-11-12 | the budget's reasons: 180 order actions a minute under Alpaca's 200, queries counted, the burst inside the budget, priority CANCEL > REDUCE > MODIFY > QUERY > SUBMIT; and how the Alpaca adapter calls the pacer (every REST request through it, the SDK's own retries off, a pacer refusal is a not-sent refusal) | own design (the owner's) |
| Alpaca Trading API rate limit | n/a (Alpaca support article, December 2022) | https://alpaca.markets/support/usage-limit-api-calls | 2026-11-12 | "currently 200 requests per minute, per account", every request counted, 429 past it; the budget keeps to 180 of them. Alpaca's archived API reference (`alpacahq/alpaca-docs` at `2080c5e0efbbd812c48eef9209a7a9962de67d2a`, `content/api-references/trading-api/_index.md`) says per API key instead; the current docs give no figure | upstream |
| NautilusTrader's own order rate limits (read, not set here) | 2.0.0rc9, commit `da6b57aefdd62b44f675e434ffcfefca7f4025dd` | https://github.com/nautechsystems/nautilus_trader/blob/da6b57aefdd62b44f675e434ffcfefca7f4025dd/crates/live/src/node/config.rs ; https://github.com/nautechsystems/nautilus_trader/blob/da6b57aefdd62b44f675e434ffcfefca7f4025dd/crates/risk/src/engine/mod.rs ; https://github.com/nautechsystems/nautilus_trader/blob/da6b57aefdd62b44f675e434ffcfefca7f4025dd/crates/trading/src/strategy/mod.rs | 2026-11-12 | why the budget is a component of its own: the risk engine throttles only submits and modifies (100 a second each by default, rolling window) and denies the excess instead of queueing it, while a strategy's cancels and queries go straight to execution without a throttle | upstream |

Notes on the order budget, measured by the soak (`evidence/M2-order-budget-*-soak.json`):

- **It holds the request past the budget; it does not raise.** A request waits in the pacer's
  queue until the bucket has a token, most urgent kind first. A queued request leaves the queue
  unsent in three ways: its caller's admission check turns false (the caller withdrew it); it
  is an entry whose protection reserve would reach the burst (`refuse(reason)` is called, and
  `request()` raises `PacerRefused` if that is already so when it is made); or it is an entry
  whose reserve cannot be worked out (reserve rows missing, or a position count that is not a
  whole number), which is dropped silently, so a caller checks reserve authority in its own
  admission, as Sextant's Alpaca gateway does. This is the owner's design (Sextant ADR-0009,
  R6), kept as it is because the Alpaca adapter of M3 relies on it.
- **The cap is 179, not 180.** The refill interval rounds up (370,370,371 ns for 162 refills a
  minute), so the 162nd refill lands 102 ns after the window: a full burst of 18 plus 161
  refills. After a quiet spell the bucket is full again, and the window that follows holds 179
  too. Under steady demand above the budget it sends 161 to 163 a minute, because the burst is
  shared with the budget rather than added to it.

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
