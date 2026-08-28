---
name: explainer-video-maker
description: >
  Use when the user wants to create an explainer, documentary, knowledge-sharing,
  news-broadcast, product-introduction, or data-report video from a topic.
  Trigger keywords: "make a documentary", "make a video about", "make an explainer",
  "make a news video", "make a product intro", "make a knowledge video",
  "help me make a ... video". Also trigger for Chinese equivalents like
  "帮我制作一个...纪录片/视频", "做一个...解说视频". Supports auto topic selection
  when user only names a category. Produces video via research → struct design →
  TTS → AIGC → Remotion render → MP4. Do NOT trigger for generic video editing,
  trimming, or format conversion.
argument-hint: "[topic or category]"
effort: high
category: Content Creation
version: 1.0.0
created: 2026-07-30
permissions:
  - env
  - file_read
  - file_write
  - network
  - shell
dependencies:
  - remotion-video-template
  - comfyui-scheduler
metadata:
  requires:
    bins: [python3, ffmpeg, ffprobe, node, npx, comfyui-scheduler]
    # python packages: see requirements.txt (install with pip install -r)
---

# Explainer Video Maker

Automated pipeline for **narration-driven explainer videos** from any topic.
Supports documentaries, knowledge sharing, news, data reports, product
introductions, and any format suitable for narrated explanation.

Audio drives visuals: each section carries exactly one narration; its audio
duration sets the narration's total frame count, which is split across the
section's 1-N scenes by each scene's `percentage`.

## Contents

- [Prerequisites](#prerequisites)
- [Project Management](#project-management)
- [Execution Modes](#execution-modes) — Auto (default) vs Manual
- [Workflow (14 Steps)](#workflow)
- [Hard Rules](#hard-rules)
- [References](#references)

---

## Prerequisites

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`.

```bash
SKILL_DIR="${SKILL_DIR:-${CLAUDE_SKILL_DIR}}"
python3 "${SKILL_DIR}/scripts/tool/check_prereqs.py"
```

External dependencies:
- Python >= 3.10; install the Python packages from `${SKILL_DIR}/requirements.txt`
  (`pip install -r "${SKILL_DIR}/requirements.txt"`), then the Playwright
  browser (`playwright install chromium`)
- `ffmpeg`, `ffprobe` on PATH
- Node.js >= 18, `npx`
- The two **component dependencies** below (`comfyui-scheduler`,
  `remotion-video-template`) — installed under the workspace's `dep/` directory
- A running ComfyUI server with default workflows imported

### Installing the two component dependencies

`comfyui-scheduler` (the ComfyUI CLI) and `remotion-video-template` (the
Remotion render backend) are separate repositories. Install them under the
**workspace's `dep/` directory** — i.e. `dep/` inside the workspace root (the
directory that contains `projects/`). Configs store these as workspace-relative
paths (e.g. `dep/remotion-video-template`); the scripts resolve a relative path
against the workspace at runtime. `init_project.py` pre-fills `dependence_paths`
with these paths, so no manual path editing is normally needed.

Repository URLs:
- `comfyui-scheduler` — https://github.com/calcuforge/comfyui-scheduler.git
- `remotion-video-template` — https://github.com/calcuforge/remotion-video-template.git

```bash
# Run from the workspace root (the directory that contains projects/)
mkdir -p dep
git clone https://github.com/calcuforge/comfyui-scheduler.git dep/comfyui-scheduler
git clone https://github.com/calcuforge/remotion-video-template.git dep/remotion-video-template

pip install -e dep/comfyui-scheduler          # comfyui-scheduler CLI on PATH
( cd dep/remotion-video-template && npm install )   # node_modules
```

If the dependencies already exist somewhere else, set
`dependence_paths.remotion_template` / `dependence_paths.comfyui_scheduler` in
`project_config.yaml` to their paths (a `~`-path, absolute, or relative to the
workspace) instead of the `dep/` default.

---

## Project Management

**All projects MUST live under the workspace `projects/` directory.**

**Project directory naming:** `scripts/tool/init_project.py` creates the project
directory from the `scripts/project_config_tpl.yaml` template, named via its
`--project-dir-name` argument. **The project name is categorized across THREE
dimensions** (joined with `_`):

1. **Content category (内容分类)** — what the video is *about*: `air_crash`
   (空难事件), `history` (历史), `tech` (科技), `hardware` (硬件), ... Derive it
   from the user's topic.
2. **Narrative structure (叙事结构)** — how it is *told*: `documentary` (纪录片),
   `knowledge_sharing` (知识分享), `news_broadcast` (新闻播报), `product_intro`,
   `data_report`, `tutorial`, ...
3. **Fine-grained parameters (细分参数)** — include only what the user explicitly
   specified and is important: `resolution` (`1080p`/`4k`), `orientation`
   (`horizontal`/`vertical`), theme, language, target audience, ...

If the name already exists, a numeric suffix is appended automatically:
`air_crash_documentary_1080p_horizontal`,
`air_crash_documentary_1080p_horizontal2`, ...

**Example:** user asks "制作一个1080P横屏的空难纪录片" → content=`air_crash`,
structure=`documentary`, params=`1080p`+`horizontal` →
`projects/air_crash_documentary_1080p_horizontal/`. Check whether a project whose
**all three dimensions match** already exists; if not, create a new one.

After creation, edit `project_config.yaml` to set `project.name` (the same
categorized name, e.g. `air_crash_documentary_1080p_horizontal`),
`project.video_style`, `project.target_audience`, and other request-dependent
fields. **`project.name` MUST be the categorized name — never the specific video
title.**

**Video directory — never reuse.** Every video-making request creates a NEW
`video{N}/` directory (`video1`, `video2`, ...). Each time the user asks to make
a video, create the next available `video{N}/`; never reuse or overwrite an
existing one. (Resuming an *interrupted* pipeline continues the same in-progress
`video{N}/` — that is recovery, not reuse.)

**Project directory reuse** (the table below is about the *project* dir, not the
video dir):

| Situation | Action |
|-----------|--------|
| First video request | Run Step 1: create `projects/{content}_{structure}_{params}/` |
| Same content + structure + params | Reuse existing project, then create a new `video{N}/` inside it |
| Any dimension differs | Run Step 1: create a new project directory |

To determine project reuse: compare **ALL** categorization dimensions — content
category, narrative structure, and every explicitly-specified fine parameter
(resolution, orientation, theme, language, target audience). **Reuse only if
every dimension matches.** If the request maps to a different content category or
structure, or adds/removes a fine parameter (e.g. 1080p vs 4K, horizontal vs
vertical), create a new project — even when one dimension (e.g. `documentary`) is
shared. Each video request still creates a fresh `video{N}/` inside.

### Project Output Layout

```text
projects/
├── project1/
│   ├── project_config.yaml        # Project global preferences
│   ├── voice_file.wav             # TTS reference voice (shared by all videos)
│   ├── bgm.mp3                    # Background music (Step 11, shared by all videos)
│   ├── ad_video/                  # Ad short videos for Step 14 (pre-created, empty; drop ad files here)
│   ├── video1/
│   │   ├── result.mp4             # Final rendered video (Step 13)
│   │   ├── final.mp4              # With ad videos inserted (Step 14, when ad_video.enabled and ads found)
│   │   ├── video_config.yaml      # Topic (Step 2) + content summaries (Step 5)
│   │   ├── video_struct.yaml      # Video structure (stories → sections (one narration) → scenes (1-N, percentage))
│   │   ├── video_tasks.yaml       # AIGC task list
│   │   ├── remotion_sections.yaml # Remotion render config
│   │   ├── tmp/                   # General temporary files (cache, discovery results, etc.)
│   │   ├── search_results/
│   │   │   ├── result1.md         # Research result 1
│   │   │   └── result2.md         # Research result 2
│   │   └── stories/
│   │       ├── story1/
│   │       │   ├── script.md      # Chapter narration script (Step 5)
│   │       │   └── narration1/
│   │       │       ├── speech.wav # Narration audio
│   │       │       └── scenes/
│   │       │           ├── video_prompt_{scene_id}.yaml  # Structured video prompt per scene (Step 8a)
│   │       │           ├── origin_scene1.png  # AIGC raw output
│   │       │           ├── scene1.png         # Upscaled asset
│   │       │           ├── origin_scene2.mp4
│   │       │           └── scene2.mp4
│   │       └── story2/
│   └── video2/
└── project2/
```

Detailed structure reference: [templates/demo_projects/](templates/demo_projects/)

---

## Execution Modes

### Auto Mode (default)

The agent makes **all decisions autonomously** across all 13 steps. No user
interaction is required until the final video is ready. Infer sensible
defaults from the user's request (language, style, audience, duration).

### Manual Mode

The agent **pauses for user confirmation** at key points:

| When | What to ask / report |
|------|---------------------|
| **Before Step 1** (project_config generation) | Ask user to confirm: video_style, target_audience, language, orientation, resolution, duration, tts backend |
| **Before Step 2** (topic selection) | Present the chosen topic (auto) or confirm the user's topic; ask user to approve before proceeding |
| **After each step completes** | Report which artifacts were generated (file paths), then wait for user confirmation before starting the next step |

In manual mode, never proceed to the next step until the user explicitly
confirms (e.g., "ok", "continue", "next", "确认", "继续").

### Mode Detection

- **Step 1:** project_config.yaml does not yet exist. If the user explicitly
  requests manual interaction ("I want to control each step", "interactive",
  "手动模式"), run Step 1 in manual mode (ask before creating the config).
  Otherwise default to auto. Write the chosen mode into `project.creation_mode`.
- **Step 2 onwards:** Read `project.creation_mode` from project_config.yaml to
  determine behavior. Do NOT rely on conversational memory — always re-read the
  field from the file.

---

## Workflow

> Detailed step-by-step instructions:
> - Steps 1–4 (Setup): [references/workflow-setup.md](references/workflow-setup.md)
> - Steps 5–7 (Content): [references/workflow-content.md](references/workflow-content.md)
> - Steps 8–14 (Production): [references/workflow-production.md](references/workflow-production.md)

| # | Step | Key Script | Output |
|---|------|-----------|--------|
| 1 | Project initialization | `scripts/tool/init_project.py`, `scripts/verify/verify_project_config.py`, `scripts/tool/check_environment.py` | `project_config.yaml` |
| 2 | Define topic | — (agent research) | `video_config.yaml` |
| 3 | Topic research | `scripts/search_provider/search.py`, `scripts/search_provider/search_rss.py` | `search_results/*.md` |
| 4 | Design chapter list | `scripts/verify/verify_stories.py` | `video_struct.yaml` (stories only) |
| 5 | Write chapter scripts | `scripts/verify/verify_story_scripts.py` | `stories/{story_id}/script.md`, `video_config.yaml` (summary + chapter_summaries) |
| 6 | Design scene list | `scripts/tool/generate_scene_list.py`, `scripts/verify/verify_video_struct.py` | `video_struct.yaml` (full structure) |
| 7 | TTS + frame calculation | `scripts/tool/run_tts.py`, `scripts/verify/verify_audio.py` | `speech.wav` per scene |
| 8 | Search stock media | `scripts/search_provider/search_stock_media.py`, `scripts/verify/verify_stock_assets.py` | `scenes/origin_*` stock assets |
| 9 | Design AIGC prompts + plan tasks | `scripts/tool/build_video_prompt.py`, `scripts/verify/verify_video_tasks.py` | `video_prompt_{scene_id}.yaml` per scene, `video_tasks.yaml` |
| 10 | Execute AIGC tasks | `scripts/tool/run_aigc.py`, `scripts/tool/run_upscale.py`, `scripts/verify/verify_aigc_assets.py` | `scenes/` assets |
| 11 | Generate background music | `scripts/tool/run_bgm.py` | `projects/{name}/bgm.mp3` |
| 12 | Generate remotion config | `scripts/tool/generate_remotion_sections.py`, `scripts/verify/verify_remotion_sections.py`, `scripts/verify/verify_remotion_data.py` | `remotion_sections.yaml` |
| 13 | Render video | `scripts/tool/render.py` | `result.mp4` |
| 14 | Insert ad videos | `scripts/tool/insert_ad_videos.py` | `final.mp4` (when `ad_video.enabled` and ads found) |

**Mandatory validation gates:**

- After Step 1: `verify_project_config.py` must exit 0
- After Step 1: `check_environment.py` must exit 0 (ComfyUI + TTS nodes reachable — the ONLY way node availability is determined)
- After Step 4: `verify_stories.py` must exit 0 (re-do step if not)
- After Step 5: `verify_story_scripts.py` must exit 0
- After Step 6: `verify_video_struct.py` must exit 0
- After Step 7: `verify_audio.py` must exit 0
- After Step 8: `verify_stock_assets.py` must exit 0
- After Step 9: `verify_video_tasks.py` must exit 0
- After Step 10: `verify_aigc_assets.py` must exit 0
- After Step 11: `run_bgm.py` must exit 0 (skipped when `bgm.enabled: false`; fill `bgm.prompt` in `project_config.yaml` first — it is empty at init)
- After Step 12: `verify_remotion_sections.py` must exit 0, then `verify_remotion_data.py` must exit 0
- After Step 14: `insert_ad_videos.py` must exit 0 (skipped when `ad_video.enabled: false` or no ad videos found; for `insert_position: middle` fill `ad_video.insert_after_story` first)

---

## Hard Rules

| Rule | Requirement |
|------|-------------|
| **Projects under workspace** | All project directories MUST be under `projects/` in the workspace. Never create outside. |
| **Project name = categorized** | `project.name` MUST be the categorized project name derived from content + narrative structure + fine params (e.g. `air_crash_documentary_1080p_horizontal`) — never the specific video title. |
| **New video dir per request** | Every video-making request creates a NEW `video{N}/` directory. Never reuse or overwrite an existing `video{N}/` — always pick the next available `N`. |
| **Audio-master clock** | Each narration's audio duration (plus `tts.pause_seconds` silence, default 0.5s) determines that narration's total frames: `narration.total_frame = ceil((audio_duration + pause_seconds) × fps)`. The narration's scenes split it by `percentage` (largest-remainder, Σ scene frames == narration.total_frame). Never hand-estimate. |
| **One narration = one section, split into scenes** | Each section has exactly one `narration` and 1-N scenes. A narration should usually drive MULTIPLE scenes — split long (>30-40 chars) or multi-idea narrations into 2+ scenes and set each scene's integer `percentage` (Σ = 100). A single scene is the exception for short, single-idea narrations. |
| **Scene percentage split** | Each section's scene `percentage` values MUST be integers summing to exactly 100. Enforced by `verify_video_struct.py`. |
| **Script = merged narrations** | A chapter's `script.md` MUST equal all its narration contents concatenated in section order. Splitting a narration into scenes must not add/drop/reword text. Enforced by `verify_video_struct.py`. |
| **Data fields ≠ narration** | In data/text components, `label`/`title`/`suffix`/`headers` hold SHORT labels only — never a narration sentence (no sentence punctuation). The full sentence stays in `narration.content`. Don't make a `StatCounter`/`DataBar` just because narration contains a number. Enforced by `verify_remotion_data`. |
| **Visual-majority for narrative styles** | In `documentary`, `knowledge_sharing` and `news_broadcast` videos, visual scenes (`AssetImage`/`AssetVideo`/`KenBurnsImage`/`MediaSection`) MUST be the majority: documentary ≥ 75%, knowledge_sharing / news_broadcast ≥ 60% of ALL scenes. Data/text scenes are accents — default each narration to a visual, ask "能换成画面吗?" before using a text component. Enforced by `verify_video_struct.py` (Step 6). |
| **Locale-aware search** | Detect network locale by REACHABILITY (Baidu reachable + Google blocked ⇒ China), not just system locale. In a domestic China network, NEVER use Google/Wikipedia (unreachable) — use Baidu/Bing/Baike only. `search.py` auto-drops google/wikipedia in China networks. |
| **Playwright for web** | All website access uses Playwright Chromium (headless), except where `curl` is explicitly specified (RSS feeds). |
| **Anti-slop narration** | Narration text MUST follow [references/natural-narration.md](references/natural-narration.md). No AI-sounding filler, no rhetorical hooks, no rule-of-three abuse. |
| **Narration length** | No hard character cap on narration `content`. Write substantive sentences and vary their length; split a narration into multiple scenes for visual reasons, not for length. |
| **Verify before proceed** | Each step's verify script must pass before moving to the next step. |
| **Node availability = script only** | Determine ComfyUI/TTS node availability EXCLUSIVELY via `scripts/tool/check_environment.py` (Step 1 gate): run it and read its JSON `data.guidance` on failure. NEVER probe nodes yourself — no curl/nc/Test-NetConnection/manual TCP/socket checks, no guessing from config values. If a backend step (7/9/10/11) later fails with a connectivity error, re-run `check_environment.py` to diagnose, then act on its guidance. |
| **Long tasks: background + 3h timeout** | All long-running scripts (TTS, AIGC, upscale, BGM, render) MUST be launched in the background (Bash `run_in_background: true`) so the conversation is never blocked waiting; continue with other ready work instead, and proceed when the completion notification arrives (then check exit status + artifacts). Set generous timeouts — at least 3 hours (10800s): `run_aigc.py --total-timeout 10800`, `render.py --timeout 10800`, `run_tts.py --timeout 10800`, `run_bgm.py --timeout 10800`. Never use default 1-2h timeouts for these steps. |
| **Absolute paths** | All script path arguments (`--config`, `--video-struct`, `--output`, etc.) MUST be absolute paths. Scripts reject relative paths with an error. |
| **Output confined to project** | ALL agent-produced files (search results, scripts, audio, AIGC assets, remotion configs, rendered video) MUST be written under the project directory's pre-defined resource dirs or its `tmp/` directory. Scripts that produce output files MUST expose a `--output` (or equivalent) parameter so output paths are explicit. NEVER write to system temp dirs (`/tmp`, `%TEMP%`, `TMPDIR`), the workspace root, or any path outside the project. |
| **Faststart progressive playback** | When presenting the finished video as a player in the chat, the mp4 MUST be faststart (moov atom at the front) and embedded for PROGRESSIVE playback — e.g. `<video controls preload="metadata" src="...">`. Do NOT load the whole file at once (`preload="auto"`). The render pipeline already emits faststart mp4s. |
| **AIGC cross-scene consistency** | For subjects that appear across multiple AIGC scenes (recurring characters, specific objects, branded items, consistent environments), the `common.subject.description` and `common.style` fields in all their `video_prompt_{scene_id}.yaml` files MUST use the SAME appearance description (same wording, same visual attributes). This prevents ComfyUI from generating visually inconsistent outputs for the same subject across scenes. If a character/object appears in N scenes, write the description once, then reuse it verbatim in all N prompt files. |
| **Stock media for generic visuals** | For scenes showing generic, non-specific visuals (atmosphere, mood, environment — NOT specific people/events/products), prefer `asset_generation_method: stock` over AIGC — but **only when the corresponding flag is enabled**: `stock_media.search_image` (default true) for image scenes, `stock_media.search_video` (default false) for video scenes. If a flag is false, use AIGC for that type. Also requires `stock_media.sources` to be non-empty. Configure sources in `project_config.yaml` (each entry: `provider` + `api_key`). See `expression_intent_mapping.md` for when stock is appropriate. |
| **Ad insertion (Step 14)** | When `ad_video.enabled` (default true) and ad videos exist under `{project_root}/ad_video` or `ad_video.directories`, insert ALL found videos at the configured `ad_video.insert_position` (beginning \| middle \| end, default middle): the finished `result.mp4` is split at the chapter boundary and merged with the ads (ffmpeg) into `final.mp4`. For `middle`, the AGENT must pick the chapter boundary and fill `ad_video.insert_after_story` (a story id) before running the script. Deliver `final.mp4` when inserted, else `result.mp4`. |

---

## References

Load on demand — do NOT load all at once:

| File | Load when |
|------|-----------|
| [references/workflow-setup.md](references/workflow-setup.md) | Steps 1–4 — project init, topic, research, chapters |
| [references/topic-selection.md](references/topic-selection.md) | Step 2 — **only when auto topic selection is needed** (user only names a category: web-search candidates, de-dupe against existing project topics, then apply the full selection strategy) |
| [references/workflow-content.md](references/workflow-content.md) | Steps 5–7 — scripts, scene design, TTS |
| [references/workflow-production.md](references/workflow-production.md) | Steps 8–14 — stock media, AIGC, bgm, remotion config, render, ad insertion |
| [references/natural-narration.md](references/natural-narration.md) | Step 5 — writing chapter narration scripts |
| [references/search-providers.md](references/search-providers.md) | Step 3 — topic research |
| [references/expression_intent_mapping.md](references/expression_intent_mapping.md) | Step 6 — choosing scene types and components |
| [references/stock_image_mapping.md](references/stock_image_mapping.md) | Step 6 — **only if `stock_media.search_image: true`** |
| [references/stock_video_mapping.md](references/stock_video_mapping.md) | Step 6 — **only if `stock_media.search_video: true`** (default false) |
| [references/special-rules.md](references/special-rules.md) | Step 6 — style-specific scene constraints (e.g. documentary opens on video) |
| [templates/demo_projects/](templates/demo_projects/) | Any step — reference for config file structure |
