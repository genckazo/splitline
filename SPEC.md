# SplitLine — Product Spec v0.1

Working name: **SplitLine**. One line for the game, one line for everything else.

## The problem (in the customer's words)

"I have two internet connections at home. The second a download or upload starts,
my game ping explodes. Why can't my PC just use one connection for gaming and
the other for downloads?"

Today the answers are all bad:
- Buy a dual-WAN router and learn policy routing (nerd-only).
- Speedify-style bonding VPNs (subscription, server adds latency — the opposite
  of what a gamer wants).
- Bandwidth limiters (NetLimiter etc.) throttle apps; they don't move them to
  the other connection.

## The product promise

Two toggles and a list:

1. **Game line:** pick connection A. It becomes the protected default route.
2. **Download line:** pick connection B.
3. **App rules:** tick the apps that ride the download line (torrent client,
   Steam downloads, browsers, cloud sync). Everything else stays on the game line.

No servers. No VPN. No account. Local routing only — the game packets never
leave the house on the wrong wire.

## Who it's for

- Gamers in two-connection homes: fiber + 4G/5G modem, two ISPs, dorm + mobile
  hotspot. Heavy in Turkey / MENA / rural EU / LatAm.
- Streamers are a secondary audience (stream on line B, game on line A).

## Form factors, in build order

### v0 — Linux split script (NOW, dogfood)
Bash prototype using policy routing: second routing table + `ip rule` for a
marked "downloads" network namespace / interface pinning, plus qBittorrent
interface binding. Purpose: prove the outcome feels as good as the pitch on
g's own two-modem setup. Not the product — the lab.

### v1 — Router wizard (the sellable one)
Desktop app (Windows/macOS/Linux) that SSHes into a cheap OpenWrt router,
detects two WANs, and writes a working mwan3 policy config in ~2 minutes:
game device/game traffic → WAN1, bulk devices/apps → WAN2, automatic failover.
Why this form: no kernel driver, no Microsoft driver-signing cost, and zero
anti-cheat exposure (nothing is installed on the gaming PC's network stack).
Price idea: one-time €10–15 (estimate, unvalidated).

### NOT v1 — native Windows per-app routing driver
Requires a WFP callout driver + paid signing, and game anti-cheat systems
(Vanguard / EAC / BattlEye class) may flag traffic-manipulation drivers.
Selling gamers a ban risk is a non-starter. Revisit only with legal + technical
proof it is safe, or never.

## Validation gate (before any real build)

Post the pain + one-click fix in gamer / home-networking communities
(drafts in `marketing/validation-posts.md`). Proceed to v1 only if the posts
produce real demand signals (upvotes/comments asking "where can I get this",
rough target: 50+ engaged responses across posts — g's call on the threshold).
Zero-cost by design: g's budget is €0.

## Risks (from the idea log, kept honest)

- Support burden: home networks are chaos; the wizard must detect-and-refuse
  setups it can't handle rather than break someone's internet.
- Price-sensitive markets: keep price one-time and low; no subscription.
- Partial competitors exist (Speedify, NetLimiter, OpenMPTCProuter) — the moat
  is simplicity for this one job, not technology.

## Dogfood target OS

g answered "Both / not sure yet" (2026-11-02), so both dogfood paths exist:
`prototype/splitline.sh` (Linux) and `prototype/WINDOWS.md` (adapter metrics +
qBittorrent binding, settings only). Whichever machine he sits at first is
the test bed.

## v0.2 — Cross-platform gamer CLI (built 2026-11-02)

g asked for Linux + Windows + macOS, "more advanced", and hardened. Built as
a stdlib-only Python package in `splitline/` with one safety engine for all
three OSes (plan → print → `--yes` to apply → per-interface verify →
automatic rollback on any failure; `revert` + `heal` included — see
`SECURITY.md` for the exact guarantees and their limits):

- **Linux (full strength):** bulk routing table + source rule + fwmark rule,
  optional per-uid iptables marking (`--mark-uid`). Main table untouched.
- **Windows (honest scope):** adapter metrics (game 10 / bulk 50) + optional
  destination routes via the bulk gateway (`--bulk-route`) + client-binding
  notes. No per-app routing — that still needs a driver, still excluded
  (anti-cheat). Whole-house Windows strength remains the v1 router wizard.
- **macOS:** namespaced pf anchor (`com.splitline`) with route-to rules for
  named bulk destinations (`--bulk-dest`) + client binding; session-scoped
  in v0.2, so a reboot is a clean reset.

13 unit tests cover detection parsing, plan contents per OS, command-
injection refusal, rollback on mid-apply failure, state round-trip, and
dry-run purity. Windows/macOS backends are plan-verified by tests, not yet
run on real Windows/Mac hardware — first dogfood runs will confirm.

The router wizard stays the v1 sellable form; this CLI is the power-user /
dogfood tier and the shared brain (detect/plan/verify) the wizard will reuse.

## v0.2.1 — GPUI desktop app scaffold (2026-11-02, g's ask)

`gui/` adds a GPUI (Rust, Zed's framework — g's notesec stack) desktop
front-end: interface pickers for game/bulk lines, plan preview, apply via
pkexec, status, revert. Hard rule: the GUI holds zero routing logic — it
shells to the CLI (new `detect --json` output exists for exactly this), so
one safety engine serves terminal and GUI alike. 14 unit tests pass.
Scaffold is uncompiled as of this writing (no Rust toolchain in Muse's
sandbox; saturn is the GPUI build machine) — first-build API fixes are
expected and normal; treat `gui/` as source until a build is verified.
