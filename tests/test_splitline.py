import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splitline import cli
from splitline.backends import LinuxBackend, MacBackend, WindowsBackend
from splitline.core import (CompletedCmd, Interface, SplitLineError,
                            execute_plan, load_state, save_state, clear_state,
                            validate_iface)

LINUX_ADDR = json.dumps([
    {"ifname": "eth0", "operstate": "UP",
     "addr_info": [{"family": "inet", "local": "192.168.1.10"}]},
    {"ifname": "wlan0", "operstate": "UP",
     "addr_info": [{"family": "inet", "local": "192.168.2.10"}]},
    {"ifname": "lo", "operstate": "UNKNOWN",
     "addr_info": [{"family": "inet", "local": "127.0.0.1"}]},
])
LINUX_ROUTES = json.dumps([
    {"dst": "default", "gateway": "192.168.1.1", "dev": "eth0", "metric": 100},
    {"dst": "default", "gateway": "192.168.2.1", "dev": "wlan0", "metric": 600},
])
WIN_JSON = json.dumps([
    {"name": "Ethernet", "ip": "192.168.1.10", "gateway": "192.168.1.1", "metric": 25},
    {"name": "Wi-Fi", "ip": "192.168.2.10", "gateway": "192.168.2.1", "metric": 30},
])


class FakeRunner:
    def __init__(self, handler):
        self.calls = []
        self.handler = handler

    def run(self, argv):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        return self.handler(argv)


def ok(argv):
    return CompletedCmd(argv, 0, "", "")


def linux_handler(fail_on=None):
    def h(argv):
        if argv[:3] == ["ip", "-j", "addr"]:
            return CompletedCmd(argv, 0, LINUX_ADDR, "")
        if argv[:3] == ["ip", "-j", "route"]:
            return CompletedCmd(argv, 0, LINUX_ROUTES, "")
        if argv[0] == "cat":
            return CompletedCmd(argv, 0, "100\tlocal\n200\tbulk\n", "")
        if fail_on and fail_on in " ".join(argv):
            return CompletedCmd(argv, 1, "", "simulated failure")
        return ok(argv)
    return h


class LinuxDetectTest(unittest.TestCase):
    def test_detect_parses_interfaces(self):
        r = FakeRunner(linux_handler())
        ifaces = LinuxBackend().detect(r)
        by_name = {i.name: i for i in ifaces}
        self.assertEqual(by_name["eth0"].gateway, "192.168.1.1")
        self.assertEqual(by_name["wlan0"].ip, "192.168.2.10")
        self.assertNotIn("lo", by_name)


class LinuxPlanTest(unittest.TestCase):
    def setUp(self):
        self.backend = LinuxBackend()
        self.known = self.backend.detect(FakeRunner(linux_handler()))

    def test_plan_routes_bulk_only(self):
        plan = self.backend.plan_apply("eth0", "wlan0", self.known,
                                       runner=FakeRunner(linux_handler()))
        joined = [" ".join(s.argv) for s in plan.steps]
        self.assertTrue(any("table 200" in j and "192.168.2.1" in j for j in joined))
        self.assertTrue(any("rule add from 192.168.2.10" in j for j in joined))
        self.assertTrue(any("fwmark 0x200" in j for j in joined))
        # The game interface must never be a mutation target.
        for s in plan.steps:
            self.assertNotIn("eth0", " ".join(s.argv))

    def test_same_iface_refused(self):
        with self.assertRaises(SplitLineError):
            self.backend.plan_apply("eth0", "eth0", self.known)

    def test_injection_name_refused(self):
        with self.assertRaises(SplitLineError):
            self.backend.plan_apply("eth0; rm -rf /", "wlan0", self.known)
        with self.assertRaises(SplitLineError):
            validate_iface("$(reboot)", self.known)

    def test_bad_uid_refused(self):
        with self.assertRaises(SplitLineError):
            self.backend.plan_apply("eth0", "wlan0", self.known,
                                    mark_uids=("1000; reboot",))


class RollbackTest(unittest.TestCase):
    def test_failed_step_rolls_back(self):
        backend = LinuxBackend()
        known = backend.detect(FakeRunner(linux_handler()))
        plan = backend.plan_apply("eth0", "wlan0", known,
                                  runner=FakeRunner(linux_handler()))
        r = FakeRunner(linux_handler(fail_on="rule add from"))
        with self.assertRaises(SplitLineError):
            execute_plan(plan, r, log=lambda *a: None)
        flat = [" ".join(c) for c in r.calls]
        self.assertTrue(any("route flush table 200" in f for f in flat),
                        "rollback must flush the bulk table")


class WindowsPlanTest(unittest.TestCase):
    def setUp(self):
        self.backend = WindowsBackend()
        r = FakeRunner(lambda a: CompletedCmd(a, 0, WIN_JSON, ""))
        self.known = self.backend.detect(r)

    def test_detect(self):
        self.assertEqual({i.name for i in self.known}, {"Ethernet", "Wi-Fi"})

    def test_metrics_plan(self):
        plan = self.backend.plan_apply("Ethernet", "Wi-Fi", self.known)
        joined = [" ".join(s.argv) for s in plan.steps]
        self.assertTrue(any("InterfaceMetric 10" in j and "Ethernet" in j for j in joined))
        self.assertTrue(any("InterfaceMetric 50" in j and "Wi-Fi" in j for j in joined))
        self.assertTrue(all(s.undo_argv for s in plan.steps))

    def test_bulk_route_and_bad_cidr(self):
        plan = self.backend.plan_apply("Ethernet", "Wi-Fi", self.known,
                                       bulk_routes=("203.0.113.0/24",))
        joined = [" ".join(s.argv) for s in plan.steps]
        self.assertTrue(any("route add 203.0.113.0 mask 255.255.255.0" in j for j in joined))
        with self.assertRaises(SplitLineError):
            self.backend.plan_apply("Ethernet", "Wi-Fi", self.known,
                                    bulk_routes=("not-a-cidr",))


class MacPlanTest(unittest.TestCase):
    def setUp(self):
        self.backend = MacBackend()
        self.known = [Interface("en0", "192.168.1.10", "192.168.1.1"),
                      Interface("en1", "192.168.2.10", "192.168.2.1")]

    def test_anchor_plan_with_dests(self):
        plan = self.backend.plan_apply("en0", "en1", self.known,
                                       bulk_dests=("203.0.113.0/24",))
        joined = [" ".join(s.argv) for s in plan.steps]
        self.assertTrue(any("pfctl" in j and "com.splitline" in j for j in joined))

    def test_no_dests_means_no_mutation(self):
        plan = self.backend.plan_apply("en0", "en1", self.known)
        self.assertEqual(plan.steps, [])
        self.assertTrue(plan.notes)


class StateTest(unittest.TestCase):
    def test_roundtrip(self):
        backend = LinuxBackend()
        known = backend.detect(FakeRunner(linux_handler()))
        plan = backend.plan_apply("eth0", "wlan0", known,
                                  runner=FakeRunner(linux_handler()))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            save_state(plan, path)
            state = load_state(path)
            self.assertEqual(state["game_iface"], "eth0")
            self.assertEqual(len(state["steps"]), len(plan.steps))
            clear_state(path)
            self.assertIsNone(load_state(path))


class CliDryRunTest(unittest.TestCase):
    def test_apply_defaults_to_dry_run(self):
        r = FakeRunner(linux_handler())
        lines = []
        rc = cli.main(["apply", "eth0", "wlan0"], runner=r,
                      backend=LinuxBackend(), out=lines.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any("Dry run" in l for l in lines))
        mutating = [c for c in r.calls if c[:2] == ["ip", "rule"]]
        self.assertEqual(mutating, [], "dry run must not change routing")


class CliJsonTest(unittest.TestCase):
    def test_detect_json(self):
        r = FakeRunner(linux_handler())
        lines = []
        rc = cli.main(["detect", "--json"], runner=r,
                      backend=LinuxBackend(), out=lines.append)
        self.assertEqual(rc, 0)
        data = json.loads(lines[0])
        self.assertEqual({d["name"] for d in data}, {"eth0", "wlan0"})
        self.assertEqual(data[0]["gateway"], "192.168.1.1")


if __name__ == "__main__":
    unittest.main()
