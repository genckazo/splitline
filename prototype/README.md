# SplitLine v0 prototype — Linux split script

`splitline.sh` proves the SplitLine outcome on any Linux box with two live
connections (e.g. Ethernet to modem 1 + Wi-Fi to modem 2). It is a lab tool,
not the product. **Run nothing as root until you've read it** — `DRY=1` prints
every command without executing.

## Quick start

```bash
chmod +x splitline.sh
./splitline.sh detect                 # find your two interface names + gateways
./splitline.sh test eth0               # latency + public IP of the game line
./splitline.sh test wlan0              # latency + public IP of the bulk line
DRY=1 sudo ./splitline.sh apply eth0 wlan0   # preview
sudo ./splitline.sh apply eth0 wlan0         # activate
./splitline.sh status
sudo ./splitline.sh revert             # undo everything, guaranteed
```

## How it works

- The main routing table is never edited: your game line stays the default
  route for the whole machine.
- A second table (`bulk`, 200) gets a default route via the bulk interface.
- One policy rule — "packets sourced from the bulk interface's IP use the bulk
  table" — sends bind-capable apps out the download line.

## After applying, point the big apps at the bulk line

- **qBittorrent:** Options → Advanced → "Network Interface" = bulk interface
  (or "Optional IP address to bind to" = the bulk IP shown by `status`).
- **curl:** `curl --interface <bulk-iface> <url>`
- **Verification:** `./splitline.sh test <iface>` on both interfaces should
  show two different public IPs, and starting a fat torrent download should
  leave `ping` on the game interface flat.

## Known v0 limits (honest)

- Apps that can't bind (Steam downloads, browsers) still ride the game line.
  v0.2 candidates: cgroup v2 marking + `fwmark` rule, or a `bulk` network
  namespace with a launcher (`splitline run <app>`).
- Wi-Fi bulk is fine (latency doesn't matter for downloads); game line should
  be the wired / lower-ping one.
- If an interface's IP changes (DHCP), re-run `revert` then `apply`.
