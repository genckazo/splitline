"""OS backends. Each backend can DETECT interfaces and PLAN a split.

Planning never mutates anything. Plans are data (see core.Plan) — the core
engine executes them with rollback. Backends differ because the OSes differ:

- Linux:   full policy routing (bulk routing table + source rule + fwmark
           rule + optional per-user iptables marks). The main table — the
           game line — is never edited.
- Windows: adapter metrics (game line preferred) + optional destination
           routes via the bulk gateway + client-binding notes. There is NO
           per-app routing on Windows without a kernel driver, and SplitLine
           deliberately ships no driver (anti-cheat safety, see SPEC.md).
- macOS:   a pf anchor with route-to rules for the bulk destinations you
           name, plus client-binding notes. Anchor is namespaced
           (com.splitline) and flushed on revert.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re

from .core import Interface, Plan, SplitLineError, Step, get_iface, validate_ip

TABLE_ID = 200
FWMARK = "0x200"


def _networks(cidrs, what="destination"):
    out = []
    for c in cidrs or []:
        try:
            out.append(str(ipaddress.ip_network(c, strict=False)))
        except ValueError:
            raise SplitLineError(f"Invalid {what} CIDR: {c!r}")
    return out


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

class LinuxBackend:
    name = "linux"

    def detect(self, runner):
        addr = runner.run(["ip", "-j", "addr"])
        routes = runner.run(["ip", "-j", "route", "show", "default"])
        if addr.returncode != 0:
            raise SplitLineError("`ip` command failed — is iproute2 installed?")
        gw = {}
        if routes.returncode == 0:
            for r in json.loads(routes.stdout or "[]"):
                if r.get("dev") and r.get("gateway"):
                    gw.setdefault(r["dev"], (r["gateway"], r.get("metric")))
        ifaces = []
        for link in json.loads(addr.stdout or "[]"):
            name = link.get("ifname", "")
            if name == "lo" or link.get("operstate") == "DOWN":
                continue
            ip = ""
            for a in link.get("addr_info", []):
                if a.get("family") == "inet":
                    ip = a.get("local", "")
                    break
            g, m = gw.get(name, ("", None))
            ifaces.append(Interface(name, ip, g, m, True))
        return ifaces

    def plan_apply(self, game_name, bulk_name, known, runner=None, mark_uids=()):
        game = get_iface(game_name, known)
        bulk = get_iface(bulk_name, known)
        if game.name == bulk.name:
            raise SplitLineError("Game and bulk interfaces must differ.")
        plan = Plan(self.name, game.name, bulk.name)

        table_registered = False
        if runner is not None:
            res = runner.run(["cat", "/etc/iproute2/rt_tables"])
            table_registered = res.returncode == 0 and \
                re.search(rf"^{TABLE_ID}\s", res.stdout or "", re.M) is not None
        if not table_registered:
            plan.steps.append(Step(
                "Register the 'bulk' routing table (id 200)",
                ["sh", "-c",
                 f"grep -q '^{TABLE_ID}[[:space:]]' /etc/iproute2/rt_tables 2>/dev/null "
                 f"|| echo '{TABLE_ID} bulk' >> /etc/iproute2/rt_tables"],
                None))  # leaving the name registered is harmless; no undo
        plan.steps.append(Step(
            f"Bulk table default route via {bulk.name}",
            ["ip", "route", "replace", "default", "via", bulk.gateway,
             "dev", bulk.name, "table", str(TABLE_ID)],
            ["ip", "route", "flush", "table", str(TABLE_ID)]))
        plan.steps.append(Step(
            f"Traffic sourced from {bulk.ip} ({bulk.name}) uses the bulk table",
            ["ip", "rule", "add", "from", bulk.ip, "table", str(TABLE_ID),
             "priority", "100"],
            ["ip", "rule", "del", "from", bulk.ip, "table", str(TABLE_ID),
             "priority", "100"]))
        plan.steps.append(Step(
            f"Packets marked {FWMARK} use the bulk table",
            ["ip", "rule", "add", "fwmark", FWMARK, "table", str(TABLE_ID),
             "priority", "101"],
            ["ip", "rule", "del", "fwmark", FWMARK, "table", str(TABLE_ID),
             "priority", "101"]))
        for uid in mark_uids:
            if not str(uid).isdigit():
                raise SplitLineError(f"Invalid uid for marking: {uid!r}")
            base = ["iptables", "-t", "mangle"]
            plan.steps.append(Step(
                f"All traffic of uid {uid} is marked for the bulk line",
                base + ["-A", "OUTPUT", "-m", "owner", "--uid-owner", str(uid),
                        "-j", "MARK", "--set-mark", FWMARK],
                base + ["-D", "OUTPUT", "-m", "owner", "--uid-owner", str(uid),
                        "-j", "MARK", "--set-mark", FWMARK]))
        plan.steps.append(Step(
            "Flush the route cache",
            ["ip", "route", "flush", "cache"], None))
        plan.notes.append(
            f"Bind download apps to the bulk line: qBittorrent > Options > "
            f"Advanced > Network Interface = {bulk.name} (or bind IP {bulk.ip}).")
        plan.notes.append(
            "Apps run under a marked uid (see --mark-uid) ride the bulk line "
            "with no binding at all.")
        return plan

    def probe_iface(self, runner, iface):
        return runner.run(["ping", "-I", iface.name, "-c", "1", "-W", "2",
                           "1.1.1.1"]).returncode == 0


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

_PS_DETECT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$cfgs = Get-NetIPConfiguration | Where-Object { $_.IPv4Address } | ForEach-Object {"
    "  [PSCustomObject]@{ name=$_.InterfaceAlias;"
    "    ip=$_.IPv4Address[0].IPAddress;"
    "    gateway=($_.IPv4DefaultGateway | Select-Object -First 1).NextHop;"
    "    metric=(Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex"
    "             -AddressFamily IPv4).InterfaceMetric } };"
    " $cfgs | ConvertTo-Json -Compress"
)


class WindowsBackend:
    name = "windows"

    def detect(self, runner):
        res = runner.run(["powershell", "-NoProfile", "-Command", _PS_DETECT])
        if res.returncode != 0 or not (res.stdout or "").strip():
            raise SplitLineError("PowerShell network detection failed.")
        data = json.loads(res.stdout)
        if isinstance(data, dict):
            data = [data]
        return [Interface(d.get("name", ""), d.get("ip") or "",
                          d.get("gateway") or "", d.get("metric"))
                for d in data if d.get("name")]

    def plan_apply(self, game_name, bulk_name, known, runner=None, bulk_routes=()):
        game = get_iface(game_name, known)
        bulk = get_iface(bulk_name, known)
        if game.name == bulk.name:
            raise SplitLineError("Game and bulk interfaces must differ.")
        plan = Plan(self.name, game.name, bulk.name)

        def ps(script):
            return ["powershell", "-NoProfile", "-Command", script]

        plan.steps.append(Step(
            f"Prefer the game line ({game.name}) — interface metric 10",
            ps(f"Set-NetIPInterface -InterfaceAlias '{game.name}' "
               f"-AddressFamily IPv4 -InterfaceMetric 10"),
            ps(f"Set-NetIPInterface -InterfaceAlias '{game.name}' "
               f"-AddressFamily IPv4 -AutomaticMetric Enabled")))
        plan.steps.append(Step(
            f"Deprefer the bulk line ({bulk.name}) — interface metric 50",
            ps(f"Set-NetIPInterface -InterfaceAlias '{bulk.name}' "
               f"-AddressFamily IPv4 -InterfaceMetric 50"),
            ps(f"Set-NetIPInterface -InterfaceAlias '{bulk.name}' "
               f"-AddressFamily IPv4 -AutomaticMetric Enabled")))
        for net in _networks(bulk_routes):
            n = ipaddress.ip_network(net)
            plan.steps.append(Step(
                f"Route {net} via the bulk gateway {bulk.gateway}",
                ["route", "add", str(n.network_address), "mask",
                 str(n.netmask), bulk.gateway],
                ["route", "delete", str(n.network_address), "mask",
                 str(n.netmask), bulk.gateway]))
        plan.notes.append(
            f"Bind qBittorrent to the bulk line: Options > Advanced > Network "
            f"Interface = {bulk.name} (or bind IP {bulk.ip}).")
        plan.notes.append(
            "Windows has no per-app routing without a kernel driver; SplitLine "
            "ships none on purpose (anti-cheat safety). Apps that cannot bind "
            "follow the default route — the game line.")
        plan.notes.append("Run from an elevated (Administrator) terminal.")
        return plan

    def probe_iface(self, runner, iface):
        if not iface.ip:
            return False
        return runner.run(["ping", "-S", iface.ip, "-n", "1", "-w", "2000",
                           "1.1.1.1"]).returncode == 0


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

class MacBackend:
    name = "macos"
    ANCHOR = "com.splitline"
    ANCHOR_PATH = "/etc/pf.anchors/com.splitline"

    def detect(self, runner):
        ports = runner.run(["networksetup", "-listallhardwareports"])
        devices = re.findall(r"Device:\s*(\S+)", ports.stdout or "")
        default = runner.run(["route", "-n", "get", "default"])
        default_iface = ""
        default_gw = ""
        m = re.search(r"interface:\s*(\S+)", default.stdout or "")
        if m:
            default_iface = m.group(1)
        m = re.search(r"gateway:\s*(\S+)", default.stdout or "")
        if m:
            default_gw = m.group(1)
        ifaces = []
        for dev in devices:
            ip_res = runner.run(["ipconfig", "getifaddr", dev])
            ip = (ip_res.stdout or "").strip() if ip_res.returncode == 0 else ""
            gw = default_gw if dev == default_iface else ""
            if not gw and ip:
                pkt = runner.run(["ipconfig", "getpacket", dev])
                m = re.search(r"router \(ip_mult\): \{([\d.]+)\}", pkt.stdout or "")
                if m:
                    gw = m.group(1)
            if ip:
                ifaces.append(Interface(dev, ip, gw))
        return ifaces

    def plan_apply(self, game_name, bulk_name, known, runner=None, bulk_dests=()):
        game = get_iface(game_name, known)
        bulk = get_iface(bulk_name, known)
        if game.name == bulk.name:
            raise SplitLineError("Game and bulk interfaces must differ.")
        plan = Plan(self.name, game.name, bulk.name)
        dests = _networks(bulk_dests)
        if dests:
            dest_list = ", ".join(dests)
            content = (f"# SplitLine anchor — managed by splitline, do not edit\n"
                       f"pass out route-to ({bulk.name} {bulk.gateway}) inet "
                       f"proto {{ tcp udp }} from any to {{ {dest_list} }}\n")
            b64 = base64.b64encode(content.encode()).decode()
            plan.steps.append(Step(
                f"Write the pf anchor {self.ANCHOR_PATH}",
                ["sh", "-c", f"echo {b64} | base64 -d > {self.ANCHOR_PATH}"],
                ["rm", "-f", self.ANCHOR_PATH]))
            plan.steps.append(Step(
                f"Load the pf anchor {self.ANCHOR}",
                ["pfctl", "-a", self.ANCHOR, "-f", self.ANCHOR_PATH],
                ["pfctl", "-a", self.ANCHOR, "-F", "all"]))
            plan.steps.append(Step(
                "Make sure pf is enabled",
                ["pfctl", "-E"], None))  # never disabled on revert: may predate us
        else:
            plan.notes.append(
                "No bulk destinations given: macOS gets no route-to rules. "
                "Re-run apply with --bulk-dest <CIDR> for the download "
                "servers/services you want on the bulk line.")
        plan.notes.append(
            f"Bind qBittorrent to the bulk line: Preferences > Advanced > "
            f"Network Interface = {bulk.name} (or bind IP {bulk.ip}) — binding "
            f"needs no pf rules at all.")
        plan.notes.append(
            "pf anchors must also be referenced from /etc/pf.conf to survive "
            "reboots; SplitLine v0.2 anchors are session-scoped on purpose "
            "(a reboot is a full clean reset).")
        return plan

    def probe_iface(self, runner, iface):
        if not iface.ip:
            return False
        validate_ip(iface.ip)
        return runner.run(["ping", "-c", "1", "-t", "2", "-S", iface.ip,
                           "1.1.1.1"]).returncode == 0


BACKENDS = {"linux": LinuxBackend, "windows": WindowsBackend, "darwin": MacBackend}


def get_backend(platform=None):
    import sys
    p = platform or sys.platform
    if p.startswith("linux"):
        cls = LinuxBackend
    elif p.startswith("win"):
        cls = WindowsBackend
    elif p == "darwin":
        cls = MacBackend
    else:
        raise SplitLineError(f"Unsupported platform: {p}")
    return cls()
