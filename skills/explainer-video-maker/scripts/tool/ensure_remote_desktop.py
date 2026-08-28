#!/usr/bin/env python3
"""
Manage the remote-desktop stack (virtual display + VNC + Chromium) used for
human-machine collaboration.

Lifecycle rule: run `start` BEFORE the collaboration begins (idempotent —
checks each component and starts only missing ones) and `stop` AFTER it ends.
Scripts that need the user to see the screen must follow the same start/stop
rule around their collaboration window.

Components (Linux/container):
  - Virtual display: Xvfb {DISPLAY} (TigerVNC `Xvnc` substitutes when Xvfb is
    absent — Xvnc bundles display + VNC in one process).
  - VNC: x11vnc attached to the Xvfb display.
  - Chromium: headed instance on the virtual display, identified by its
    --user-data-dir marker so `status` can find it.

Usage:
    python ensure_remote_desktop.py status           # report component state
    python ensure_remote_desktop.py start [--url U]  # start missing components
    python ensure_remote_desktop.py stop             # close the whole stack

stdout carries one JSON document ({{status, msg, data}}); progress notes go to
stderr. Exit code 0 on success, 1 on error.

Env overrides:
    RD_DISPLAY      display number, default :99
    RD_RESOLUTION   Xvfb screen geometry, default 1920x1080x24
    RD_STATE_DIR    state dir (pid files, logs, chromium profile); default
                    /tmp/remote_desktop — machine-level runtime state, not a
                    project artifact
    RD_VNC_PASSWORD set to require a VNC password (unset = no password)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


DISPLAY = os.environ.get("RD_DISPLAY", ":99")
RESOLUTION = os.environ.get("RD_RESOLUTION", "1920x1080x24")
STATE_DIR = Path(os.environ.get("RD_STATE_DIR", "/tmp/remote_desktop"))
VNC_PASSWORD = os.environ.get("RD_VNC_PASSWORD", "")
CHROMIUM_PROFILE = STATE_DIR / "chromium_profile"
_DISPLAY_ESC = DISPLAY.replace(":", r"\:")
_VNC_MARKER = rf"x11vnc.*{_DISPLAY_ESC}|Xvnc {_DISPLAY_ESC}"
_DISPLAY_MARKER = rf"(Xvfb|Xvnc) {_DISPLAY_ESC}"
_CHROMIUM_MARKER = rf"chromium.*{CHROMIUM_PROFILE}"


def emit(status: str, msg: str, data: dict | None = None) -> None:
    print(json.dumps({"status": status, "msg": msg, "data": data or {}},
                     ensure_ascii=False, indent=2))


def _which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _pids(marker: str) -> list[int]:
    try:
        result = subprocess.run(["pgrep", "-f", marker],
                                capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    pids = []
    for line in result.stdout.split():
        try:
            pids.append(int(line))
        except ValueError:
            pass
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pidfile(name: str) -> Path:
    return STATE_DIR / f"{name}.pid"


def _read_pid(name: str) -> int | None:
    path = _pidfile(name)
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except ValueError:
        return None


def _write_pid(name: str, pid: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _pidfile(name).write_text(str(pid))


def _clear_pid(name: str) -> None:
    _pidfile(name).unlink(missing_ok=True)


def component_state(name: str, marker: str) -> dict:
    """Tracked pid first, then pgrep fallback (stale pid files are cleaned up)."""
    pid = _read_pid(name)
    if pid and not _alive(pid):
        _clear_pid(name)
        pid = None
    if pid:
        return {"name": name, "running": True, "pid": pid}
    pids = _pids(marker)
    return {"name": name, "running": bool(pids), "pid": pids[0] if pids else None}


def _daemonize(cmd: list[str], env: dict | None, log_name: str) -> int:
    """Start a background process detached from this script, record its pid."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(STATE_DIR / f"{log_name}.log", "ab")
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.Popen(cmd, stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, start_new_session=True,
                            env=full_env)
    return proc.pid


def _display_socket() -> Path:
    num = DISPLAY.lstrip(":").split(".")[0]
    return Path(f"/tmp/.X11-unix/X{num}")


def _window_size() -> str:
    width, _, rest = RESOLUTION.partition("x")
    height = rest.split("x", 1)[0] or "1080"
    return f"{width},{height}"


def _collect() -> dict:
    return {
        "display": component_state("display", _DISPLAY_MARKER),
        "vnc": component_state("vnc", _VNC_MARKER),
        "chromium": component_state("chromium", _CHROMIUM_MARKER),
    }


def cmd_status() -> int:
    comps = _collect()
    ready = all(c["running"] for c in comps.values())
    emit("ok", f"remote desktop {'ready' if ready else 'not ready'} on {DISPLAY}", comps)
    return 0


def cmd_start(url: str | None) -> int:
    comps = _collect()
    problems: list[str] = []

    if not comps["display"]["running"]:
        xvfb, xvnc = _which("Xvfb"), _which("Xvnc")
        if xvfb:
            pid = _daemonize([xvfb, DISPLAY, "-screen", "0", RESOLUTION,
                              "-nolisten", "tcp"], None, "display")
            _write_pid("display", pid)
            socket = _display_socket()
            for _ in range(50):  # wait up to ~5s for the X socket
                if socket.exists():
                    break
                time.sleep(0.1)
            comps = _collect()
        elif xvnc:
            pid = _daemonize([xvnc, DISPLAY, "-geometry", _window_size().replace(",", "x"),
                              "-depth", "24"], None, "display")
            _write_pid("display", pid)
            time.sleep(1.0)
            comps = _collect()
        else:
            problems.append("neither Xvfb nor Xvnc found — install xvfb + x11vnc "
                            "(or tigervnc-standalone-server) in the container")

    if comps["display"]["running"] and not comps["vnc"]["running"]:
        # Xvnc covers VNC itself; x11vnc only needed for a separate Xvfb display.
        x11vnc = _which("x11vnc")
        if x11vnc:
            args = [x11vnc, "-display", DISPLAY, "-forever", "-shared", "-quiet"]
            if VNC_PASSWORD:
                args += ["-passwd", VNC_PASSWORD]
            else:
                args += ["-nopw"]
            pid = _daemonize(args, None, "vnc")
            _write_pid("vnc", pid)
            time.sleep(1.0)
            comps = _collect()
        else:
            problems.append("x11vnc not found — install x11vnc (or use TigerVNC Xvnc "
                            "as the display, which serves VNC itself)")

    if not comps["chromium"]["running"]:
        chrome = _which("chromium", "chromium-browser", "google-chrome",
                        "google-chrome-stable")
        if chrome:
            args = [chrome, "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                    "--no-first-run", f"--user-data-dir={CHROMIUM_PROFILE}",
                    f"--window-size={_window_size()}"]
            if url:
                args.append(url)
            pid = _daemonize(args, {"DISPLAY": DISPLAY}, "chromium")
            _write_pid("chromium", pid)
            time.sleep(2.0)
            comps = _collect()
        else:
            problems.append("chromium not found — install chromium (or google-chrome) "
                            "in the container")

    ready = all(c["running"] for c in comps.values())
    if ready:
        emit("ok", f"remote desktop ready on {DISPLAY}", comps)
        return 0
    msg = "remote desktop start incomplete: " + "; ".join(problems or
          [f"{name} not running" for name, c in comps.items() if not c["running"]])
    emit("error", msg, comps)
    return 1


def _terminate(pid: int | None, marker: str, grace: float = 3.0) -> None:
    pids = [pid] if pid and _alive(pid) else _pids(marker)
    if not pids:
        return
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + grace
    while time.time() < deadline:
        if not any(_alive(p) for p in pids):
            return
        time.sleep(0.2)
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass


def cmd_stop() -> int:
    comps = _collect()
    if comps["chromium"]["running"]:
        _terminate(comps["chromium"]["pid"], _CHROMIUM_MARKER)
        _clear_pid("chromium")
    if comps["vnc"]["running"]:
        _terminate(comps["vnc"]["pid"], _VNC_MARKER)
        _clear_pid("vnc")
    if comps["display"]["running"]:
        _terminate(comps["display"]["pid"], _DISPLAY_MARKER)
        _clear_pid("display")
    emit("ok", f"remote desktop stack closed on {DISPLAY}", {})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure (start/stop/status) the VNC + virtual display + "
                    "Chromium stack for human-machine collaboration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report whether display/VNC/Chromium are running")
    p_start = sub.add_parser("start", help="start missing components (idempotent)")
    p_start.add_argument("--url", default=None,
                         help="URL for Chromium to open on the virtual display")
    sub.add_parser("stop", help="close the whole stack")
    args = parser.parse_args()

    if platform.system() == "Windows":
        emit("error", "ensure_remote_desktop.py targets the Linux container "
                      "(Xvfb/x11vnc/chromium); not supported on Windows")
        return 1

    if args.command == "status":
        return cmd_status()
    if args.command == "start":
        return cmd_start(args.url)
    return cmd_stop()


if __name__ == "__main__":
    sys.exit(main())
