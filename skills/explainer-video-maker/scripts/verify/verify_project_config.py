#!/usr/bin/env python3
"""
Validate project_config.yaml structure and field values.

Usage:
    python verify_project_config.py --config /abs/path/project_config.yaml

Exit codes: 0 = valid, 1 = errors found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from lib.yamlutil import load_yaml

VALID_LANGUAGES = ["zh-CN", "en-US"]
VALID_ORIENTATIONS = ["horizontal", "vertical"]
VALID_RESOLUTIONS = ["1080p", "4k"]
VALID_TTS_BACKENDS = ["comfyui_indextts", "http_server"]
VALID_TRANSITION_TYPES = ["fade", "slide", "wipe", "none"]
VALID_DURATIONS = ["short", "medium", "long"]
VALID_CREATION_MODES = ["auto", "manual"]
VALID_CODECS = ["h264", "h265", "hevc", "vp8", "vp9", "av1", "prores"]


def validate(config: dict) -> list[str]:
    """Return a list of error messages (empty = valid)."""
    errors = []

    # --- project section ---
    project = config.get("project")
    if not project:
        errors.append("[project] section is missing")
    else:
        if not project.get("name"):
            errors.append("[project.name] is required")
        if not project.get("project_root_path"):
            errors.append("[project.project_root_path] is required")
        lang = project.get("language", "")
        if lang and lang not in VALID_LANGUAGES:
            errors.append(f"[project.language] invalid value '{lang}'. Valid: {VALID_LANGUAGES}")
        mode = project.get("creation_mode", "")
        if mode and mode not in VALID_CREATION_MODES:
            errors.append(f"[project.creation_mode] invalid value '{mode}'. Valid: {VALID_CREATION_MODES}")

    # --- video section ---
    video = config.get("video")
    if not video:
        errors.append("[video] section is missing")
    else:
        orientation = video.get("orientation", "")
        if orientation and orientation not in VALID_ORIENTATIONS:
            errors.append(f"[video.orientation] invalid '{orientation}'. Valid: {VALID_ORIENTATIONS}")
        resolution = video.get("resolution", "")
        if resolution and resolution.lower() not in VALID_RESOLUTIONS:
            errors.append(f"[video.resolution] invalid '{resolution}'. Valid: {VALID_RESOLUTIONS}")
        fps = video.get("fps")
        if fps is not None:
            if not isinstance(fps, (int, float)) or fps <= 0:
                errors.append(f"[video.fps] must be a positive number, got '{fps}'")

    # --- aigc section ---
    aigc = config.get("aigc", {})
    for field in ["origin_image_width", "origin_image_height", "origin_video_width", "origin_video_height"]:
        val = aigc.get(field)
        if val is not None:
            if not isinstance(val, int) or val <= 0:
                errors.append(f"[aigc.{field}] must be a positive integer, got '{val}'")

    # --- tts section ---
    tts = config.get("tts")
    if not tts:
        errors.append("[tts] section is missing")
    else:
        backend = tts.get("backend", "")
        if backend and backend not in VALID_TTS_BACKENDS:
            errors.append(f"[tts.backend] invalid '{backend}'. Valid: {VALID_TTS_BACKENDS}")
        speed = tts.get("speed")
        if speed is not None:
            if not isinstance(speed, (int, float)) or not (0.25 <= speed <= 4.0):
                errors.append(f"[tts.speed] must be 0.25-4.0, got '{speed}'")
        volume = tts.get("volume")
        if volume is not None:
            if not isinstance(volume, (int, float)) or not (0 <= volume <= 1.0):
                errors.append(f"[tts.volume] must be 0-1.0, got '{volume}'")
        pause_seconds = tts.get("pause_seconds")
        if pause_seconds is not None:
            if isinstance(pause_seconds, bool) or not isinstance(pause_seconds, (int, float)) or pause_seconds < 0:
                errors.append(f"[tts.pause_seconds] must be a non-negative number, got '{pause_seconds}'")
        loudnorm = tts.get("loudnorm")
        if loudnorm is not None and not isinstance(loudnorm, bool):
            errors.append(f"[tts.loudnorm] must be a boolean, got '{loudnorm}'")
        loudness_target = tts.get("loudness_target")
        if loudness_target is not None:
            if isinstance(loudness_target, bool) or not isinstance(loudness_target, (int, float)) \
                    or not (-70 <= loudness_target <= 0):
                errors.append(f"[tts.loudness_target] must be a LUFS target (-70 to 0), got '{loudness_target}'")
        # voice_instruct is left empty at init and filled by the agent before Step 7;
        # run_tts.py errors if it is still empty when the voice file is auto-generated.

        # If http_server backend, check http config
        if backend == "http_server":
            http = tts.get("http", {})
            if not http.get("url"):
                errors.append("[tts.http.url] is required when backend is http_server")

    # --- bgm section ---
    bgm = config.get("bgm", {})
    enabled = bgm.get("enabled", True)
    if enabled is not None and not isinstance(enabled, bool):
        errors.append(f"[bgm.enabled] must be a boolean, got '{enabled}'")
    loop = bgm.get("loop")
    if loop is not None and not isinstance(loop, bool):
        errors.append(f"[bgm.loop] must be a boolean, got '{loop}'")
    length = bgm.get("length")
    if length is not None:
        if not isinstance(length, (int, float)) or length <= 0:
            errors.append(f"[bgm.length] must be a positive number, got '{length}'")
    volume = bgm.get("volume")
    if volume is not None:
        if not isinstance(volume, (int, float)) or not (0 <= volume <= 0.3):
            errors.append(f"[bgm.volume] must be 0-0.3, got '{volume}'")
    # bgm.prompt is intentionally left empty at init and filled by the agent before
    # Step 11; run_bgm.py errors if it is still empty at generation time.

    # --- theme section ---
    theme = config.get("theme", {})
    transition = theme.get("transition_type", "")
    if transition and transition not in VALID_TRANSITION_TYPES:
        errors.append(f"[theme.transition_type] invalid '{transition}'. Valid: {VALID_TRANSITION_TYPES}")
    show_bar = theme.get("show_progress_bar")
    if show_bar is not None and not isinstance(show_bar, bool):
        errors.append(f"[theme.show_progress_bar] must be a boolean, got '{show_bar}'")

    # --- ad_video section (Step 14) ---
    ad = config.get("ad_video", {})
    if not isinstance(ad, dict):
        errors.append("[ad_video] must be a mapping")
    else:
        ad_enabled = ad.get("enabled", True)
        if not isinstance(ad_enabled, bool):
            errors.append(f"[ad_video.enabled] must be a boolean, got '{ad_enabled}'")
        ad_position = ad.get("insert_position", "middle")
        if ad_position not in ("beginning", "middle", "end"):
            errors.append(f"[ad_video.insert_position] must be beginning | middle | end, got '{ad_position}'")
        ad_dirs = ad.get("directories", [])
        if ad_dirs is None:
            ad_dirs = []
        if not isinstance(ad_dirs, list) or not all(isinstance(d, str) and d.strip() for d in ad_dirs):
            errors.append("[ad_video.directories] must be a list of non-empty directory strings")
        ad_after = ad.get("insert_after_story")
        if ad_after is not None and not isinstance(ad_after, str):
            errors.append(f"[ad_video.insert_after_story] must be a story id string, got '{ad_after}'")

    # --- content section ---
    content = config.get("content", {})
    duration = content.get("duration", "")
    if duration and duration not in VALID_DURATIONS:
        errors.append(f"[content.duration] invalid '{duration}'. Valid: {VALID_DURATIONS}")
    min_chars = content.get("min_story_chars")
    if min_chars is not None:
        if not isinstance(min_chars, int) or min_chars <= 0:
            errors.append(f"[content.min_story_chars] must be a positive integer, got '{min_chars}'")

    # --- render section ---
    render_cfg = config.get("render", {})
    mode = render_cfg.get("mode", "local")
    if mode not in ("local", "distributed"):
        errors.append(f"[render.mode] invalid '{mode}'. Valid: local, distributed")
    codec = render_cfg.get("codec", "")
    if codec and codec.lower() not in VALID_CODECS:
        errors.append(f"[render.codec] invalid '{codec}'. Valid: {VALID_CODECS}")
    crf = render_cfg.get("crf")
    if crf is not None:
        if not isinstance(crf, (int, float)) or not (0 <= crf <= 51):
            errors.append(f"[render.crf] must be 0-51, got '{crf}'")
    timeout_ms = render_cfg.get("timeout_ms")
    if timeout_ms is not None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            errors.append(f"[render.timeout_ms] must be a positive integer, got '{timeout_ms}'")

    # --- dependence_paths ---
    deps = config.get("dependence_paths", {})
    if not deps.get("remotion_template"):
        errors.append("[dependence_paths.remotion_template] is required")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate project_config.yaml")
    parser.add_argument("--config", required=True, help="Path to project_config.yaml (absolute)")
    args = parser.parse_args()

    from lib.net import require_abs
    require_abs(args.config)

    config = load_yaml(args.config)
    errors = validate(config)

    if errors:
        print(json.dumps({
            "status": "error",
            "msg": f"project_config.yaml has {len(errors)} error(s)",
            "data": {"errors": errors},
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    else:
        print(json.dumps({
            "status": "ok",
            "msg": "project_config.yaml is valid",
            "data": {},
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
