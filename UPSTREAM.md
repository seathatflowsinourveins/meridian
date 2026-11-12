# Upstream register

Every tool this repo installs or integrates has a row here: what it is, the exact version or
commit, the page it was read from, the date it was read, and what it is used for.
"upstream" means the thing is used as its maintainers ship it. "own design" means it was written
here and no upstream ships it.

A row is added in the same commit that adds the tool. Versions marked "recorded after first boot"
are filled in from the running distro, not from memory.

## Distro (`deploy/wsl/`)

| Component | Version or commit | Source URL (read) | Date read | Used for | Origin |
|---|---|---|---|---|---|
| WSL (already on the host, not installed by this repo) | 3.0.3.0 | `wsl --help` and `wsl --version` on this machine; https://learn.microsoft.com/windows/wsl/basic-commands | 2026-11-12 | `--install --name --location --vhd-size --no-launch`, `--set-default`, `--mount --vhd --bare`, `--unmount` | upstream |
| Ubuntu 26.04 LTS WSL image | `Ubuntu-26.04` from `wsl --list --online`; build recorded after first boot | https://documentation.ubuntu.com/wsl/stable/howto/cloud-init/ | 2026-11-12 | the `meridian` distro | upstream |
| cloud-init, WSL datasource | shipped in the image; version recorded after first boot | https://cloudinit.readthedocs.io/en/latest/reference/datasources/wsl.html | 2026-11-12 | applies `deploy/wsl/meridian.user-data` on first boot, looked up as `%USERPROFILE%\.cloud-init\meridian.user-data` | upstream |
| `/etc/wsl.conf` keys | n/a (WSL 3.0.3.0) | https://learn.microsoft.com/windows/wsl/wsl-config | 2026-11-12 | `[boot] systemd=true`, `[user] default`, `[interop] appendWindowsPath=false` | upstream |
| apt packages `git gh build-essential curl jq unzip` | Ubuntu 26.04 archive; versions recorded after first boot | https://packages.ubuntu.com/resolute/ | 2026-11-12 | base tools named in the plan | upstream |
| Node.js | v24.22.3 (LTS "Krypton"), `node-v24.22.3-linux-x64.tar.xz`, sha256 `4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb` | https://nodejs.org/dist/v24.22.3/SHASUMS256.txt ; https://nodejs.org/dist/index.json | 2026-11-12 | pinned Node >= 18.18 for the agent CLIs of the next sitting; nothing in this repo runs on it yet | upstream |
| uv | 0.13.7, installer sha256 `d263ee68314cf5bea36b08e6bd9e2c4563240d7adb73756cf33af5c199b92db4` | https://astral.sh/uv/0.13.7/install.sh ; https://docs.astral.sh/uv/getting-started/installation/ ; https://github.com/astral-sh/uv/releases/tag/0.13.7 | 2026-11-12 | Python project, lockfile, managed CPython | upstream |
| Claude Code (native installer) | 2.1.322 | https://code.claude.com/docs/en/setup ; https://claude.ai/install.sh ; https://downloads.claude.ai/claude-code-releases/latest | 2026-11-12 | the lead agent in the distro | upstream |
| Claude Code setting `disableClaudeAiConnectors` | n/a | https://code.claude.com/docs/en/settings | 2026-11-12 | set to `true` in `~/.claude/settings.json` so claude.ai connectors (including an Interactive Brokers one) never load in the distro | upstream |
| Orca `orca.yaml` file format | v1.4.257, commit `b0570d90fc9af8c9e7e3566c0fb841d0884e2462` | https://github.com/stablyai/orca/blob/v1.4.257/docs/site/content/docs/model/orca-yaml.mdx | 2026-11-12 | `orca.yaml` (`scripts.setup`). Orca itself is not installed in this sitting | upstream |
| `deploy/wsl/meridian.user-data`, `deploy/wsl/setup.sh` | this repo | n/a | 2026-11-12 | the distro definition and the user-level setup steps | own design |

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
