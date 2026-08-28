#!/usr/bin/env python3
"""
Manage the hermes-desktop remote-desktop stack (virtual display + VNC +
Chromium) used for human-machine collaboration.

Runs INSIDE the hermes-desktop container (image repo: hermes-hitl-environment):
every desktop service is owned by supervisord (on-demand, autostart=false).
This script drives supervisorctl — it does NOT spawn raw processes.

Lifecycle rule: run `start` BEFORE the collaboration begins (idempotent —
checks each service and starts only the missing ones) and `stop` AFTER it
ends. Scripts that need the user to see the screen must follow the same
start/stop rule around their collaboration window.

Components (supervisord services, in start order):
    pulseaudio, xvfb (虚拟桌面), openbox, chromium, x11vnc (VNC :5900),
    novnc (:6080). Chromium is the SHARED instance: humans watch it over VNC,
    agents attach via CDP :9222 — same persistent profile (/data/chromium).

Usage:
    python ensure_remote_desktop.py status           # report service states
    python ensure_remote_desktop.py start [--url U]  # start missing services
    python ensure_remote_desktop.py stop             # close the whole stack

stdout carries one JSON document ({{status, msg, data}}); progress notes go to
stderr. Exit code 0 on success, 1 on error. Optional --url opens a new tab in
the shared Chromium via its CDP endpoint once it is ready.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# Dependency order — must match launch-desktop.sh.
SERVICES = ["pulseaudio", "xvfb", "openbox", "chromium", "x11vnc", "novnc"]

CDP_BASE = "http://127.0.0.1:9222"


def emit(status: str, msg: str, data: dict | None = None) -> None:
    print(json.dumps({"status": status, "msg": msg, "data": data or {}},
                     ensure_ascii=False, indent=2))


def _supervisorctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["supervisorctl", *args],
                          capture_output=True, text=True, timeout=30)


def service_states() -> tuple[dict, str | None]:
    """{service: {running, pid}} for every desktop service, or (None, error)."""
    try:
        result = _supervisorctl("status", *SERVICES)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return None, f"supervisorctl unavailable: {e}"
    states: dict = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        name, status = parts[0], parts[1]
        pid = None
        if status == "RUNNING":
            m = line.rsplit("pid ", 1)
            if len(m) == 2:
                try:
                    pid = int(m[1].split()[0])
                except ValueError:
                    pass
        states[name] = {"running": status == "RUNNING", "pid": pid}
    return states, None


def cmd_status() -> int:
    states, err = service_states()
    if err:
        emit("error", err)
        return 1
    ready = all(s["running"] for s in states.values())
    emit("ok", f"remote desktop {'ready' if ready else 'not ready'}", states)
    return 0


def _wait_until(predicate, timeout: float, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_BASE}/json/version", timeout=2):
            return True
    except OSError:
        return False


def _open_url(url: str) -> str | None:
    """Open a new tab in the shared Chromium via CDP /json/new (PUT, GET fallback)."""
    endpoint = f"{CDP_BASE}/json/new?{urllib.parse.quote(url, safe='')}"
    for method in ("PUT", "GET"):
        req = urllib.request.Request(endpoint, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())["id"]
        except OSError:
            continue
    return None


def cmd_start(url: str | None) -> int:
    states, err = service_states()
    if err:
        emit("error", err)
        return 1

    for svc in SERVICES:
        if states.get(svc, {}).get("running"):
            continue
        print(f"[ensure_remote_desktop] starting {svc}", file=sys.stderr)
        result = _supervisorctl("start", svc)
        if result.returncode != 0:
            emit("error", f"supervisorctl start {svc} failed: "
                          f"{(result.stderr or result.stdout).strip()[:300]}",
                 states)
            return 1
        states, err = service_states()
        if err:
            emit("error", err)
            return 1

    if url:
        # Chromium may take a few seconds to expose CDP; the /json/new endpoint
        # creates a new tab (does not touch the shared profile's logins).
        if not _wait_until(_cdp_ready, timeout=30):
            print("[ensure_remote_desktop] warning: CDP not ready — "
                  f"could not open {url}", file=sys.stderr)
        else:
            tab_id = _open_url(url)
            print(f"[ensure_remote_desktop] opened {url} "
                  f"({'tab ' + tab_id if tab_id else 'failed'})", file=sys.stderr)

    ready = all(s["running"] for s in states.values())
    if ready:
        emit("ok", "remote desktop ready", states)
        return 0
    emit("error", "remote desktop start incomplete",
         {k: v for k, v in states.items() if not v["running"]})
    return 1


def cmd_stop() -> int:
    states, err = service_states()
    if err:
        emit("error", err)
        return 1
    # Reverse dependency order: browser first, display last.
    for svc in reversed(SERVICES):
        if not states.get(svc, {}).get("running"):
            continue
        print(f"[ensure_remote_desktop] stopping {svc}", file=sys.stderr)
        result = _supervisorctl("stop", svc)
        if result.returncode != 0:
            emit("error", f"supervisorctl stop {svc} failed: "
                          f"{(result.stderr or result.stdout).strip()[:300]}",
                 states)
            return 1
        states, err = service_states()
        if err:
            emit("error", err)
            return 1
    emit("ok", "remote desktop stack closed", states)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure (status/start/stop) the hermes-desktop VNC + "
                    "virtual display + Chromium stack (supervisord-managed) "
                    "for human-machine collaboration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report whether the desktop services are running")
    p_start = sub.add_parser("start", help="start missing services (idempotent)")
    p_start.add_argument("--url", default=None,
                         help="open this URL in a new tab of the shared Chromium")
    sub.add_parser("stop", help="close the whole stack")
    args = parser.parse_args()

    if platform.system() == "Windows":
        emit("error", "ensure_remote_desktop.py runs inside the hermes-desktop "
                      "container (supervisord-managed Xvfb/x11vnc/chromium); "
                      "not supported on Windows")
        return 1

    if args.command == "status":
        return cmd_status()
    if args.command == "start":
        return cmd_start(args.url)
    return cmd_stop()


if __name__ == "__main__":
    sys.exit(main())
