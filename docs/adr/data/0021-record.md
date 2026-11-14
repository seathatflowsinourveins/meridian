# ADR 0021 record: IBC for the Gateway's paper login (read 2026-11-14)

The sources were read over HTTPS, anonymously, on 2026-11-14 (ET). The release zip was checked
against GitHub's digest, read in a scratch folder under `~/.cache/meridian/` and then removed.
Nothing was installed, started, logged in to or connected to. No login was typed or read.

## Upstream state
- `gh api repos/IbcAlpha/IBC`: `archived: true`, `pushed_at: 2026-09-01T00:46:31Z`, licence
  GPL-3.0. The last commit is `fc6d917d56` "Revise retirement information and repository status".
- Releases: 3.24.2 (2026-08-21), 3.24.1 (2026-07-02), 3.24.0 (2026-06-19), 3.23.0 (2025-07-03).
  `IBCLinux-3.24.2.zip` has sha256 `cc097ca1dfa75413a5fbe02e4743050af15f3308eb6a97c769b3cff9850c80c5`
  (GitHub's asset digest; `sha256sum -c` OK). Commit `80cb002274`: "Provide support for
  TWS/Gateway v1048 and later". The Gateway here is 10.50 (`~/Jts/ibgateway/1050`; its folder name only).
- README: "This project has been retired, as of 1 September 2026 … there will be no further
  development of IBC, other than completing work in progress at that date and fixing any
  significant newly reported bugs. Nor will IBC be actively supported on this repository."
  "This project repository has been archived … read-only". "It is intended to produce a final
  release that clears all outstanding issues."
- Discussion 347, "The future of IBC" (2026-03-24): "after that I will let it die … It may be
  that there is someone somewhere who would be willing to carry it forward, presumably by
  forking it to a new project with a new name." It also says: "There is less need for IBC than
  there used to be, particularly because of the auto-restart mechanism in Gateway and TWS."
- Forks pushed after 2026-09-15: the largest has 12 stars (XYUU/IBAS); the others have 0 to 2.
  No fork has been named as the successor.
- gnzsnz/ib-gateway-docker: MIT, pushed 2026-11-13, release `ibgateway-latest@10.52.1d`;
  `stable/Dockerfile` line 13 is `ENV IBC_VERSION=3.24.2`, and its `IBC_REPO` is
  `https://github.com/IbcAlpha/IBC`.
- NautilusTrader `v2.0.0rc9` `docs/integrations/interactive_brokers.md`: "`DockerizedIBGateway`
  manages the gnzsnz IB Gateway container. Supply credentials in the config or set
  `TWS_USERNAME` and `TWS_PASSWORD`". On this machine `command -v docker` finds nothing.
- code-hustler-ft3d/ibg-controller: MIT, created 2026-04-12, 48 stars, v0.17.1 of 2026-11-13,
  "Unattended IB Gateway in Docker".

## Source lines for the six points (IBCLinux-3.24.2 unless named)
1. User guide, "Running with crontab": `* 8 * * 1 export DISPLAY=:10 && /bin/bash /opt/ibc/gatewaystart.sh`;
   "The value you need for the DISPLAY variable will depend on how your system is configured."
   `gatewaystart.sh` line 231 opens an `xterm` unless it is given `-inline`. On this machine:
   Ubuntu 26.04.1, systemd 259, `apt-cache policy xvfb` reports "Installed: (none)" with candidate
   2:21.1.22-1ubuntu1.3, and `/mnt/wslg` and `/tmp/.X11-unix/X0` are present while this session runs.
2. `scripts/ibcstart.sh` line 527: `"$java_path/java" … "$ibc_ini" "$ib_user_id" "$ib_password" ${mode}`.
   It prints `***` in the echoed command but passes the real values to `java`. `/proc/mounts`:
   `proc /proc proc rw,nosuid,nodev,noexec,noatime` (no `hidepid`). User guide, "Password
   Security": the `.ini` "is the preferred method"; the command line "is strongly deprecated
   because command line information associated with a process is easily available outside the
   process". `config.ini`: a login given on the command line overrides the `.ini`'s.
   `DefaultSettings.java` (tag 3.24.2), `getSettingSanitisedValue`: `IbLoginId` and `IbPassword` are logged as `***`.
3. `config.ini`, Trading Mode: "If it is set to 'paper', then either the live or the
   paper-trading credentials may be supplied"; the default is `live`. `DefaultTradingModeManager.java`:
   the mode is taken from the argv, else from `TradingMode`, else `live`; any other value exits
   with `INVALID_TRADING_MODE`. IBKR Web API docs, "Using a Paper Account": the separate "Paper
   Trading Username" is under Client Portal › Settings › Paper Trading Account. `config.ini`,
   Read-only Login: it applies "if the user is enrolled in IB's account security programme".
   Second factor for the paper user: none of the IBKR pages read states a rule.
   A search summary claimed that paper logins need one, but no page it cited says so, so nothing is claimed here.
4. `config.ini`: `OverrideTwsApiPort` "changes the 'Socket port'"; `ReadOnlyApi` "If not set, the
   existing … configuration is unchanged"; `TrustedTwsApiClientIPs`: "ONLY RELEVANT FOR THE
   GATEWAY, AND ONLY WHEN FIX=yes"; `AcceptIncomingConnectionAction`: "recommended to set this to
   'reject', and to explicitly configure which IP addresses can connect … in TWS's API
   configuration page". No key sets "localhost only". `meridian/boundary.py`: the Gateway binds
   `*:4002`, and only its own "Allow connections from localhost only" setting keeps other hosts out.
5. IBKR, "Auto Restart Considerations" (https://www.ibkrguides.com/traderworkstation/auto-restart-considerations.htm,
   updated 2025-10-08): "This procedure will require manual authentication once a week, the first
   time you log into the platform after the security tokens have been invalidated. This security
   process occurs each Sunday at 1:00 am ET." Things that impede it: "If your machine is in sleep
   or hibernation mode, or happens to have no power when the restart is scheduled to occur",
   OS-update reboots, and token revocation "for security reasons". `config.ini`: `ColdRestartTime`
   is a Sunday time after 01:00 US/Eastern at which IBC "initiat[es] the usual full logon".
   `ExistingSessionDetectedDialogHandler.java`: with `secondary`, IBC clicks "Cancel" or "Exit
   Application" on every existing-session dialog, so it always yields.
6. `ibcstart.sh`: `-DjtsConfigDir=${tws_settings_path}` (default `~/Jts`). Line 510: `mv
   "${program_path}/ibgateway" "${program_path}/ibgateway1"` "to prevent restart without IBC".
   `meridian/boundary.py`: the paths follow the caller's `$HOME`, and "M7 has to run the Gateway
   and the lane as one user, or give the lane that access".

## What a person still does
- After every machine or WSL restart: start `~/Jts/ibgateway/1050/ibgateway` and log in to
  Paper Trading with the paper user's own login (docs/LANES.md). The Gateway's auto-restart
  continues a running session. A machine that was off "when the restart is scheduled" is not
  covered (IBKR, above).
- With the daily auto-restart set in the Gateway (Configure › Lock and Exit), the session
  survives the weekdays. The first start after Sunday 01:00 ET needs manual authentication
  (IBKR, above). If the machine is restarted only at the weekend, that is one typed login a week.
- Between those logins nobody needs to be present: port 4002 stays open while the Gateway runs.

## The frozen 3.24.2 design
This is the alternative the ADR advises against; it is written out so the owner can choose it knowingly.
- Xvfb from Ubuntu's `xvfb` on its own display. An owner user unit with linger (point 6),
  `LoadCredentialEncrypted=` from `/etc/credstore.encrypted/` (systemd-creds, typed once into a
  no-echo helper). A wrapper renders `config.ini` with `TradingMode=paper`,
  `ExistingSessionDetectedAction=secondary`, `AcceptIncomingConnectionAction=reject`,
  `ReadOnlyApi` unset and `CommandServerPort=0` into `$RUNTIME_DIRECTORY` (mode 0600, removed at
  stop). It passes `paper` on the argv, refuses any other mode, and passes no login on the argv.
- Drawbacks, most serious first:
  1. `TradingMode=paper` also accepts a live login, so the paper-only guarantee rests on which
     login is typed, which no start check can verify.
  2. The upstream is retired: no fix follows a future Gateway change.
  3. It renames the Gateway's launcher, which breaks the attended start.
  4. "Localhost only" stays a manual setting.
  5. GPL-3.0 code runs beside the lane.

## Not a substitute
IBKR Web API introduction (https://www.interactivebrokers.com/docs/web-api/introduction.md): a
"RESTful Web API … Authorization and Authentication … is managed using OAuth 2.0". NautilusTrader's
adapter "connects … to Trader Workstation (TWS) or IB Gateway through the TWS API" (integration guide, line 4).
These are two different APIs, so OAuth cannot log in the Gateway that the engine uses.
