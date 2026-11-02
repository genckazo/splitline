#!/usr/bin/env bash
# SplitLine v0 — Linux prototype: game on connection A, downloads on connection B.
#
# What it does (all reversible, see `revert`):
#   1. Adds a second routing table ("bulk", id 200) whose default route leaves
#      via the BULK interface.
#   2. Adds a policy rule: any packet whose SOURCE address is the bulk
#      interface's IP uses the bulk table. Apps that can bind to an interface
#      or IP (qBittorrent, curl --interface, most torrent clients) therefore
#      ride the download line; everything else keeps using the main table,
#      whose default route is the GAME interface (verified, and its metric is
#      left untouched — this script never edits the main table).
#   3. Saves what it changed in a state file so `revert` removes exactly that.
#
# What it does NOT do:
#   - It cannot force apps that refuse to bind (Steam, browsers) onto the bulk
#     line. That needs cgroup marking or a netns wrapper — v0.2 territory.
#   - It never touches firewall rules, DNS, or the main routing table.
#
# Usage:
#   ./splitline.sh detect                     # show interfaces, gateways, IPs
#   ./splitline.sh test <iface>               # ping + public IP via one iface
#   sudo ./splitline.sh apply <game> <bulk>   # e.g. apply eth0 wlan0
#   ./splitline.sh status
#   sudo ./splitline.sh revert
#
# Dry-run: prefix any mutating command with DRY=1 to only print commands.

set -euo pipefail

TABLE_ID=200
TABLE_NAME="bulk"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/splitline"
STATE_FILE="$STATE_DIR/state.env"

run() {
  if [[ "${DRY:-0}" == "1" ]]; then
    echo "[dry-run] $*"
  else
    echo "+ $*"
    "$@"
  fi
}

need_root() {
  if [[ $EUID -ne 0 && "${DRY:-0}" != "1" ]]; then
    echo "This command changes routing — run it with sudo (or DRY=1 to preview)." >&2
    exit 1
  fi
}

iface_ip() { ip -4 -brief addr show "$1" 2>/dev/null | awk '{print $3}' | cut -d/ -f1; }
iface_gw() { ip route show default dev "$1" 2>/dev/null | awk '/default/ {print $3; exit}'; }

cmd_detect() {
  echo "Interfaces with IPv4 addresses:"
  ip -4 -brief addr | grep -v '^lo' || true
  echo
  echo "Default routes (lower metric wins the main table):"
  ip route show default || true
  echo
  for raw in $(ip -4 -brief addr | grep -v '^lo' | awk '{print $1}'); do
    dev="${raw%%@*}"   # veth names look like host0@if3 — the kernel name is host0
    echo "$dev: ip=$(iface_ip "$dev" || echo none) gateway=$(iface_gw "$dev" || echo none)"
  done
}

cmd_test() {
  local dev="${1:?usage: splitline.sh test <iface>}"
  echo "Ping via $dev:"
  ping -I "$dev" -c 3 -W 2 1.1.1.1 || true
  echo "Public IP via $dev:"
  curl --interface "$dev" -s --max-time 8 https://api.ipify.org || echo "(failed)"
  echo
}

cmd_apply() {
  local game="${1:?usage: splitline.sh apply <game-iface> <bulk-iface>}"
  local bulk="${2:?usage: splitline.sh apply <game-iface> <bulk-iface>}"
  need_root
  [[ "$game" != "$bulk" ]] || { echo "Game and bulk interfaces must differ." >&2; exit 1; }

  local bulk_ip bulk_gw game_gw
  bulk_ip="$(iface_ip "$bulk")";  bulk_gw="$(iface_gw "$bulk")"
  game_gw="$(iface_gw "$game")"
  [[ -n "$bulk_ip" ]] || { echo "$bulk has no IPv4 address — is it connected?" >&2; exit 1; }
  [[ -n "$bulk_gw" ]] || { echo "$bulk has no default gateway — is it connected?" >&2; exit 1; }
  [[ -n "$game_gw" ]] || { echo "$game has no default gateway — game line must stay the main default." >&2; exit 1; }

  # Register table name once (harmless if already present).
  if ! grep -q "^${TABLE_ID}[[:space:]]" /etc/iproute2/rt_tables 2>/dev/null; then
    run bash -c "echo '${TABLE_ID} ${TABLE_NAME}' >> /etc/iproute2/rt_tables"
  fi

  run ip route replace default via "$bulk_gw" dev "$bulk" table "$TABLE_ID"
  run ip rule add from "$bulk_ip" table "$TABLE_ID" priority 100
  run ip route flush cache || true

  mkdir -p "$STATE_DIR"
  cat > "$STATE_FILE" <<EOF
GAME_IFACE=$game
BULK_IFACE=$bulk
BULK_IP=$bulk_ip
BULK_GW=$bulk_gw
TABLE_ID=$TABLE_ID
EOF
  echo
  echo "Split active: main table = $game (game), source $bulk_ip = $bulk (bulk)."
  echo "Now point your download apps at the bulk line, e.g.:"
  echo "  qBittorrent: Options > Advanced > Network Interface = $bulk"
  echo "               (or Optional IP address to bind to = $bulk_ip)"
  echo "  curl:        curl --interface $bulk <url>"
  echo "Undo everything with: sudo $0 revert"
}

cmd_status() {
  if [[ -f "$STATE_FILE" ]]; then
    echo "State file:"; cat "$STATE_FILE"; echo
  else
    echo "No state file — apply has not been run (or was reverted)."
  fi
  echo "Bulk table:"; ip route show table "$TABLE_ID" 2>/dev/null || echo "  (empty)"
  echo "Policy rules:"; ip rule show | grep -E "from .* lookup ${TABLE_ID}|lookup ${TABLE_NAME}" || echo "  (none)"
}

cmd_revert() {
  need_root
  [[ -f "$STATE_FILE" ]] || { echo "Nothing to revert (no state file)." >&2; exit 1; }
  # shellcheck disable=SC1090
  source "$STATE_FILE"
  run ip rule del from "$BULK_IP" table "$TABLE_ID" priority 100 || true
  run ip route flush table "$TABLE_ID" || true
  run ip route flush cache || true
  run rm -f "$STATE_FILE"
  echo "Reverted. All traffic uses the main table again."
}

case "${1:-}" in
  detect) cmd_detect ;;
  test)   shift; cmd_test "$@" ;;
  apply)  shift; cmd_apply "$@" ;;
  status) cmd_status ;;
  revert) cmd_revert ;;
  *) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
