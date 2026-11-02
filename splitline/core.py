"""Core engine: command running, interface validation, plan execution with
rollback, post-apply verification, and state persistence.

Security properties (see SECURITY.md):
- Commands are always argv lists passed to subprocess — never shell strings,
  never eval. User-supplied interface names are validated against the list of
  interfaces the OS actually reports, plus a strict character whitelist.
- Mutations require an explicit --yes at the CLI layer; planning is pure.
- Every plan step carries its own undo. A failed step or a failed
  verification rolls back everything that was already applied.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

IFACE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\- ]{1,64}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class SplitLineError(Exception):
    """Any refusal or failure the user should see as a clean message."""


# --------------------------------------------------------------------------
# Command running
# --------------------------------------------------------------------------

@dataclass
class CompletedCmd:
    argv: list
    returncode: int
    stdout: str
    stderr: str


class SubprocessRunner:
    """The real runner. argv lists only — a shell is never involved."""

    def run(self, argv):
        proc = subprocess.run(
            [str(a) for a in argv],
            capture_output=True, text=True, timeout=30,
        )
        return CompletedCmd(list(argv), proc.returncode, proc.stdout, proc.stderr)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class Interface:
    name: str
    ip: str = ""
    gateway: str = ""
    metric: int | None = None
    is_up: bool = True

    def __str__(self):
        return (f"{self.name}: ip={self.ip or '-'} gateway={self.gateway or '-'} "
                f"metric={self.metric if self.metric is not None else '-'}")


@dataclass
class Step:
    """One mutating command plus the command that undoes it (if any)."""
    description: str
    argv: list
    undo_argv: list | None = None


@dataclass
class Plan:
    backend: str
    game_iface: str
    bulk_iface: str
    steps: list = field(default_factory=list)
    notes: list = field(default_factory=list)   # instructions for the user

    def describe(self):
        lines = [f"Plan ({self.backend}): game={self.game_iface} bulk={self.bulk_iface}"]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"  {i}. {s.description}")
            lines.append(f"     $ {' '.join(str(a) for a in s.argv)}")
        for n in self.notes:
            lines.append(f"  note: {n}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate_iface(name, known):
    """An interface name is accepted only if the OS itself reported it."""
    if not isinstance(name, str) or not IFACE_NAME_RE.match(name):
        raise SplitLineError(f"Invalid interface name: {name!r}")
    names = {i.name for i in known}
    if name not in names:
        raise SplitLineError(
            f"Interface {name!r} not found. Detected: {', '.join(sorted(names)) or 'none'}")
    return name


def validate_ip(ip, what="IP address"):
    if not IP_RE.match(ip or ""):
        raise SplitLineError(f"Invalid {what}: {ip!r}")
    if any(int(p) > 255 for p in ip.split(".")):
        raise SplitLineError(f"Invalid {what}: {ip!r}")
    return ip


def get_iface(name, known):
    validate_iface(name, known)
    for i in known:
        if i.name == name:
            if not i.ip:
                raise SplitLineError(f"{name} has no IPv4 address — is it connected?")
            if not i.gateway:
                raise SplitLineError(f"{name} has no gateway — is it connected?")
            return i
    raise SplitLineError(f"Interface {name!r} not found.")  # unreachable


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def state_path(platform=None):
    platform = platform or sys.platform
    if platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "SplitLine" / "state.json"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "splitline" / "state.json"


def save_state(plan, path=None):
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "backend": plan.backend,
        "game_iface": plan.game_iface,
        "bulk_iface": plan.bulk_iface,
        "steps": [{"argv": s.argv, "undo_argv": s.undo_argv} for s in plan.steps],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def load_state(path=None):
    path = path or state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SplitLineError(f"State file is unreadable ({e}). Run `splitline heal`.")


def clear_state(path=None):
    path = path or state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------
# Execution: apply with rollback, revert, verify
# --------------------------------------------------------------------------

def execute_plan(plan, runner, log=print):
    """Run steps in order. Any failure undoes everything done so far."""
    done = []
    try:
        for step in plan.steps:
            log(f"+ {' '.join(str(a) for a in step.argv)}")
            res = runner.run(step.argv)
            if res.returncode != 0:
                raise SplitLineError(
                    f"Step failed ({step.description}): {res.stderr.strip() or res.stdout.strip()}")
            done.append(step)
    except SplitLineError:
        log("Failure — rolling back applied steps…")
        _rollback(done, runner, log)
        raise
    return done


def _rollback(steps, runner, log=print):
    for step in reversed(steps):
        if step.undo_argv:
            log(f"- undo: {' '.join(str(a) for a in step.undo_argv)}")
            runner.run(step.undo_argv)   # best effort; never raise from rollback


def revert_from_state(runner, path=None, log=print):
    state = load_state(path)
    if not state:
        raise SplitLineError("No SplitLine state found — nothing to revert.")
    steps = [Step("(from state)", s["argv"], s.get("undo_argv"))
             for s in state.get("steps", [])]
    _rollback(steps, runner, log)
    clear_state(path)
    log("Reverted. All SplitLine routing changes are removed.")


def verify_split(backend, game, bulk, runner):
    """Each connection must still reach the internet on its own interface."""
    problems = []
    for iface in (game, bulk):
        if not backend.probe_iface(runner, iface):
            problems.append(f"{iface.name} cannot reach the internet after apply")
    return problems
