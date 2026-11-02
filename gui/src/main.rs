//! SplitLine GUI (GPUI) — a native desktop front-end for the SplitLine CLI.
//!
//! Architecture rule: this app contains NO routing logic. Every action is a
//! subprocess call to the Python CLI (`splitline`), which owns detection,
//! planning, verification and rollback. The GUI is presentation only, so the
//! safety properties in ../SECURITY.md hold identically for GUI users.
//!
//! Elevation: on Linux, apply/revert run through `pkexec` (the CLI saves its
//! state as root, so status/revert go through pkexec too, to see that same
//! state). On Windows/macOS the CLI is called directly for now — run the GUI
//! from an elevated shell there (see gui/README.md).
//!
//! Status: scaffold v0.1. Not yet compiled in Muse's sandbox (no Rust
//! toolchain there); first build happens on saturn, where notesec builds.

#![forbid(unsafe_code)]

use gpui::{
    div, prelude::*, px, rgb, size, App, Application, Bounds, Context, FontWeight,
    MouseButton, Window, WindowBounds, WindowOptions,
};
use serde::Deserialize;
use std::env;
use std::process::Command;

const BG: u32 = 0x16181d;
const PANEL: u32 = 0x1f232b;
const PANEL_HOVER: u32 = 0x262b36;
const TEXT: u32 = 0xe8eaf0;
const DIM: u32 = 0x9aa3b2;
const GAME: u32 = 0x2ea043;
const BULK: u32 = 0x2f6fed;
const DANGER: u32 = 0xb3392f;
const NEUTRAL: u32 = 0x39404d;

#[derive(Clone, Debug, Deserialize)]
struct Iface {
    name: String,
    ip: String,
    gateway: String,
    metric: Option<i64>,
}

// ---------------------------------------------------------------------------
// CLI plumbing
// ---------------------------------------------------------------------------

/// Base command for the Python CLI. Override with SPLITLINE_CMD
/// (e.g. "splitline" once installed, default: python3 -m splitline.cli).
fn cli_base() -> Vec<String> {
    if let Ok(v) = env::var("SPLITLINE_CMD") {
        let parts: Vec<String> = v.split_whitespace().map(str::to_owned).collect();
        if !parts.is_empty() {
            return parts;
        }
    }
    vec!["python3".into(), "-m".into(), "splitline.cli".into()]
}

fn cli_command(args: &[&str], elevated: bool) -> Command {
    let base = cli_base();
    let mut argv: Vec<String> = Vec::new();
    if elevated && cfg!(target_os = "linux") {
        argv.push("pkexec".into());
    }
    argv.extend(base.iter().cloned());
    argv.extend(args.iter().map(|s| s.to_string()));
    let mut cmd = Command::new(&argv[0]);
    cmd.args(&argv[1..]);
    if let Ok(home) = env::var("SPLITLINE_HOME") {
        cmd.current_dir(home);
    }
    cmd
}

fn run_cli(args: &[&str], elevated: bool) -> (bool, String) {
    match cli_command(args, elevated).output() {
        Ok(out) => {
            let mut text = String::from_utf8_lossy(&out.stdout).into_owned();
            let err = String::from_utf8_lossy(&out.stderr).into_owned();
            if !err.trim().is_empty() {
                text.push_str(&err);
            }
            (out.status.success(), text)
        }
        Err(e) => (false, format!("failed to start the splitline CLI: {e}")),
    }
}

fn tail(text: &str, max_lines: usize) -> String {
    let lines: Vec<&str> = text.lines().collect();
    if lines.len() > max_lines {
        lines[lines.len() - max_lines..].join("\n")
    } else {
        text.to_string()
    }
}

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

struct SplitLineView {
    ifaces: Vec<Iface>,
    game: Option<String>,
    bulk: Option<String>,
    status: String,
    output: String,
}

impl SplitLineView {
    fn new() -> Self {
        let mut view = SplitLineView {
            ifaces: Vec::new(),
            game: None,
            bulk: None,
            status: "Detecting interfaces…".into(),
            output: String::new(),
        };
        view.refresh();
        view
    }

    fn refresh(&mut self) {
        let (ok, text) = run_cli(&["detect", "--json"], false);
        if ok {
            match serde_json::from_str::<Vec<Iface>>(text.trim()) {
                Ok(ifaces) => {
                    self.status = format!("{} interface(s) detected.", ifaces.len());
                    if self.game.is_none() {
                        self.game = ifaces.first().map(|i| i.name.clone());
                    }
                    if self.bulk.is_none() {
                        self.bulk = ifaces.get(1).map(|i| i.name.clone());
                    }
                    self.ifaces = ifaces;
                }
                Err(e) => {
                    self.status = format!("Detection returned unparsable output: {e}");
                    self.output = text;
                }
            }
        } else {
            self.status = "Detection failed — is the splitline CLI reachable? \
                           (run from the repo root or set SPLITLINE_CMD)"
                .into();
            self.output = text;
        }
    }

    fn selection_error(&self) -> Option<String> {
        match (&self.game, &self.bulk) {
            (None, _) => Some("Pick a game line first.".into()),
            (_, None) => Some("Pick a bulk line first.".into()),
            (Some(g), Some(b)) if g == b => {
                Some("Game line and bulk line must be different interfaces.".into())
            }
            _ => None,
        }
    }

    fn preview(&mut self) {
        if let Some(e) = self.selection_error() {
            self.status = e;
            return;
        }
        let (ok, text) = run_cli(
            &["apply", self.game.as_deref().unwrap(), self.bulk.as_deref().unwrap()],
            false,
        );
        self.status = if ok {
            "Plan preview (nothing was changed).".into()
        } else {
            "The CLI refused this plan — see output.".into()
        };
        self.output = text;
    }

    fn apply(&mut self) {
        if let Some(e) = self.selection_error() {
            self.status = e;
            return;
        }
        let (ok, text) = run_cli(
            &[
                "apply",
                self.game.as_deref().unwrap(),
                self.bulk.as_deref().unwrap(),
                "--yes",
            ],
            true,
        );
        self.status = if ok {
            "Split applied and verified. 🎮".into()
        } else {
            "Apply failed or was rolled back — see output.".into()
        };
        self.output = text;
    }

    fn revert(&mut self) {
        let (ok, text) = run_cli(&["revert"], true);
        self.status = if ok {
            "Reverted — all SplitLine changes removed.".into()
        } else {
            "Revert reported a problem — see output.".into()
        };
        self.output = text;
    }

    fn check_status(&mut self) {
        let (ok, text) = run_cli(&["status"], cfg!(target_os = "linux"));
        self.status = if ok { text.trim().to_string() } else { "Status failed.".into() };
    }

    fn iface_row(
        &self,
        iface: &Iface,
        selected: bool,
        accent: u32,
        cx: &mut Context<Self>,
        target_game: bool,
    ) -> impl IntoElement {
        let name = iface.name.clone();
        div()
            .flex()
            .flex_row()
            .justify_between()
            .items_center()
            .w_full()
            .px_3()
            .py_2()
            .mb_1()
            .rounded_md()
            .cursor_pointer()
            .bg(if selected { rgb(accent) } else { rgb(PANEL) })
            .hover(|s| s.bg(rgb(PANEL_HOVER)))
            .on_mouse_down(
                MouseButton::Left,
                cx.listener(move |this, _event, _window, cx| {
                    if target_game {
                        this.game = Some(name.clone());
                    } else {
                        this.bulk = Some(name.clone());
                    }
                    cx.notify();
                }),
            )
            .child(
                div()
                    .flex()
                    .flex_col()
                    .child(div().font_weight(FontWeight::SEMIBOLD).child(iface.name.clone()))
                    .child(
                        div()
                            .text_sm()
                            .text_color(rgb(if selected { 0xffffff } else { DIM }))
                            .child(format!(
                                "ip {} · gateway {}",
                                iface.ip, iface.gateway
                            )),
                    ),
            )
            .child(if selected { "●" } else { "○" })
    }
}

fn action_button<F>(
    label: &'static str,
    bg: u32,
    cx: &mut Context<SplitLineView>,
    f: F,
) -> impl IntoElement
where
    F: Fn(&mut SplitLineView, &mut Context<SplitLineView>) + 'static,
{
    div()
        .px_3()
        .py_2()
        .rounded_md()
        .cursor_pointer()
        .bg(rgb(bg))
        .text_color(rgb(0xffffff))
        .font_weight(FontWeight::SEMIBOLD)
        .hover(|s| s.opacity(0.85))
        .on_mouse_down(
            MouseButton::Left,
            cx.listener(move |this, _event, _window, cx| {
                f(this, cx);
                cx.notify();
            }),
        )
        .child(label)
}

impl Render for SplitLineView {
    fn render(&mut self, _window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let game_rows: Vec<_> = self
            .ifaces
            .iter()
            .map(|i| {
                let sel = self.game.as_deref() == Some(i.name.as_str());
                self.iface_row(i, sel, GAME, cx, true).into_any_element()
            })
            .collect();
        let bulk_rows: Vec<_> = self
            .ifaces
            .iter()
            .map(|i| {
                let sel = self.bulk.as_deref() == Some(i.name.as_str());
                self.iface_row(i, sel, BULK, cx, false).into_any_element()
            })
            .collect();

        div()
            .flex()
            .flex_col()
            .h_full()
            .w_full()
            .bg(rgb(BG))
            .text_color(rgb(TEXT))
            .p_4()
            // header
            .child(
                div()
                    .flex()
                    .flex_row()
                    .justify_between()
                    .items_center()
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .child(
                                div()
                                    .text_2xl()
                                    .font_weight(FontWeight::BOLD)
                                    .child("SplitLine"),
                            )
                            .child(
                                div()
                                    .text_sm()
                                    .text_color(rgb(DIM))
                                    .child("One line for the game. One line for everything else."),
                            ),
                    )
                    .child(action_button("↻ Refresh", NEUTRAL, cx, |this, _cx| {
                        this.refresh()
                    })),
            )
            // status
            .child(
                div()
                    .mt_3()
                    .text_sm()
                    .text_color(rgb(DIM))
                    .child(self.status.clone()),
            )
            // pickers
            .child(
                div()
                    .flex()
                    .flex_row()
                    .gap_3()
                    .mt_4()
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .flex_1()
                            .child(
                                div()
                                    .mb_2()
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .child("🎮 Game line (protected)"),
                            )
                            .children(game_rows),
                    )
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .flex_1()
                            .child(
                                div()
                                    .mb_2()
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .child("⬇ Bulk line (downloads / uploads)"),
                            )
                            .children(bulk_rows),
                    ),
            )
            // actions
            .child(
                div()
                    .flex()
                    .flex_row()
                    .gap_2()
                    .mt_4()
                    .child(action_button("Preview plan", NEUTRAL, cx, |this, _cx| {
                        this.preview()
                    }))
                    .child(action_button("Apply split", GAME, cx, |this, _cx| {
                        this.apply()
                    }))
                    .child(action_button("Status", NEUTRAL, cx, |this, _cx| {
                        this.check_status()
                    }))
                    .child(action_button("Revert", DANGER, cx, |this, _cx| {
                        this.revert()
                    })),
            )
            // output
            .child(
                div()
                    .flex()
                    .flex_col()
                    .flex_1()
                    .mt_4()
                    .p_3()
                    .rounded_md()
                    .bg(rgb(PANEL))
                    .overflow_hidden()
                    .child(
                        div()
                            .text_sm()
                            .text_color(rgb(DIM))
                            .child(tail(&self.output, 40)),
                    ),
            )
    }
}

fn main() {
    Application::new().run(|cx: &mut App| {
        let bounds = Bounds::centered(None, size(px(880.0), px(640.0)), cx);
        cx.open_window(
            WindowOptions {
                window_bounds: Some(WindowBounds::Windowed(bounds)),
                ..Default::default()
            },
            |_window, cx| cx.new(|_cx| SplitLineView::new()),
        )
        .unwrap();
        cx.activate(true);
    });
}
