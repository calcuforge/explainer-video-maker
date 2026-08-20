#!/usr/bin/env python3
"""
Insert ad short videos at a chapter boundary of the finished video — Step 14.

Reads project_config.yaml -> ad_video:
    enabled: true            # default true; false disables the whole step
    insert_position: middle  # beginning | middle (default) | end
    directories: []          # extra ad dirs (relative to project root or absolute),
                             #   multiple allowed; default empty = scan only
                             #   {project_root}/ad_video
    insert_after_story: ""   # agent decision for middle: story_id whose END is
                             #   the insertion point (e.g. story3)

All videos found under the ad dirs are inserted at the insertion point in
filename order: part1 + ad1 + ad2 + ... + part2.

Implementation (ffmpeg):
  1. compute the insertion time T from remotion_sections.yaml scene frame sums
  2. split the finished video at T into tmp/part1.mp4 + tmp/part2.mp4 (re-encode,
     frame-accurate)
  3. normalize each ad to the main video's resolution/fps/codec (silent audio
     track added if the ad has none)
  4. merge part1 + ads + part2 with the concat demuxer (stream copy) into
     {video_dir}/final.mp4 (faststart)

Usage:
    python insert_ad_videos.py --project-config /abs/project_config.yaml \
                               --remotion-sections /abs/remotion_sections.yaml \
                               --video /abs/result.mp4 \
                               [--insert-after-story story3] \
                               [--keep-parts]

Exit codes: 0 = ok (ads inserted, or skipped: disabled / no ad videos found),
            1 = error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from lib.net import require_abs
from lib.yamlutil import load_yaml

AD_DIR_DEFAULT = "ad_video"
AD_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv"}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path: str) -> dict:
    """Return {width, height, fps, duration} of the first video stream + format duration."""
    out = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
        "-of", "json", path,
    ])
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    stream = (data.get("streams") or [{}])[0]
    fps = 24.0
    if stream.get("avg_frame_rate"):
        num, _, den = stream["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den) if float(den) else 24.0
        except ValueError:
            fps = 24.0
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": fps,
        "duration": float(data.get("format", {}).get("duration") or 0.0),
    }


def has_audio(path: str) -> bool:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "json", path])
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {out.stderr.strip()}")
    return bool(json.loads(out.stdout).get("streams"))


def find_ad_videos(project_root: Path, extra_dirs: list[str]) -> list[Path]:
    dirs: list[Path] = [project_root / AD_DIR_DEFAULT]
    for d in extra_dirs:
        p = Path(d)
        dirs.append(p if p.is_absolute() else project_root / p)

    found: list[Path] = []
    seen: set[Path] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in AD_EXTENSIONS and f.resolve() not in seen:
                seen.add(f.resolve())
                found.append(f)
    return found


def compute_cut_time(remotion_sections: dict, position: str, insert_after_story: str | None) -> tuple[float, str]:
    """Return (cut time in seconds, human-readable point description)."""
    fps = float(remotion_sections.get("fps", 24.0))
    stories = remotion_sections.get("stories", [])

    story_frames: list[tuple[str, int]] = []
    for story in stories:
        frames = 0
        for section in story.get("section_list", []):
            for scene in section.get("scene_list", []):
                frames += int(scene.get("total_frame", 0))
        story_frames.append((story.get("story_id", ""), frames))
    total_frames = sum(f for _, f in story_frames)

    if position == "beginning":
        return 0.0, "beginning (before story 1)"
    if position == "end":
        return total_frames / fps, "end (after all chapters)"

    # middle — the agent decides the exact chapter boundary
    if not insert_after_story:
        raise RuntimeError(
            "insert_position=middle requires the agent to pick the chapter boundary: "
            "set ad_video.insert_after_story in project_config.yaml (e.g. story3) "
            "or pass --insert-after-story. Valid story ids: "
            + ", ".join(sid for sid, _ in story_frames if sid)
        )
    cut_frames = 0
    for sid, frames in story_frames:
        cut_frames += frames
        if sid == insert_after_story:
            return cut_frames / fps, f"after story '{insert_after_story}'"
    raise RuntimeError(
        f"insert_after_story '{insert_after_story}' not found in remotion_sections.yaml. "
        f"Valid story ids: {', '.join(sid for sid, _ in story_frames if sid)}"
    )


def encode_segment(src: str, dst: str, w: int, h: int, fps: float, crf: int, start: float | None, duration: float | None) -> None:
    """Re-encode a segment (split part or ad) to the main video's spec. Frame-accurate when -ss is on the input."""
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.4f}"]
    cmd += ["-i", src]
    if duration is not None:
        cmd += ["-t", f"{duration:.4f}"]
    cmd += [
        "-vf", f"scale={w}:{h},setsar=1",
        "-r", f"{fps:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        dst,
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr[-2000:]}")


def normalize_ad(src: str, dst: str, w: int, h: int, fps: float, crf: int) -> None:
    """Normalize an ad to the main video spec; add a silent track if it has no audio."""
    if has_audio(src):
        encode_segment(src, dst, w, h, fps, crf, None, None)
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", src,
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-shortest",
            "-vf", f"scale={w}:{h},setsar=1",
            "-r", f"{fps:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            dst,
        ]
        proc = _run(cmd)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr[-2000:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert ad short videos at a chapter boundary (Step 14)")
    parser.add_argument("--project-config", required=True, help="Path to project_config.yaml (absolute)")
    parser.add_argument("--remotion-sections", required=True, help="Path to remotion_sections.yaml (absolute)")
    parser.add_argument("--video", default="", help="Path to the finished video (default: {video_dir}/result.mp4)")
    parser.add_argument("--insert-after-story", default="", help="Override ad_video.insert_after_story (story id)")
    parser.add_argument("--keep-parts", action="store_true", help="Keep split/normalized temp files in tmp/")
    args = parser.parse_args()

    require_abs(args.project_config, args.remotion_sections)

    project_config = load_yaml(args.project_config)
    remotion_sections = load_yaml(args.remotion_sections)
    video_dir = Path(args.remotion_sections).parent
    video = Path(args.video) if args.video else video_dir / "result.mp4"
    if not video.exists():
        print(json.dumps({"status": "error", "msg": f"video not found: {video}"}, ensure_ascii=False))
        sys.exit(1)

    ad = project_config.get("ad_video", {})
    if not ad.get("enabled", True):
        print(json.dumps({"status": "ok", "msg": "ad insertion skipped (ad_video.enabled: false)",
                          "data": {"inserted": False}}, ensure_ascii=False))
        return

    project_root = Path(project_config.get("project", {}).get("project_root_path", video_dir.parent.parent))
    ad_videos = find_ad_videos(project_root, [str(d) for d in ad.get("directories", []) or []])
    if not ad_videos:
        print(json.dumps({"status": "ok",
                          "msg": "ad insertion skipped (no ad videos found — check {project_root}/ad_video or ad_video.directories)",
                          "data": {"inserted": False}}, ensure_ascii=False))
        return

    position = ad.get("insert_position", "middle")
    if position not in ("beginning", "middle", "end"):
        print(json.dumps({"status": "error", "msg": f"ad_video.insert_position must be beginning|middle|end, got '{position}'"},
                         ensure_ascii=False))
        sys.exit(1)
    insert_after_story = args.insert_after_story or str(ad.get("insert_after_story", "") or "")

    try:
        cut_sec, point_desc = compute_cut_time(remotion_sections, position, insert_after_story)
    except RuntimeError as e:
        print(json.dumps({"status": "error", "msg": str(e)}, ensure_ascii=False))
        sys.exit(1)

    main_info = probe(str(video))
    w, h = main_info["width"], main_info["height"]
    if not w or not h:
        print(json.dumps({"status": "error", "msg": f"no video stream found in {video}"}, ensure_ascii=False))
        sys.exit(1)
    duration = main_info["duration"]
    if cut_sec < 0.01:
        cut_sec = 0.0
    if cut_sec >= duration - 0.01:
        cut_sec = duration
    if cut_sec > duration - 0.5:
        print(f"WARN: cut time {cut_sec:.2f}s is near the video end ({duration:.2f}s) — ad effectively appended", file=sys.stderr)

    fps = main_info["fps"]
    crf = int(remotion_sections.get("crf", 23))
    tmp = video_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    made: list[Path] = []
    try:
        # 1) split the finished video at the insertion point into two parts
        if cut_sec > 0.01:
            part1 = tmp / "ad_part1.mp4"
            encode_segment(str(video), str(part1), w, h, fps, crf, start=0.0, duration=cut_sec)
            made.append(part1)
        if cut_sec < duration - 0.01:
            part2 = tmp / "ad_part2.mp4"
            encode_segment(str(video), str(part2), w, h, fps, crf, start=cut_sec, duration=None)
            made.append(part2)

        # 2) normalize ads to the main video spec, in filename order;
        #    ads sit between part1 and part2
        ad_segments: list[Path] = []
        for i, ad_video_file in enumerate(ad_videos, 1):
            norm = tmp / f"ad_norm{i}.mp4"
            normalize_ad(str(ad_video_file), str(norm), w, h, fps, crf)
            ad_segments.append(norm)
            made.append(norm)

        order: list[Path] = []
        if cut_sec > 0.01:
            order.append(tmp / "ad_part1.mp4")
        order += ad_segments
        if cut_sec < duration - 0.01:
            order.append(tmp / "ad_part2.mp4")

        # 3) merge part1 + ads + part2 (concat demuxer, stream copy)
        concat_list = tmp / "ad_concat_list.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in order:
                f.write(f"file '{str(p).replace(chr(39), chr(39) * 2)}'\n")

        final = video_dir / "final.mp4"
        proc = _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", "-movflags", "+faststart", str(final),
        ])
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed:\n{proc.stderr[-2000:]}")

        total_sec = sum(probe(str(p))["duration"] for p in order)
        print(json.dumps({
            "status": "ok",
            "msg": f"inserted {len(ad_videos)} ad video(s) {point_desc} into {final.name}",
            "data": {
                "inserted": True,
                "insert_position": position,
                "insert_point": point_desc,
                "ad_videos": [str(p) for p in ad_videos],
                "final_video": str(final),
                "final_duration": round(total_sec, 2),
            },
        }, ensure_ascii=False, indent=2))
    finally:
        if not args.keep_parts:
            for p in made:
                p.unlink(missing_ok=True)
            (tmp / "ad_concat_list.txt").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
