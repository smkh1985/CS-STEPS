#!/usr/bin/env python3
"""Record a screencast of VS Code writing, compiling and running an empty C++ program.

Requirements (Linux, X11 session): ffmpeg (with x11grab), xdotool, g++, VS Code (`code`).

Usage:
    python3 record.py                  # writes recording.mp4
    python3 record.py -o demo.mp4 --fps 30 --type-delay 60
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

CPP_SOURCE = """#include <iostream>

int main() {
    return 0;
}
"""

# A tiny extension (vscode-helper/) loaded into the throwaway profile: it reports which editor
# line is at the top and scrolls to a line on HELPER_KEY, without moving the cursor.
HELPER_SOURCE = Path(__file__).resolve().parent / "vscode-helper"
HELPER_COMMAND = "lessonHelper.scroll"
HELPER_KEY = "ctrl+alt+shift+F12"

# Throwaway VS Code profile: no auto-closing brackets/indent/suggestions, so typed
# text lands exactly as written, and no welcome pages or prompts in the recording.
VSCODE_SETTINGS = {
    "editor.autoClosingBrackets": "never",
    "editor.autoClosingQuotes": "never",
    "editor.autoClosingComments": "never",  # typing /* must not add */ by itself
    "editor.autoSurround": "never",  # typing "(" over a selection must replace it, not wrap it
    "editor.autoIndent": "none",
    "editor.formatOnType": False,
    "editor.quickSuggestions": {"other": False, "comments": False, "strings": False},
    "editor.suggestOnTriggerCharacters": False,
    "editor.acceptSuggestionOnEnter": "off",
    "editor.parameterHints.enabled": False,
    "editor.fontSize": 20,
    "terminal.integrated.fontSize": 18,
    # Nerd Fonts so the zsh prompt's icons render (same fonts as the main VS Code setup).
    "editor.fontFamily": "'JetBrainsMono Nerd Font', 'monospace'",
    "terminal.integrated.fontFamily": "'JetBrainsMonoNL NFM', 'JetBrainsMono NFM', monospace",
    "terminal.integrated.enablePersistentSessions": False,
    "terminal.integrated.confirmOnExit": "never",
    "terminal.integrated.confirmOnKill": "never",
    "terminal.integrated.suggest.enabled": False,  # no "Show suggestions" hint in the terminal
    "files.simpleDialog.enable": True,  # Save As in an in-window input box the recording can type into
    "workbench.startupEditor": "none",
    "workbench.tips.enabled": False,
    "workbench.view.alwaysShowHeaderActions": True,
    "workbench.secondarySideBar.defaultVisibility": "hidden",  # explorer's New File button always visible
    "workbench.welcomePage.experimentalOnboarding": False,
    "workbench.welcomePage.walkthroughs.openOnInstall": False,
    "chat.disableAIFeatures": True,
    "workbench.enableExperiments": False,
    "security.workspace.trust.enabled": False,
    "update.mode": "none",
    "update.showReleaseNotes": False,
    "extensions.ignoreRecommendations": True,
    "telemetry.telemetryLevel": "off",
    "window.restoreWindows": "none",
    "window.newWindowDimensions": "maximized",
    "editor.smoothScrolling": True,
    "editor.stickyScroll.enabled": False,  # pinned lines would cover the top editor lines
    "editor.dragAndDrop": False,  # a `select:` starting inside a selection must not move the text  # `scroll:` glides to the line instead of jumping
    "terminal.integrated.commandsToSkipShell": [HELPER_COMMAND],  # scroll even from the terminal
}


EXTENSION_CACHE = Path(__file__).resolve().parent / ".vscode-extension-cache"


def link_extension(name: str, extensions_dir: Path) -> None:
    """Make an extension from your own VS Code (e.g. "ms-vscode.cpptools") available to the
    throwaway profile. It is copied once into EXTENSION_CACHE and linked from there, so your own
    installation is never touched and later recordings start quickly."""
    found = sorted(p for p in (Path.home() / ".vscode" / "extensions").glob(name + "-*")
                   if p.name[len(name) + 1:][:1].isdigit())  # the version follows: not "-themes"
    if not found:
        sys.exit(f"Extension {name!r} isn't installed in ~/.vscode/extensions")
    source = found[-1]  # the newest version
    cached = EXTENSION_CACHE / source.name
    if not cached.exists():
        print(f"Copying {source.name} into {EXTENSION_CACHE} (once)...", flush=True)
        shutil.copytree(source, cached, symlinks=True)
    (extensions_dir / source.name).symlink_to(cached, target_is_directory=True)


def run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def primary_monitor() -> tuple[int, int, int, int]:
    """Return (width, height, x, y) of the primary monitor (first one if none is primary)."""
    lines = run("xrandr", "--listmonitors").splitlines()[1:]
    geometry = re.compile(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)")
    monitors = [(line, geometry.search(line)) for line in lines]
    monitors = [(line, m) for line, m in monitors if m]
    if not monitors:
        sys.exit("Could not determine monitor geometry from xrandr")
    line, m = next(((l, m) for l, m in monitors if "*" in l), monitors[0])
    return tuple(int(v) for v in m.groups())


def keyboard_layout() -> dict[str, str]:
    out = run("setxkbmap", "-query")
    return dict(line.split(":", 1) for line in out.splitlines() if ":" in line)


def restore_keyboard_layout(layout: dict[str, str]) -> None:
    cmd = ["setxkbmap", "-layout", layout.get("layout", "us").strip(),
           "-variant", layout.get("variant", "").strip()]
    if layout.get("model"):
        cmd += ["-model", layout["model"].strip()]
    if layout.get("options"):
        cmd += ["-option", "", "-option", layout["options"].strip()]
    subprocess.run(cmd, capture_output=True)


NOTIFICATIONS_KEY = ["org.gnome.desktop.notifications", "show-banners"]


def set_notification_banners(value: str | None) -> str | None:
    """Turn GNOME notification banners on/off ("true"/"false") and return the previous
    value, or None when gsettings isn't available (non-GNOME desktops)."""
    if not shutil.which("gsettings"):
        return None
    previous = subprocess.run(["gsettings", "get", *NOTIFICATIONS_KEY], capture_output=True, text=True).stdout.strip()
    if value is not None and previous:
        subprocess.run(["gsettings", "set", *NOTIFICATIONS_KEY, value], capture_output=True)
    return previous or None


def vscode_windows() -> set[str]:
    result = subprocess.run(["xdotool", "search", "--name", "Visual Studio Code"],
                            capture_output=True, text=True)
    return set(result.stdout.split())


def wait_for_new_window(existing: set[str], timeout: float = 60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        new = vscode_windows() - existing
        if new:
            return new.pop()
        time.sleep(0.5)
    sys.exit("VS Code window did not appear")


def focus(win: str) -> None:
    """Bring our window to the front; abort rather than type into some other window."""
    for _ in range(10):
        # getactivewindow fails while a native Wayland window (e.g. the terminal) has focus
        active = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True)
        if active.returncode == 0 and active.stdout.strip() == win:
            return
        subprocess.run(["xdotool", "windowraise", win], capture_output=True)
        subprocess.run(["xdotool", "windowactivate", win], capture_output=True)
        time.sleep(0.5)
    raise RuntimeError("Could not focus the VS Code window; aborting so keystrokes don't go elsewhere")


def xdotool_type(win: str, text: str, delay_ms: int) -> None:
    # Type line by line, re-checking focus each time.
    for line in text.splitlines(keepends=True):
        focus(win)
        run("xdotool", "type", "--clearmodifiers", "--delay", str(delay_ms), line)


def xdotool_key(win: str, *keys: str) -> None:
    focus(win)
    run("xdotool", "key", "--clearmodifiers", *keys)


def window_geometry(win: str) -> tuple[int, int, int, int]:
    """Return (width, height, x, y) of a window in absolute screen coordinates."""
    out = run("xwininfo", "-id", win)
    def field(name: str) -> int:
        return int(re.search(rf"{name}:\s+(-?\d+)", out).group(1))
    return field("Width"), field("Height"), field("Absolute upper-left X"), field("Absolute upper-left Y")


def place_window(win: str, monitor: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Make sure the (maximized) window is on the given monitor and return the capture
    region: the window clipped to the monitor, even-sized for yuv420p."""
    mon_w, mon_h, mon_x, mon_y = monitor
    w, h, x, y = window_geometry(win)
    if not (mon_x <= x + w // 2 < mon_x + mon_w and mon_y <= y + h // 2 < mon_y + mon_h):
        # Moving unmaximizes the window; maximize it again on the new monitor.
        run("xdotool", "windowmove", "--sync", win, str(mon_x + 100), str(mon_y + 100))
        xdotool_key(win, "super+Up")
        time.sleep(1)
        w, h, x, y = window_geometry(win)
    x, y = max(x, mon_x), max(y, mon_y)
    w = min(w, mon_x + mon_w - x)
    h = min(h, mon_y + mon_h - y)
    return w // 2 * 2, h // 2 * 2, x, y


def start_ffmpeg(display: str, region: tuple[int, int, int, int], fps: int, output: Path,
                 draw_mouse: bool = False, lossless: bool = False) -> subprocess.Popen:
    width, height, x, y = region
    # Lossless keeps full colour detail (4:4:4) for a later high-quality encode;
    # otherwise encode directly to a normal, widely playable file.
    encode = (["-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv444p"] if lossless
              else ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p"])
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "x11grab", "-framerate", str(fps), "-video_size", f"{width}x{height}",
        "-draw_mouse", str(int(draw_mouse)), "-i", f"{display}+{x},{y}",
        *encode, str(output),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    time.sleep(1)
    if proc.poll() is not None:
        raise RuntimeError("ffmpeg failed to start recording (see error above)")
    return proc


def stop_ffmpeg(proc: subprocess.Popen) -> None:
    # Sending 'q' lets ffmpeg finalize the MP4 container; killing it would corrupt the file.
    try:
        proc.communicate(b"q", timeout=15)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait()


class Recording:
    """A VS Code window being recorded; see vscode_recording()."""

    def __init__(self, win: str, region: tuple[int, int, int, int], work: Path,
                 ffmpeg: subprocess.Popen, started_at: float, helper: Path):
        self.win = win
        self.helper = helper  # the helper extension's folder (state.json, request.json)
        self.region = region  # (width, height, x, y) of the recorded area on screen
        self.work = work
        self.ffmpeg: subprocess.Popen | None = ffmpeg
        self.started_at = started_at  # time.monotonic() just before ffmpeg was launched
        self.stopped_at: float | None = None

    def editor_top(self) -> int:
        """The editor line currently shown at the top of the view."""
        return json.loads((self.helper / "state.json").read_text())["top"]

    def scroll_to(self, line: int, timeout: float = 3) -> None:
        """Smoothly scroll the editor so `line` is at the top; the cursor doesn't move."""
        (self.helper / "request.json").write_text(json.dumps({"top": line}))
        xdotool_key(self.win, HELPER_KEY)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.1)
            try:
                if self.editor_top() == line:
                    break
            except (OSError, ValueError):  # state.json is being rewritten
                pass
        time.sleep(0.3)  # let the smooth scroll settle

    def stop(self) -> None:
        if self.ffmpeg:
            self.stopped_at = time.monotonic()
            stop_ffmpeg(self.ffmpeg)
            self.ffmpeg = None


def check_requirements() -> None:
    for tool in ("ffmpeg", "xdotool", "xrandr", "xwininfo", "setxkbmap", "g++", "code"):
        if not shutil.which(tool):
            sys.exit(f"Missing required tool: {tool}")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        sys.exit("This script needs an X11 session (x11grab/xdotool don't work on Wayland)")


@contextmanager
def vscode_recording(work: Path, source_name: str | None, output: Path, fps: int,
                     show_mouse: bool = False, files: dict[str, str] | None = None,
                     fullscreen: bool = False, lossless: bool = False,
                     setup: list[str] | None = None, settings: dict | None = None,
                     extensions: list[str] | None = None, keybindings: list[dict] | None = None) -> Iterator[Recording]:
    """Open an empty `work/source_name` in a throwaway VS Code window and record that window.
    With source_name=None, open the `work` folder instead, with the sidebar hidden.
    `files` ({name: content}) are written into `work` first, e.g. code from a previous lesson,
    then the `setup` shell commands run there (e.g. compiling that code).
    `settings` are added to (or override) VSCODE_SETTINGS, e.g. a different terminal shell.

    On exit the recording is stopped, VS Code is closed and the keyboard layout restored.
    """
    display = os.environ.get("DISPLAY", ":0")
    # The profile lives next to `work`, so it doesn't show up in VS Code's explorer.
    profile = work.with_name(work.name + "-vscode-profile")

    # Fresh state each run: empty work folder and a clean profile with our settings.
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(profile, ignore_errors=True)
    work.mkdir(parents=True)
    for name, content in (files or {}).items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)  # e.g. .vscode/launch.json
        (work / name).write_text(content)
    for command in setup or []:
        subprocess.run(command, shell=True, cwd=work, check=True)
    (profile / "User").mkdir(parents=True)
    settings = {**VSCODE_SETTINGS, "terminal.integrated.cwd": str(work), **(settings or {})}
    (profile / "User" / "settings.json").write_text(json.dumps(settings, indent=2))
    (profile / "User" / "keybindings.json").write_text(json.dumps(
        [{"key": HELPER_KEY.lower(), "command": HELPER_COMMAND}] + list(keybindings or []), indent=2))
    helper = profile / "extensions" / "lesson.lesson-helper-0.0.1"
    shutil.copytree(HELPER_SOURCE, helper)
    for name in extensions or []:
        link_extension(name, profile / "extensions")
    target = work
    if source_name:
        target = work / source_name
        target.write_text("")

    monitor = primary_monitor()
    output.unlink(missing_ok=True)
    existing = vscode_windows()
    # xdotool mistypes shifted characters (e.g. '>' becomes '<') when several keyboard
    # layouts are configured, so use plain US while recording and restore afterwards.
    original_layout = keyboard_layout()
    subprocess.run(["setxkbmap", "us"], check=True)
    # Do Not Disturb: desktop notifications (e.g. "Low disk space") would end up in the video.
    original_banners = set_notification_banners("false")
    recording = None
    try:
        subprocess.Popen(
            # Our own extensions folder holds only the helper, so no other extension loads.
            ["code", "--new-window", "--user-data-dir", str(profile),
             "--extensions-dir", str(profile / "extensions"), str(target)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # Only ever touch the window this run opened, never a pre-existing VS Code window.
        win = wait_for_new_window(existing)
        focus(win)
        time.sleep(4)  # let the editor finish rendering before typing
        xdotool_key(win, "Escape")  # dismiss any first-run popup that slipped through
        if not source_name:
            xdotool_key(win, "ctrl+b")  # a fresh profile shows the explorer for folders; start hidden
            time.sleep(1)

        # Record only the VS Code window's area, measured after the window manager placed it.
        region = place_window(win, monitor)
        if fullscreen:
            # Full screen covers the dock and top bar, so the video is the monitor's full resolution.
            xdotool_key(win, "F11")
            time.sleep(2)
            region = place_window(win, monitor)
        if show_mouse:
            # Park the pointer in the middle of the window so it doesn't fly in from elsewhere.
            run("xdotool", "mousemove", str(region[2] + region[0] * 2 // 3), str(region[3] + region[1] // 2))
        print(f"Recording window {region[0]}x{region[1]}+{region[2]},{region[3]} -> {output}", flush=True)
        started_at = time.monotonic()
        ffmpeg = start_ffmpeg(display, region, fps, output, draw_mouse=show_mouse, lossless=lossless)
        recording = Recording(win, region, work, ffmpeg, started_at, helper)

        yield recording

        # Stop before quitting so the video doesn't end on whatever is behind the window.
        recording.stop()
        xdotool_key(win, "ctrl+q")
        deadline = time.time() + 15
        while win in vscode_windows() and time.time() < deadline:
            time.sleep(0.5)
    finally:
        if recording:
            recording.stop()
        restore_keyboard_layout(original_layout)
        if original_banners:
            set_notification_banners(original_banners)
        # Make sure the instance we started (and only that one) is gone.
        subprocess.run(["pkill", "-f", str(profile)], capture_output=True)
        time.sleep(2)
        subprocess.run(["pkill", "-9", "-f", str(profile)], capture_output=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", default="recording.mp4", help="output video file")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--type-delay", type=int, default=50, help="ms between typed characters")
    args = parser.parse_args()

    check_requirements()
    output = Path(args.output).resolve()
    work = Path(__file__).resolve().parent / "work"

    with vscode_recording(work, "main.cpp", output, args.fps) as rec:
        xdotool_type(rec.win, CPP_SOURCE, args.type_delay)
        xdotool_key(rec.win, "ctrl+s")
        time.sleep(1)

        # Open the integrated terminal, then compile and run.
        xdotool_key(rec.win, "ctrl+grave")
        time.sleep(3)
        command = f'cd "{work}" && g++ main.cpp -o main && ./main; echo "exit code: $?"\n'
        xdotool_type(rec.win, command, args.type_delay)
        time.sleep(4)  # compile + let the viewer read the output

    print(f"Saved {output}")


if __name__ == "__main__":
    main()
