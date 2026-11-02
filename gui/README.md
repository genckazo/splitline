# SplitLine GUI (GPUI)

A native desktop front-end for SplitLine, built with
[GPUI](https://www.gpui.rs) — the GPU-accelerated Rust UI framework from the
Zed team (the same stack as g's notesec).

## Design rule

**The GUI contains no routing logic.** Every button is a subprocess call to
the Python CLI (`splitline detect --json`, `apply`, `revert`, `status`).
Detection, planning, verification and rollback live in exactly one place —
the CLI core — so the guarantees in `../SECURITY.md` are identical no
matter which front-end you use.

- **Preview plan** — dry-run apply, prints the plan, changes nothing.
- **Apply split** — on Linux runs the CLI through `pkexec` (polkit prompt);
  state is saved by that elevated process, so status/revert use `pkexec`
  too. On Windows/macOS the CLI is called directly for now: run the GUI
  from an elevated shell there (polish item, not a safety gap — the CLI
  itself still refuses to run unelevated).
- **Revert** — removes everything the state file records.

## Build & run (Linux)

You need a Rust toolchain and the usual GPUI system libraries
(typical Debian/Arch names: `libxkbcommon-dev`, `libfontconfig-dev`,
`libfreetype-dev`, `pkg-config`, a C toolchain).

```sh
cd splitline/gui
SPLITLINE_HOME=.. cargo run --release
```

`SPLITLINE_HOME` tells the GUI where the Python package lives (it runs
`python3 -m splitline.cli` from that directory). After installing the CLI
properly (`pip install ..`), you can instead set
`SPLITLINE_CMD="splitline"`.

## Status

Scaffold v0.1 (2026-11-02). Written against the GPUI 0.2 API; **not yet
compiled** — Muse's sandbox has no Rust toolchain. First build is expected
on saturn (where notesec builds). Expect the usual first-build API fixes;
the layout and CLI wiring are the substance of this scaffold.

## Build note: vendored `xattr` patch

The first saturn build (2026-11-02) failed inside `xattr 0.2.3` (pulled in
by GPUI's `zed-async-tar`): current `libc` no longer exports `ENOATTR` on
Linux. `vendor/xattr/` is upstream 0.2.3 with a one-line-class fix
(`ENOATTR = ENODATA` on Linux), wired via `[patch.crates-io]` in
`Cargo.toml`. Details in `vendor/xattr/README.md`. Delete the patch once
the upstream tree builds clean without it.
