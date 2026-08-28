#!/usr/bin/env python3
"""
TTS synthesis + frame count calculation.

Reads video_struct.yaml, generates speech audio for each narration (one per
section) using the configured TTS backend (comfyui_indextts or http_server),
then uses ffprobe to measure audio duration and calculates total_frame for each
narration.

Each synthesized narration is time-stretched to the target speech rate from
tts.speed: 1.0 = 6 CJK chars/s (zh) or 2.5 words/s (en).

Updates video_struct.yaml narration.audio_path and narration.total_frame fields.

Usage:
    python run_tts.py --project-config /abs/path/project_config.yaml --video-struct /abs/path/video_struct.yaml

The project_config.yaml tts.backend field selects the backend:
    - comfyui_indextts: uses comfyui-scheduler run -w index_tts_2
    - http_server: POST multipart to tts.http.url
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from lib.scene_frames import strip_trailing_punct
from lib.yamlutil import load_yaml, save_yaml


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", audio_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to parse ffprobe output for {audio_path}: {e}")


def duration_to_frames(duration_sec: float, fps: int) -> int:
    """Convert duration in seconds to frame count."""
    return math.ceil(duration_sec * fps)


def normalize_loudness(path: str, target_lufs: float = -14.0) -> bool:
    """Normalize a narration WAV to a target loudness (single-pass loudnorm).

    Re-encodes in place (temp file + atomic replace) so the narration is
    consistently audible. Returns False on failure, leaving the original intact.
    """
    src = Path(path)
    if not src.exists() or src.stat().st_size == 0:
        return False
    tmp = str(src) + ".loudnorm.tmp.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
             "-c:a", "pcm_s16le", tmp],
            capture_output=True, text=True, timeout=120, check=True,
        )
        Path(tmp).replace(src)
        return True
    except (subprocess.SubprocessError, OSError):
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass
        return False


# Speech-rate standard: tts.speed multiplies the base narration rate —
# speed=1.0 → 6 CJK characters/second (zh-CN) or ~2.5 words/second (en-US,
# ≈150 wpm). After synthesis each narration is time-stretched to land exactly
# on the target rate (mirrors the atempo post-processing in qwen_tts.go).
RATE_ZH = 6.0   # CJK characters per second at speed=1.0
RATE_EN = 2.5   # English words per second at speed=1.0
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")


def count_speech_units(text: str, language: str) -> int:
    """Spoken-unit count: CJK characters for zh, words for en. Punctuation and
    other scripts (e.g. digits in an English narration) are not counted."""
    if language == "en-US":
        return len(_WORD_RE.findall(text))
    return len(_CJK_RE.findall(text))


def target_duration_for_speed(text: str, speed: float, language: str) -> float:
    """Target narration duration (seconds) for the speech-rate standard: spoken
    units divided by speed × base rate. Returns 0 if the text has no units."""
    units = count_speech_units(text, language)
    if units == 0:
        return 0.0
    rate = RATE_EN if language == "en-US" else RATE_ZH
    return units / (rate * speed)


def build_atempo_chain(factor: float) -> list[str]:
    """atempo filter chain for a speed factor (>1 = faster). atempo accepts
    only 0.5–2.0 per stage, so out-of-range factors chain multiple stages."""
    if factor <= 0:
        return ["atempo=1.0"]
    if 0.5 <= factor <= 2.0:
        return [f"atempo={factor:.4f}"]
    chain: list[str] = []
    remaining = factor
    while remaining > 2.0:
        chain.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        chain.append("atempo=0.5")
        remaining /= 0.5
    if 0.5 <= remaining <= 2.0:
        chain.append(f"atempo={remaining:.4f}")
    return chain


def adjust_speech_rate(path: str, factor: float) -> bool:
    """Time-stretch a narration to the target speech rate (factor >1 = faster).
    Re-encodes in place (temp file + atomic replace), like normalize_loudness.
    Returns False on failure, leaving the original intact."""
    if abs(factor - 1.0) < 0.02:
        return True
    src = Path(path)
    if not src.exists() or src.stat().st_size == 0:
        return False
    tmp = str(src) + ".speed.tmp.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-af", ",".join(build_atempo_chain(factor)),
             "-c:a", "pcm_s16le", tmp],
            capture_output=True, text=True, timeout=120, check=True,
        )
        Path(tmp).replace(src)
        return True
    except (subprocess.SubprocessError, OSError):
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass
        return False


def synth_comfyui_indextts(
    content: str,
    voice_file: str,
    output_path: str,
    speed: float = 1.0,
    timeout: int = 3600,
) -> str:
    """Generate speech using comfyui-scheduler index_tts_2 workflow.

    Returns the output audio file path.
    """
    inputs = json.dumps({
        "content": content,
        "voice_file": voice_file,
    }, ensure_ascii=False)

    cmd = ["comfyui-scheduler", "run", "-w", "index_tts_2", "-i", inputs]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"TTS timed out after {timeout}s for: {content[:50]}...")
    except FileNotFoundError:
        raise RuntimeError("comfyui-scheduler not found on PATH")

    if result.returncode != 0:
        raise RuntimeError(f"comfyui-scheduler failed: {result.stderr or result.stdout}")

    # Parse output JSON
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Invalid JSON from comfyui-scheduler: {result.stdout[:200]}")

    if output.get("status") != "ok":
        raise RuntimeError(f"TTS error: {output.get('msg', 'unknown')}")

    files = output.get("data", {}).get("files", [])
    if not files:
        raise RuntimeError("No output files from TTS")

    # Download the output file (supports http:// and file:// URLs)
    file_url = files[0].get("url", "")
    if not file_url:
        raise RuntimeError("No URL in TTS output file")

    from lib.net import download_file
    download_file(file_url, output_path, timeout=60)

    return output_path


def synth_http_server(
    content: str,
    voice_file: str,
    output_path: str,
    url: str,
    speed: float = 1.0,
    headers: dict | None = None,
) -> str:
    """Generate speech using HTTP multipart TTS server.

    Protocol: POST multipart/form-data
        Fields: input (text), speed (float str), voice_file (file upload)
        Response: raw audio bytes
    """
    import requests

    # Expand environment variables in URL
    resolved_url = os.path.expandvars(url)

    with open(voice_file, "rb") as vf:
        files = {"voice_file": (os.path.basename(voice_file), vf, "audio/wav")}
        data = {
            "input": content,
            "speed": str(speed),
        }
        req_headers = headers or {}
        resp = requests.post(resolved_url, data=data, files=files, headers=req_headers, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP TTS server error ({resp.status_code}): {resp.text[:200]}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(resp.content)

    return output_path


def collect_narration_units(video_struct: dict) -> list[dict]:
    """Collect all narrations with their context from video_struct.

    One narration per section (section.narration); each narration maps to 1-N
    scenes. The narration dict reference is kept for in-place updates of
    audio_path / total_frame.
    """
    units = []
    for story in video_struct.get("stories", []):
        story_id = story.get("id", "")
        for section in story.get("section_list", []):
            narration = section.get("narration") or {}
            units.append({
                "story_id": story_id,
                "narration_id": narration.get("id", ""),
                "content": narration.get("content", ""),
                "audio_path": narration.get("audio_path", ""),
                "narration_ref": narration,  # reference for in-place update
            })
    return units


# Phonetically balanced reference sentences with heavy fricative/plosive
# coverage (s/sh/f/l/j/q/x/z/c/b/p/d...). The voice-clone model extracts
# articulation features (esp. s/f/l fricatives) from the reference — a
# consonant-poor sample gives it nothing to learn.
_REFERENCE_CONTENT_ZH = (
    "春风拂面，柳枝轻摆。十四岁的少年背着新书包，沿着山路数着石阶，"
    "一步一步爬上山顶，山下的城市景色尽收眼底。"
)
_REFERENCE_CONTENT_EN = (
    "Fresh spring air flows over the forest hills. She sells sixty fresh "
    "strawberries, skipping softly along the silvery stream, smiling at the "
    "sunshine."
)


def _mean_volume_db(path: str, filter_str: str | None = None) -> float | None:
    """Mean volume in dB of an audio file (optionally after an ffmpeg filter)."""
    af = f"{filter_str},volumedetect" if filter_str else "volumedetect"
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", af, "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    m = re.search(r"mean_volume:\s*([-\d.]+) dB", result.stderr)
    return float(m.group(1)) if m else None


def _postprocess_voice_ref(raw_path: str, output_path: str, eq_gain_db: float) -> dict:
    """Normalize the voice-design output to a clean 24 kHz mono WAV and lift the
    suppressed high-frequency band so s/f/l fricatives stay audible.

    The qwen3 voice-design output is heavily band-limited: energy above 2 kHz
    sits 19-28 dB below the low band (sounds "like a voice behind a thick
    cloth"), so the clone model cannot extract fricative features and the
    synthesis has to fabricate high-frequency content. A high-shelf boost
    restores that band. Returns diagnostics for the caller's report.
    """
    filters = []
    if eq_gain_db > 0:
        filters.append(f"highshelf=f=2000:g={eq_gain_db:.1f}")
    filters.append("alimiter=limit=0.95")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_path),
           "-ar", "24000", "-ac", "1", "-sample_fmt", "s16",
           "-af", ",".join(filters), str(output_path)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)

    diag: dict = {}
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(output_path)],
        capture_output=True, text=True, timeout=30,
    )
    if probe.returncode == 0:
        info = json.loads(probe.stdout)
        diag["duration"] = round(float(info["format"]["duration"]), 2)
        streams = info.get("streams") or []
        if streams:
            diag["sample_rate"] = int(streams[0].get("sample_rate", 0))

    full_b, hp_b = _mean_volume_db(raw_path), _mean_volume_db(raw_path, "highpass=f=6000")
    full_a, hp_a = _mean_volume_db(output_path), _mean_volume_db(output_path, "highpass=f=6000")
    if None not in (full_b, hp_b, full_a, hp_a):
        diag["hf_delta_before"] = round(hp_b - full_b, 1)
        diag["hf_delta_after"] = round(hp_a - full_a, 1)

    return diag


def _run_voice_design(voice_instruct: str, output_path: str, timeout: int = 3600,
                      language: str | None = None, eq_gain_db: float = 12.0,
                      content_override: str = "") -> str:
    """Generate a reference voice via the qwen3_tts_voice_design workflow.

    The raw download is post-processed (_postprocess_voice_ref) into a clean
    24 kHz mono WAV with a high-frequency clarity boost. Returns the output
    audio file path.
    """
    lang = language or "zh-CN"
    # Qwen3VoiceDesign's `language` widget takes Chinese/English enum values,
    # not project language codes (zh-CN/en-US) — map before sending.
    node_language = {"zh-CN": "Chinese", "en-US": "English"}.get(lang, "Auto")
    if content_override:
        content = content_override
    elif lang == "zh-CN":
        content = _REFERENCE_CONTENT_ZH
    else:
        content = _REFERENCE_CONTENT_EN

    inputs = json.dumps({
        "voice_instruct": voice_instruct,
        "content": content,
        "language": node_language,
    }, ensure_ascii=False)

    cmd = ["comfyui-scheduler", "run", "-w", "qwen3_tts_voice_design", "-i", inputs]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Voice design timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError("comfyui-scheduler not found on PATH")

    if result.returncode != 0:
        raise RuntimeError(f"Voice design failed: {result.stderr or result.stdout[:300]}")

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Invalid JSON from voice design: {result.stdout[:200]}")

    if output.get("status") != "ok":
        raise RuntimeError(f"Voice design error: {output.get('msg', 'unknown')}")

    files = output.get("data", {}).get("files", [])
    if not files:
        raise RuntimeError("No output files from voice design")

    file_url = files[0].get("url", "")
    if not file_url:
        raise RuntimeError("No URL in voice design output")

    from lib.net import download_file
    raw_path = str(output_path) + ".raw"
    download_file(file_url, raw_path)

    try:
        diag = _postprocess_voice_ref(raw_path, output_path, eq_gain_db)
    finally:
        Path(raw_path).unlink(missing_ok=True)

    if "hf_delta_before" in diag:
        print(
            f"Voice reference ready: {diag.get('sample_rate', '?')}Hz, "
            f"{diag.get('duration', '?')}s, HF(>6kHz) band delta "
            f"{diag['hf_delta_before']}dB -> {diag['hf_delta_after']}dB "
            f"(high-shelf {eq_gain_db}dB)",
            file=sys.stderr,
        )

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TTS synthesis and calculate frames")
    parser.add_argument("--project-config", required=True, help="Path to project_config.yaml (absolute)")
    parser.add_argument("--video-struct", required=True, help="Path to video_struct.yaml (absolute)")
    parser.add_argument("--workers", type=int, default=5, help="Concurrent TTS workers")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-TTS subprocess timeout in seconds (default 1h)")
    parser.add_argument("--force", action="store_true", help="Re-generate even if audio exists")
    args = parser.parse_args()

    from lib.net import require_abs
    require_abs(args.project_config, args.video_struct)

    # Load configs
    project_config = load_yaml(args.project_config)
    video_struct = load_yaml(args.video_struct)

    tts_timeout = args.timeout
    tts_config = project_config.get("tts", {})
    backend = tts_config.get("backend", "comfyui_indextts")
    speed = tts_config.get("speed", 1.0)
    # Silence after each narration's audio, added to narration.total_frame so the
    # next narration starts pause_seconds later while the visual stays continuous.
    pause_seconds = float(tts_config.get("pause_seconds", 0.5))
    # Normalize each narration's loudness so the narration is clearly audible.
    loudnorm_enabled = tts_config.get("loudnorm", True)
    loudness_target = float(tts_config.get("loudness_target", -14.0))  # LUFS, negative
    # High-frequency clarity boost (dB) for the auto-generated reference voice.
    # The qwen3 voice-design output is band-limited above ~2 kHz (muffled, no
    # audible fricatives); the shelf lift restores the band the clone model
    # extracts s/f/l from. 0 = disable.
    voice_ref_eq_db = float(tts_config.get("voice_ref_eq_db", 12.0))
    # Optional override for the reference audio's spoken text (default is a
    # fricative-rich phonetically balanced sentence).
    voice_ref_content = tts_config.get("voice_ref_content", "")
    fps = project_config.get("video", {}).get("fps", 24)
    language = project_config.get("project", {}).get("language", "zh-CN")

    # Resolve voice file — auto-generate via voice design if missing
    project_root = project_config.get("project", {}).get("project_root_path", "")
    voice_file = tts_config.get("voice_file", "")
    if not voice_file and project_root:
        candidate = Path(project_root) / "voice_file.wav"
        if candidate.exists():
            voice_file = str(candidate)

    if not voice_file or not Path(voice_file).exists():
        # Run voice design to generate a reference voice
        voice_instruct = tts_config.get("voice_instruct", "")
        lang = language
        if not voice_instruct:
            print(json.dumps({
                "status": "error",
                "msg": "Cannot auto-generate voice: tts.voice_instruct is empty — fill it in "
                       "project_config.yaml (describe the target voice characteristics, e.g. "
                       "'男，中年，中音调'; see comfyui-scheduler/doc/workflow.md)",
                "data": {},
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        voice_output = str(Path(project_root) / "voice_file.wav") if project_root else ""
        if not voice_output:
            print(json.dumps({
                "status": "error",
                "msg": "Cannot auto-generate voice: project.project_root_path is not set",
                "data": {},
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        print(f"Voice file not found. Running voice design (instruct: {voice_instruct})...", file=sys.stderr)
        voice_file = _run_voice_design(
            voice_instruct, voice_output, timeout=tts_timeout, language=lang,
            eq_gain_db=voice_ref_eq_db, content_override=voice_ref_content,
        )

        # Update project_config.yaml with the generated voice file
        tts_config["voice_file"] = voice_file
        save_yaml(project_config, args.project_config)
        print(f"Voice file generated and saved to project_config: {voice_file}", file=sys.stderr)

    # HTTP server config
    http_config = tts_config.get("http", {})
    http_url = http_config.get("url", "")
    # Headers: project_config tts.http.headers → env vars fallback
    http_headers = dict(http_config.get("headers", {}))
    if not http_headers.get("Host-User-ID") and "Host-User-ID" in os.environ:
        http_headers["Host-User-ID"] = os.environ["Host-User-ID"]
    if not http_headers.get("Host-User-Token") and "Host-User-Token" in os.environ:
        http_headers["Host-User-Token"] = os.environ["Host-User-Token"]

    # Speed that determines the target speech rate: http_server has its own
    # server-side speed which takes precedence over tts.speed.
    effective_speed = http_config.get("speed", speed) if backend == "http_server" else speed

    # Collect narration units
    units = collect_narration_units(video_struct)
    if not units:
        print(json.dumps({"status": "error", "msg": "No narration units found in video_struct.yaml", "data": {}}, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Determine output directory: same as video_struct, stories/{story_id}/{narration_id}/
    video_dir = Path(args.video_struct).parent

    # Filter units that need generation
    to_generate = []
    skipped = 0
    for u in units:
        # Output path: video_dir/stories/{story_id}/{narration_id}/speech.wav
        out_dir = video_dir / "stories" / u["story_id"] / u["narration_id"]
        out_path = str(out_dir / "speech.wav")

        # Check both the YAML audio_path and the computed output path
        audio_path = u["audio_path"]
        already_exists = (
            (audio_path and Path(audio_path).exists())
            or Path(out_path).exists()
        )
        if not args.force and already_exists:
            u["output_path"] = out_path if Path(out_path).exists() else audio_path
            skipped += 1
            continue

        u["output_path"] = out_path
        to_generate.append(u)

    # Generate audio
    errors = []
    generated = 0

    def generate_one(unit: dict) -> dict:
        """Generate TTS for a single narration unit."""
        try:
            content = strip_trailing_punct(unit["content"])
            if backend == "comfyui_indextts":
                synth_comfyui_indextts(
                    content=content,
                    voice_file=voice_file,
                    output_path=unit["output_path"],
                    speed=speed,
                    timeout=tts_timeout,
                )
            elif backend == "http_server":
                synth_http_server(
                    content=content,
                    voice_file=voice_file,
                    output_path=unit["output_path"],
                    url=http_url,
                    speed=http_config.get("speed", speed),
                    headers=http_headers,
                )
            else:
                raise RuntimeError(f"Unknown TTS backend: {backend}")
            # Enforce the speech-rate standard: time-stretch the synthesized
            # audio so the narration lands exactly on speed × base rate
            # (speed=1.0 → 6 CJK chars/s for zh, 2.5 words/s for en).
            target_sec = target_duration_for_speed(content, effective_speed, language)
            if target_sec > 0:
                factor = get_audio_duration(unit["output_path"]) / target_sec
                if not adjust_speech_rate(unit["output_path"], factor):
                    print(f"    WARNING: speed adjust failed for {unit['output_path']}", file=sys.stderr)
            return {"unit": unit, "error": None}
        except Exception as e:
            return {"unit": unit, "error": str(e)}

    if to_generate:
        print(f"Generating TTS for {len(to_generate)} narration unit(s) using backend: {backend}"
              f" ({skipped} skipped, already exist)", file=sys.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(generate_one, u): u for u in to_generate}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["error"]:
                    errors.append({"narration_id": result["unit"]["narration_id"], "error": result["error"]})
                else:
                    generated += 1

    # Calculate frames and update video_struct
    updated_count = 0
    for u in units:
        audio_path = u.get("output_path", u["audio_path"])
        if audio_path and Path(audio_path).exists():
            try:
                if loudnorm_enabled and not normalize_loudness(audio_path, loudness_target):
                    print(f"    WARNING: loudnorm failed for {audio_path}", file=sys.stderr)
                duration = get_audio_duration(audio_path)
                total_frame = duration_to_frames(duration + pause_seconds, fps)
                # Update in-place
                u["narration_ref"]["audio_path"] = audio_path
                u["narration_ref"]["total_frame"] = total_frame
                updated_count += 1
            except Exception as e:
                errors.append({"narration_id": u["narration_id"], "error": f"ffprobe: {e}"})

    # Save updated video_struct
    save_yaml(video_struct, args.video_struct)

    # Report
    if errors:
        print(json.dumps({
            "status": "error",
            "msg": f"TTS completed with {len(errors)} error(s)",
            "data": {"generated": generated, "skipped": skipped, "updated": updated_count, "errors": errors},
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    else:
        print(json.dumps({
            "status": "ok",
            "msg": f"TTS complete: {generated} generated, {skipped} skipped, {updated_count} updated with frame counts",
            "data": {"generated": generated, "skipped": skipped, "updated": updated_count, "fps": fps},
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
