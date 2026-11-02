# SplitLine dogfood — Windows path (no code, settings only)

Use this when the two-modem PC runs Windows. This is the manual version of
the split: Windows prefers one adapter (the game line) for everything, and
apps that support binding (qBittorrent) are pinned to the other adapter
(the download line). Weaker than the Linux script — Windows has no clean
per-app routing without a driver — but it covers the biggest traffic
(torrents) and it's fully reversible.

## Setup

1. **Wire it right.** Ethernet cable = the low-ping line (game line).
   Wi-Fi = the second line (download line). Latency doesn't matter for
   downloads; it decides games.

2. **Make the game line the default.** Windows sometimes prefers the wrong
   adapter. Force it with metrics (lower number = preferred):
   - Settings → Network & internet → Advanced network settings → pick the
     Ethernet adapter → "View additional properties" is *not* where metrics
     live; use the classic panel: `Win+R` → `ncpa.cpl` → right-click the
     Ethernet adapter → Properties → Internet Protocol Version 4 (TCP/IPv4)
     → Properties → Advanced → untick "Automatic metric" → Interface metric: **10**
   - Do the same on the Wi-Fi adapter with metric **50**.
   - PowerShell equivalent (run as Administrator):
     `Set-NetIPInterface -InterfaceAlias "Ethernet" -AddressFamily IPv4 -InterfaceMetric 10`
     `Set-NetIPInterface -InterfaceAlias "Wi-Fi" -AddressFamily IPv4 -InterfaceMetric 50`
     (Adapter names vary — check with `Get-NetAdapter`.)

3. **Pin the torrent client to the download line.**
   qBittorrent → Tools → Options → Advanced:
   - "Network Interface" = the Wi-Fi adapter
   - (or) "Optional IP address to bind to" = the Wi-Fi adapter's IPv4
     (find it with `ipconfig`)
   Restart qBittorrent after changing this.

4. **Know the limit.** Steam downloads, browsers and everything that can't
   bind still use the default route = game line. On Windows that's the honest
   state of the art without a driver (ForceBindIP exists but is old and
   unreliable — not recommended). This limit is *the* reason SplitLine v1 is
   a router wizard, not a Windows app.

## Verify it worked

1. Start a big torrent download.
2. Task Manager → Performance: Wi-Fi should be saturated, Ethernet near idle.
3. In game (or `ping 1.1.1.1 -t` in a console): ping stays at its normal
   value while the torrent maxes out. That's the whole pitch, felt.

## Undo

Re-tick "Automatic metric" on both adapters (or
`Set-NetIPInterface ... -AutomaticMetric Enabled`) and set qBittorrent's
network interface back to "Any interface".
