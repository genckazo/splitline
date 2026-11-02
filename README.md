# SplitLine

**One line for the game. One line for everything else.**

SplitLine is a work-in-progress project for people with two internet
connections at home (fiber + 4G/5G modem, two ISPs, dorm + hotspot): route the
game over the clean, low-latency connection and downloads/uploads over the
other one — no VPN servers, no subscription, no networking degree required.

## Status

Early. Currently in validation + dogfood phase:

- `SPEC.md` — product spec: the problem, the promise, the build order, and why
  the sellable v1 is a router wizard rather than a Windows driver app.
- `prototype/` — v0 dogfood tools that perform the split by hand today:
  - `splitline.sh` — Linux policy-routing split (game line stays default,
    bind-capable apps ride the bulk line; dry-run and full revert built in).
  - `WINDOWS.md` — the Windows equivalent with settings only (adapter metrics
    + qBittorrent interface binding).
- `marketing/validation-posts.md` — the demand-validation posts that decide
  whether v1 gets built.

## The idea in one paragraph

Downloads killing game ping is a universal complaint, and two-connection homes
are common — yet the only current answers are dual-WAN router configuration
(nerd-only), bonding VPN subscriptions (which add the latency gamers are
trying to escape), or bandwidth limiters (which throttle instead of reroute).
SplitLine aims to be the one-click version: game line / download line, done.

## License

All rights reserved for now — this is a pre-release commercial project, not
an open-source release. Licensing will be decided at v1.
