# SplitLine

**One line for the game. One line for everything else.**

SplitLine is a work-in-progress project for people with two internet
connections at home (fiber + 4G/5G modem, two ISPs, dorm + hotspot): route the
game over the clean, low-latency connection and downloads/uploads over the
other one — no VPN servers, no subscription, no networking degree required.

## Status

v0.2 cross-platform CLI is built (2026-11-02); validation is still open:

- `splitline/` — the Python package (stdlib-only, fully offline). One safety
  engine for Linux, Windows and macOS: plans are printed before anything
  changes, apply requires `--yes`, every step has an undo, the result is
  verified per interface, and any failure rolls back automatically.
- `SPEC.md` — product spec: the problem, the promise, the build order, and why
  the sellable v1 is a router wizard rather than a Windows driver app.
- `SECURITY.md` — the security model, stated honestly: no software is
  unhackable; here is exactly what this one guarantees and refuses to do.
- `prototype/` — v0 dogfood tools that perform the split by hand today:
  - `splitline.sh` — Linux policy-routing split (game line stays default,
    bind-capable apps ride the bulk line; dry-run and full revert built in).
  - `WINDOWS.md` — the Windows equivalent with settings only (adapter metrics
    + qBittorrent interface binding).
- `marketing/validation-posts.md` — the demand-validation posts that decide
  whether v1 gets built.

## Using the CLI (v0.2)

Needs Python 3.10+. From this repo:

```sh
python3 -m splitline.cli detect            # see your interfaces
python3 -m splitline.cli apply GAME BULK   # prints the plan, changes nothing
sudo python3 -m splitline.cli apply GAME BULK --yes   # apply + verify
sudo python3 -m splitline.cli revert       # remove everything
python3 -m splitline.cli heal              # clean up stale state
```

Per-OS strength, honestly: **Linux** gets full policy routing (plus
`--mark-uid` to send a whole user's traffic to the bulk line). **Windows**
gets adapter metrics + optional `--bulk-route CIDR` destination routes —
per-app routing would need a kernel driver, which SplitLine deliberately
does not ship (anti-cheat safety). **macOS** gets a pf anchor with
`--bulk-dest CIDR` route-to rules plus client binding; rules are
session-scoped in v0.2, so a reboot resets them.

## The idea in one paragraph

Downloads killing game ping is a universal complaint, and two-connection homes
are common — yet the only current answers are dual-WAN router configuration
(nerd-only), bonding VPN subscriptions (which add the latency gamers are
trying to escape), or bandwidth limiters (which throttle instead of reroute).
SplitLine aims to be the one-click version: game line / download line, done.

## License

All rights reserved for now — this is a pre-release commercial project, not
an open-source release. Licensing will be decided at v1.
