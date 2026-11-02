# Vendored `xattr` 0.2.3 — with ONE fix

This is an unmodified copy of the crates.io `xattr` crate **0.2.3**
(Steven Allen, MIT/Apache-2.0, see LICENSE-MIT), vendored for exactly one
reason:

**The fix (in `src/sys/mod.rs`):** newer `libc` releases removed the
`ENOATTR` constant on Linux (glibc never had it as a distinct error), so
`xattr 0.2.3` no longer compiles against current `libc` — it breaks the
GPUI build through `zed-async-tar`, which pins `xattr = "0.2"`. On Linux,
`ENOATTR` is exactly `ENODATA`, so the vendored copy defines it that way
under `#[cfg(target_os = "linux")]` and keeps `::libc::ENOATTR` everywhere
else. Nothing else was changed.

Wired in via `[patch.crates-io]` in `gui/Cargo.toml`. **Remove this vendor
directory and the patch section** as soon as the GPUI dependency tree
compiles against a fixed upstream `xattr` (or `zed-async-tar` moves off
`xattr 0.2`) — vendoring is a splint, not a lifestyle.
