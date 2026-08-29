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
    python ensure_remote_desktop.py notify "..." [--to platform] [--subject S]
                                                     # push reminder via the hermes
                                                     # messaging channel (hermes send);
                                                     # exit 1 => fall back to chat

stdout carries one JSON document ({{status, msg, data}}); progress notes go to
stderr. Exit code 0 on success, 1 on error. Optional --url opens a new tab in
the shared Chromium via its CDP endpoint once it is ready.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

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


def _hermes_targets() -> dict:
    """Configured messaging platforms from `hermes send --list --json`.

    NOTE: this reads the CACHED channel directory (~/.hermes/channel_directory.
    json), which stays empty until the gateway has run and discovered channels
    — platforms configured in ~/.hermes/config.yaml do NOT appear here.
    """
    hermes = shutil.which("hermes")
    if not hermes:
        return {}
    try:
        result = subprocess.run([hermes, "send", "--list", "--json"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        platforms = data.get("platforms", {}) if isinstance(data, dict) else {}
        return platforms if isinstance(platforms, dict) else {}
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def _has_credentials(pcfg: dict) -> bool:
    """Mirror gateway.config._is_platform_connected (permissive subset)."""
    if pcfg.get("token") or pcfg.get("api_key"):
        return True
    extra = pcfg.get("extra")
    if isinstance(extra, dict):
        # Weixin needs account_id + token.
        if extra.get("account_id") and (extra.get("token") or pcfg.get("token")):
            return True
    return False


def _has_home_channel(pcfg: dict, raw: dict, name: str) -> bool:
    hc = pcfg.get("home_channel")
    if isinstance(hc, dict) and (hc.get("chat_id") or hc.get("id")):
        return True
    # Top-level scalar homes are bridged into the env by `hermes send`
    # (e.g. `hermes config set TELEGRAM_HOME_CHANNEL <id>`).
    return f"{name.upper()}_HOME_CHANNEL" in {k: v for k, v in raw.items()
                                              if isinstance(v, str)}


def _config_platforms() -> tuple[list[str], list[str]]:
    """Platforms configured in ~/.hermes/config.yaml (the surface
    `hermes gateway setup` / `hermes config set` write).

    Returns (with_home_channel, with_credentials_only) in config order — the
    home-channel ones are preferred targets for a push.
    """
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    cfg = home / "config.yaml"
    if not cfg.exists():
        return [], []
    try:
        import yaml
    except ImportError:
        return [], []
    try:
        raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], []
    platforms = raw.get("platforms") or {}
    if not isinstance(platforms, dict):
        return [], []
    with_home, with_creds = [], []
    for name, pcfg in platforms.items():
        if not isinstance(pcfg, dict) or not _has_credentials(pcfg):
            continue
        if _has_home_channel(pcfg, raw, name):
            with_home.append(name)
        else:
            with_creds.append(name)
    return with_home, with_creds


def cmd_notify(message: str, subject: str | None, to: str | None) -> int:
    """Push a reminder via the hermes messaging channel.

    Target resolution order: --to / HERMES_NOTIFY_TO → channel directory
    (`hermes send --list --json`) → ~/.hermes/config.yaml platforms (home
    channel first, then credentials-only). Exits 1 when the push is
    unavailable or failed so the caller falls back to a conversation reminder.
    """
    hermes = shutil.which("hermes")
    if not hermes:
        emit("error", "hermes CLI not found — falling back to conversation reminder",
             {"pushed": False})
        return 1
    target = to or os.environ.get("HERMES_NOTIFY_TO", "")
    if not target:
        platforms = _hermes_targets()
        if platforms:
            target = next(iter(platforms))
    if not target:
        with_home, with_creds = _config_platforms()
        pick = with_home + with_creds
        if pick:
            target = pick[0]
    if not target:
        emit("error", "no hermes messaging platform configured (channel "
                      "directory empty and ~/.hermes/config.yaml has no "
                      "platform with credentials) — falling back to "
                      "conversation reminder", {"pushed": False})
        return 1
    cmd = [hermes, "send", "--to", target, "--json"]
    if subject:
        cmd += ["--subject", subject]
    cmd.append(message)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.SubprocessError as e:
        emit("error", f"hermes send failed: {e} — falling back to conversation reminder",
             {"pushed": False})
        return 1
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:300]
        hint = ""
        if "home channel" in detail.lower():
            hint = (f" (set it with: hermes config set {target.upper()}_HOME_CHANNEL "
                    "<chat_id>)")
        emit("error", f"hermes push to {target} failed ({result.returncode}): {detail}"
                      f"{hint} — falling back to conversation reminder",
             {"pushed": False})
        return 1
    emit("ok", f"reminder pushed via hermes channel ({target})",
         {"pushed": True, "target": target})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure (status/start/stop/notify) the hermes-desktop VNC + "
                    "virtual display + Chromium stack (supervisord-managed) "
                    "for human-machine collaboration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report whether the desktop services are running")
    p_start = sub.add_parser("start", help="start missing services (idempotent)")
    p_start.add_argument("--url", default=None,
                         help="open this URL in a new tab of the shared Chromium")
    sub.add_parser("stop", help="close the whole stack")
    p_notify = sub.add_parser("notify", help="push a reminder via the hermes "
                                             "messaging channel (fallback: chat)")
    p_notify.add_argument("message", help="reminder text, e.g. the blocked URL")
    p_notify.add_argument("--subject", default=None, help="header line (default: 需人工协作)")
    p_notify.add_argument("--to", default=None,
                          help="hermes target (platform or platform:chat_id); "
                               "default: HERMES_NOTIFY_TO or first configured platform")
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
    if args.command == "notify":
        return cmd_notify(args.message, args.subject, args.to)
    return cmd_stop()


if __name__ == "__main__":
    sys.exit(main())
