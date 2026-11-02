"""SplitLine CLI.

Safe by default: `apply` only PRINTS the plan. Nothing on the machine
changes until `--yes` is passed. After a real apply, the result is verified
per interface; a failed verification rolls everything back automatically.
"""

from __future__ import annotations

import argparse
import os
import sys

from .backends import get_backend
from .core import (SplitLineError, SubprocessRunner, clear_state,
                   execute_plan, load_state, revert_from_state, save_state,
                   validate_iface, verify_split)


def _is_admin():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="splitline",
        description="One line for the game, one line for everything else.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect", help="List network interfaces, gateways, metrics")

    t = sub.add_parser("test", help="Check one interface reaches the internet")
    t.add_argument("iface")

    a = sub.add_parser("apply", help="Plan (and with --yes, apply) the split")
    a.add_argument("game", help="Interface of the gaming line")
    a.add_argument("bulk", help="Interface of the download/upload line")
    a.add_argument("--yes", action="store_true",
                   help="Actually change routing. Without this, only the plan is printed.")
    a.add_argument("--mark-uid", action="append", default=[], metavar="UID",
                   help="Linux only: send all traffic of this uid to the bulk line (repeatable)")
    a.add_argument("--bulk-route", action="append", default=[], metavar="CIDR",
                   help="Windows only: route this destination network via the bulk line (repeatable)")
    a.add_argument("--bulk-dest", action="append", default=[], metavar="CIDR",
                   help="macOS only: route traffic to this destination via the bulk line (repeatable)")

    sub.add_parser("revert", help="Remove every SplitLine routing change")
    sub.add_parser("status", help="Show the saved SplitLine state")
    sub.add_parser("heal", help="Detect a stale/broken state and clean it up")
    return p


def main(argv=None, runner=None, backend=None, out=print):
    args = build_parser().parse_args(argv)
    runner = runner or SubprocessRunner()
    backend = backend or get_backend()
    try:
        if args.cmd == "detect":
            ifaces = backend.detect(runner)
            if not ifaces:
                out("No interfaces with IPv4 addresses found.")
            for i in ifaces:
                out(str(i))
            return 0

        if args.cmd == "test":
            ifaces = backend.detect(runner)
            validate_iface(args.iface, ifaces)
            iface = next(i for i in ifaces if i.name == args.iface)
            ok = backend.probe_iface(runner, iface)
            out(f"{iface.name}: {'reachable' if ok else 'NOT reachable'}")
            return 0 if ok else 1

        if args.cmd == "apply":
            ifaces = backend.detect(runner)
            kwargs = {}
            if backend.name == "linux":
                kwargs["mark_uids"] = tuple(args.mark_uid)
            elif backend.name == "windows":
                kwargs["bulk_routes"] = tuple(args.bulk_route)
            elif backend.name == "macos":
                kwargs["bulk_dests"] = tuple(args.bulk_dest)
            plan = backend.plan_apply(args.game, args.bulk, ifaces,
                                      runner=runner, **kwargs)
            out(plan.describe())
            if not args.yes:
                out("\nDry run — nothing was changed. Re-run with --yes to apply.")
                return 0
            if not _is_admin():
                raise SplitLineError(
                    "Applying routing changes needs administrator/root. "
                    "Re-run elevated.")
            if load_state() is not None:
                raise SplitLineError(
                    "A SplitLine state already exists. Run `splitline revert` first.")
            execute_plan(plan, runner, log=out)
            game = next(i for i in ifaces if i.name == plan.game_iface)
            bulk = next(i for i in ifaces if i.name == plan.bulk_iface)
            problems = verify_split(backend, game, bulk, runner)
            if problems:
                out("Verification failed — rolling back everything:")
                for pr in problems:
                    out(f"  ! {pr}")
                from .core import _rollback
                _rollback(plan.steps, runner, log=out)
                raise SplitLineError("Apply was rolled back; your routing is unchanged.")
            save_state(plan)
            out("\nSplit is live and verified on both interfaces.")
            return 0

        if args.cmd == "revert":
            if not _is_admin():
                raise SplitLineError("Reverting routing changes needs administrator/root.")
            revert_from_state(runner, log=out)
            return 0

        if args.cmd == "status":
            state = load_state()
            if not state:
                out("No SplitLine split is recorded as active.")
            else:
                out(f"Active split ({state['backend']}): "
                    f"game={state['game_iface']} bulk={state['bulk_iface']} "
                    f"({len(state.get('steps', []))} applied steps)")
            return 0

        if args.cmd == "heal":
            state = load_state()
            if not state:
                out("No state file — nothing to heal.")
                return 0
            ifaces = backend.detect(runner)
            names = {i.name for i in ifaces}
            missing = [n for n in (state["game_iface"], state["bulk_iface"])
                       if n not in names]
            if missing:
                out(f"Stale state: interface(s) gone: {', '.join(missing)}. "
                    f"Cleaning up recorded rules…")
                if _is_admin():
                    revert_from_state(runner, log=out)
                else:
                    clear_state()
                    out("State file cleared (not elevated, so OS rules — if any "
                        "survived — need a reboot or an elevated revert).")
            else:
                out("State looks consistent with the current interfaces.")
            return 0

    except SplitLineError as e:
        out(f"splitline: {e}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
