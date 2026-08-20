#!/usr/bin/env python3
"""
Initialize a new project directory and project_config.yaml from the template
scripts/project_config_tpl.yaml.

All default field values live in the template file — nothing is hardcoded here.
The script loads the template, creates the project directory, fills
project.project_root_path (the only field it sets — it is tied to the created
directory's absolute path), and writes project_config.yaml. The agent then edits
the created file DIRECTLY to supply request-dependent fields (project.name,
language, video_style, target_audience, dependence_paths, ...).

The project directory is created under --projects-dir, named --project-dir-name
(the categorized name: content_structure_params, e.g.
air_crash_documentary_1080p_horizontal). If that name already exists, a numeric
suffix is appended (air_crash_documentary_1080p_horizontal,
air_crash_documentary_1080p_horizontal2, ...).

Note: the generated config is NOT validated here, because the template
intentionally leaves some required fields (e.g. dependence_paths.remotion_template)
empty for the agent to fill. Run verify_project_config.py after editing.

Usage:
    python init_project.py --projects-dir /abs/path/projects \
                           --project-dir-name documentary

Output (JSON envelope): data.project_dir and data.project_config give the
created project directory and project_config.yaml locations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from lib.yamlutil import load_yaml, save_yaml

TEMPLATE_PATH = SKILL_ROOT / "project_config_tpl.yaml"


def resolve_project_dir(projects_dir: Path, name: str) -> tuple[Path, str]:
    """Return (project_dir, final_name), appending a numeric suffix if needed."""
    candidate = projects_dir / name
    if not candidate.exists():
        return candidate, name
    n = 2
    while True:
        suffixed = f"{name}{n}"
        candidate = projects_dir / suffixed
        if not candidate.exists():
            return candidate, suffixed
        n += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a new project from project_config_tpl.yaml")
    parser.add_argument("--projects-dir", required=True, help="Workspace projects/ directory (absolute)")
    parser.add_argument("--project-dir-name", required=True, help="Project directory name (categorized: content_structure_params, e.g. air_crash_documentary_1080p_horizontal)")
    args = parser.parse_args()

    from lib.net import require_abs
    require_abs(args.projects_dir)

    if not TEMPLATE_PATH.exists():
        print(json.dumps({
            "status": "error",
            "msg": f"Template not found: {TEMPLATE_PATH}",
            "data": {},
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    config = load_yaml(TEMPLATE_PATH)

    projects_dir = Path(args.projects_dir)
    projects_dir.mkdir(parents=True, exist_ok=True)
    project_dir, final_name = resolve_project_dir(projects_dir, args.project_dir_name)
    project_dir.mkdir(parents=True, exist_ok=False)

    # Pre-create the ad_video directory (kept empty) — Step 14 scans it for ad
    # short videos; the user drops ad files here before rendering.
    (project_dir / "ad_video").mkdir(exist_ok=False)

    # The only fields the script sets: the created directory's absolute path,
    # and the two component-dependency paths (defaulted to the workspace's dep/
    # dir — see below). All other fields (incl. project.name) are left as-is.
    config.setdefault("project", {})["project_root_path"] = str(project_dir)

    # Default dependence_paths to the workspace's dep/ directory (the workspace
    # is the directory that contains projects/). These are stored as
    # workspace-relative paths so the config stays portable across environments;
    # the scripts resolve a relative path against the workspace at runtime. The
    # two component repos are cloned there. The agent overrides these only if the
    # dependencies live somewhere else.
    deps = config.setdefault("dependence_paths", {})
    if not deps.get("remotion_template"):
        deps["remotion_template"] = "dep/remotion-video-template"
    if not deps.get("comfyui_scheduler"):
        deps["comfyui_scheduler"] = "dep/comfyui-scheduler"

    config_path = project_dir / "project_config.yaml"
    save_yaml(config, config_path)

    # Fields left empty in the template for the agent to fill
    project = config["project"]
    deps = config.get("dependence_paths", {})
    supplement = []
    for field in ("language", "video_style", "target_audience"):
        if not project.get(field):
            supplement.append(f"project.{field}")
    for field in ("remotion_template", "comfyui_scheduler"):
        if not deps.get(field):
            supplement.append(f"dependence_paths.{field}")
    # bgm.prompt is left empty at init — the agent fills it before Step 11
    if not config.get("bgm", {}).get("prompt"):
        supplement.append("bgm.prompt")
    # tts.voice_instruct is left empty at init — the agent fills it before Step 7
    if not config.get("tts", {}).get("voice_instruct"):
        supplement.append("tts.voice_instruct")

    print(json.dumps({
        "status": "ok",
        "msg": f"Initialized project directory '{final_name}'",
        "data": {
            "project_dir": str(project_dir.resolve()),
            "project_config": str(config_path.resolve()),
            "project_dir_name": final_name,
            "agent_supplement": supplement,
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
