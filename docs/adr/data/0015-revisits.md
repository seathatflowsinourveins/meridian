# ADR 0015 revisits

- 2026-11-14, kept. Sources rechecked: GitHub's latest release of jarrodwatts/claude-hud is still
  v0.15.0 (`gh api repos/jarrodwatts/claude-hud/releases/latest`), the pinned commit is still
  marked verified, and the advisories page still lists four, all fixed at or before the pin.
  On the owner's instruction of 2026-11-13 its display was widened with `hud set` (and in
  `claude_hud_config` for a rebuilt distro): effort, output speed, skills and MCP activity,
  prompt cache expiry and hit rate, session tokens, cost (session, today, week), compactions and
  both usage windows with their pace. Measured here on a real status payload: ten lines,
  165 to 171 ms per render over three runs (two lines and about 140 ms before).
  It now holds the manifest's "token and cost accounting" job; `ccusage/ccusage` is not
  installed (`ecosystem-manifest.md`, layer 7).
