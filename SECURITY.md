# SplitLine security model

## The honest sentence first

**No software is unhackable or unbreakable, and SplitLine will never claim
to be.** Anyone selling you "unhackable" software is selling a slogan. What
SplitLine does instead is publish exactly how it is built, what it refuses
to do, and how it fails — so failures land soft, visible, and reversible.

## What SplitLine cannot break (by construction)

- **It never edits your main routing table / default preferences blindly.**
  The game line is the protected default. Bulk traffic is moved by adding
  a *separate* routing table (Linux), preference metrics (Windows), or a
  namespaced pf anchor (macOS) — all removable without touching the rest.
- **Apply is atomic in practice.** Every plan step carries its own undo.
  If any step fails, or the post-apply connectivity check fails on either
  interface, everything already applied is rolled back automatically and
  the tool says so. You are never left in a half-split state.
- **Dry-run by default.** `splitline apply` only prints the plan. The
  machine changes only with an explicit `--yes`, from an elevated shell.
- **Detect-and-refuse.** One interface, no gateway, no IPv4, unknown
  interface names, malformed CIDRs/UIDs — the tool stops with a message
  instead of guessing. A reboot also fully clears the macOS anchor rules
  (session-scoped by design in v0.2).
- **`splitline revert` and `splitline heal`** exist from day one: revert
  removes everything the state file records; heal detects stale state
  (e.g. an interface that no longer exists) and cleans it up.

## How it resists being abused or tampered with

- **Fully offline.** SplitLine makes zero network calls of its own (the
  only traffic is your OS `ping` to 1.1.1.1 during post-apply checks).
  No telemetry, no analytics, no accounts, no auto-update channel to hijack.
- **Stdlib-only Python.** Zero third-party dependencies — no supply-chain
  of pip packages to compromise. The whole tool is a few readable files.
- **No shell, ever.** Commands run as argv lists via subprocess. Interface
  names are accepted only if the OS itself reported them, plus a strict
  character whitelist; CIDRs and UIDs are parsed and rejected if malformed.
  Command injection through interface names is covered by unit tests.
- **Least privilege.** Detection and planning need no admin rights. Only
  the apply/revert step asks for elevation, and only for the commands in
  the printed plan.
- **No driver, no daemon, no persistence tricks.** Especially on Windows:
  no kernel/WFP driver means no new attack surface in the network stack —
  and no anti-cheat exposure for gamers (Vanguard/EAC class systems watch
  exactly that layer).
- **State is a small JSON file** in the user's own state directory,
  written atomically, listing exactly what was applied so revert is exact.

## Release integrity (roadmap, stated plainly)

- Now: source is public in this repo; verify any copy against git history.
- For packaged releases: publish SHA-256 checksums alongside binaries.
- "Proper" signed releases need paid certificates (estimates: an Apple
  Developer ID is $99/year; a Windows code-signing certificate is roughly
  €200–400/year). Until those exist, SplitLine ships as source + scripts,
  which any user can read before running — for a routing tool, that
  transparency is worth more than a signature.

## Threats explicitly out of scope

- An attacker who already has admin/root on your machine. At that point
  every tool on the box is theirs; routing software cannot change that.
- Compromised OS network tools (`ip`, `route`, `pfctl`, PowerShell).
  SplitLine calls the OS's own tools by design.
