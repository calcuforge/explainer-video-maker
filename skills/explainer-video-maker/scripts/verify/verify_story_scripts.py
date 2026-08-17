#!/usr/bin/env python3
"""
Validate total narration script length — Step 5 gate.

Every story in video_struct.yaml must have a narration script file at
    {video_dir}/stories/{story_id}/script.md
The COMBINED character count (trimmed) across ALL chapter scripts must reach
content.min_story_chars × <number of chapters> (default 500 per chapter).
There is no per-chapter minimum.

Also validates the content summaries in video_config.yaml (written in Step 5
after all scripts):
    summary:            overall video synopsis, non-empty
    chapter_summaries:  one non-empty synopsis per story_id, keyed by story id

Usage:
    python verify_story_scripts.py --video-struct /abs/path/video_struct.yaml \
                                   --project-config /abs/path/project_config.yaml

Exit codes: 0 = valid, 1 = errors found, 2 = warnings only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from lib.yamlutil import load_yaml

SCRIPT_FILENAME = "script.md"
VIDEO_CONFIG_FILENAME = "video_config.yaml"
DEFAULT_MIN_CHARS = 500
MIN_SUMMARY_CHARS = 10


def validate(struct: dict, min_chars: int, video_dir: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors = []
    warnings = []

    stories = struct.get("stories", [])
    if not stories:
        errors.append("[stories] list is empty or missing")
        return errors, warnings

    total_chars = 0
    for si, story in enumerate(stories):
        story_id = story.get("id", "")
        prefix = f"stories[{si}] ({story_id or '?'})"

        if not story_id:
            errors.append(f"{prefix}: 'id' is required, cannot locate script file")
            continue

        script_path = video_dir / "stories" / story_id / SCRIPT_FILENAME
        if not script_path.exists():
            errors.append(f"{prefix}: script file not found: {script_path}")
            continue

        total_chars += len(script_path.read_text(encoding="utf-8").strip())

    # Total length across ALL chapters: no per-chapter minimum.
    expected = min_chars * len(stories)
    if total_chars < expected:
        errors.append(
            f"Total narration is {total_chars} chars across {len(stories)} chapter(s), "
            f"below the {expected} minimum "
            f"(content.min_story_chars={min_chars} × {len(stories)} chapters)"
        )

    # Content summaries in video_config.yaml (overall + per chapter).
    config_path = video_dir / VIDEO_CONFIG_FILENAME
    if not config_path.exists():
        errors.append(f"video_config.yaml not found (required for summaries): {config_path}")
        return errors, warnings

    config = load_yaml(config_path)
    summary = config.get("summary", "")
    if not str(summary).strip():
        errors.append("video_config.yaml: 'summary' (视频内容梗概) is missing or empty")
    elif len(str(summary).strip()) < MIN_SUMMARY_CHARS:
        errors.append(
            f"video_config.yaml: 'summary' is too short ({len(str(summary).strip())} chars), "
            f"must be a substantive synopsis (≥ {MIN_SUMMARY_CHARS} chars)"
        )

    chapter_summaries = config.get("chapter_summaries")
    if not isinstance(chapter_summaries, dict) or not chapter_summaries:
        errors.append("video_config.yaml: 'chapter_summaries' (分章节内容梗概) is missing or empty")
    else:
        for story in stories:
            story_id = story.get("id", "")
            if story_id not in chapter_summaries:
                errors.append(
                    f"video_config.yaml: 'chapter_summaries' is missing story '{story_id}'"
                )
                continue
            text = str(chapter_summaries[story_id]).strip()
            if not text:
                errors.append(
                    f"video_config.yaml: 'chapter_summaries.{story_id}' is empty"
                )
            elif len(text) < MIN_SUMMARY_CHARS:
                errors.append(
                    f"video_config.yaml: 'chapter_summaries.{story_id}' is too short "
                    f"({len(text)} chars), must be a substantive synopsis (≥ {MIN_SUMMARY_CHARS} chars)"
                )

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate per-chapter narration scripts")
    parser.add_argument("--video-struct", required=True, help="Path to video_struct.yaml (absolute)")
    parser.add_argument("--project-config", required=True, help="Path to project_config.yaml (absolute)")
    args = parser.parse_args()

    from lib.net import require_abs
    require_abs(args.video_struct, args.project_config)

    struct = load_yaml(args.video_struct)
    project_config = load_yaml(args.project_config)
    min_chars = project_config.get("content", {}).get("min_story_chars", DEFAULT_MIN_CHARS)

    video_dir = Path(args.video_struct).parent
    errors, warnings = validate(struct, min_chars, video_dir)

    story_count = len(struct.get("stories", []))
    expected_total = min_chars * story_count

    if errors:
        print(json.dumps({
            "status": "error",
            "msg": f"chapter scripts have {len(errors)} error(s)",
            "data": {"errors": errors, "warnings": warnings, "min_story_chars": min_chars},
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    elif warnings:
        print(json.dumps({
            "status": "warning",
            "msg": f"chapter scripts are valid with {len(warnings)} warning(s)",
            "data": {"warnings": warnings, "min_story_chars": min_chars},
        }, ensure_ascii=False, indent=2))
        sys.exit(2)
    else:
        print(json.dumps({
            "status": "ok",
            "msg": f"All chapter scripts meet the total {expected_total}-character minimum",
            "data": {"stories": story_count, "min_story_chars": min_chars, "expected_total": expected_total},
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
