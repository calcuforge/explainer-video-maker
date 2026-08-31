# Workflow Steps — Setup Phase (Steps 1–4)

> **When to load:** Step 1 through Step 4 — project initialization, topic definition,
> research, and chapter design. Covers everything from a blank directory to a validated
> chapter list ready for script writing.

## Overview

The pipeline produces narration-driven explainer videos through 13 steps.
Audio drives visuals: narration audio length determines frame counts.

Structure hierarchy: **Story → Section → Scene**
- 1 story contains N sections; each section = exactly one narration
- Each narration (section) maps to 1-N scenes; every scene carries an integer
  `percentage` (Σ = 100 per narration)
- The narration audio duration determines `narration.total_frame`; each scene's
  frames = its percentage share (largest-remainder, Σ scene frames == total_frame)

**Output confinement — ALL files under the project:** every file produced during
the pipeline (search results, scripts, audio, AIGC assets, configs, video output)
MUST be written under the project directory in its designated resource
directories (see layout above) or its `tmp/` directory. Scripts MUST accept
`--output` (or equivalent) parameters so output paths are always explicit.
NEVER write to system temp dirs (`/tmp`, `%TEMP%`, `TMPDIR`), the workspace
root, or any path outside the project.

**Working principle — batch by story:** whenever a step creates a *large number*
of items, do it **one story at a time** rather than all at once — e.g., writing
chapter scripts (Step 5), splitting scenes and filling their `data`/`text`
fields (Step 6), and planning AIGC tasks (Step 9). Finish one story completely
before moving to the next; this keeps each batch focused and produces richer,
more consistent content.

### Project Output Layout

All pipeline artifacts live under the workspace `projects/` directory:

```text
projects/
├── {project_name}/
│   ├── project_config.yaml        # Step 1 — project global preferences
│   ├── voice_file.wav             # Step 1 — TTS reference voice
│   ├── bgm.mp3                    # Step 11 — background music (shared by all videos)
│   ├── ad_video/                  # Step 1 — ad short videos for Step 14 (pre-created, empty)
│   ├── {video_name}/
│   │   ├── video_config.yaml      # Step 2 — topic definition; Step 5 adds content summaries
│   │   ├── search_results/        # Step 3 — research artifacts
│   │   │   ├── result1.md
│   │   │   └── result2.md
│   │   ├── video_struct.yaml      # Step 4 (chapters) + Step 6 (scenes)
│   │   ├── stories/               # Step 5 (scripts), Step 7 (audio), Step 8 (stock), Step 9 (prompts), Step 10 (AIGC)
│   │   │   └── {story_id}/
│   │   │       ├── script.md          # Step 5 — chapter narration script
│   │   │       └── {narration_id}/
│   │   │           ├── speech.wav
│   │   │           └── scenes/
│   │   │               ├── video_prompt_{scene_id}.yaml  # Step 9a — structured video prompt per scene
│   │   │               ├── origin_{scene_id}.{png|mp4}
│   │   │               └── {scene_id}.{png|mp4}
│   │   ├── video_tasks.yaml       # Step 9b — AIGC task list
│   │   ├── tmp/                   # General temporary files (cache, discovery results, etc.)
│   │   ├── remotion_sections.yaml # Step 12 — render config
│   │   └── result.mp4             # Step 13 — rendered video
│   │   └── final.mp4              # Step 14 — with ad videos inserted (when ads enabled + found)
```

---

### Execution Modes

| Mode | Behavior |
|------|----------|
| **Auto** (default) | Agent decides everything autonomously. No pauses. Runs Steps 1-9 end-to-end. |
| **Manual** | Agent pauses for confirmation at: (1) before generating project_config.yaml, (2) before topic selection, (3) after every step completes. |

**Mode detection:**
- **Step 1:** `project_config.yaml` does not exist yet. If the user explicitly requests manual interaction ("interactive", "手动模式", "I want to control each step"), run in manual mode. Otherwise default to auto. Write the decision into `project.creation_mode`.
- **Step 2 onwards:** Always read `project.creation_mode` from `project_config.yaml` to determine behavior. Do NOT rely on conversational memory — re-read the field from the file at each step boundary.

**Manual mode protocol:**
- Before Step 1: ask the user to confirm project parameters (style, audience, language, orientation, resolution, duration, TTS backend).
- Before Step 2: present the topic choice and wait for approval.
- After each step: report generated artifacts (list file paths), then wait for the user to say "continue" / "确认" / "ok" before proceeding.
- Never skip a confirmation gate in manual mode.

---

## Step 1: Project Initialization

**When:** First video request, or when category/parameters differ from existing projects.

> **Manual mode:** Before running init_project.py, present all configurable
> fields to the user and ask for confirmation. Do NOT create the project until
> the user approves the parameters.

**What to do:**

1. **Generate the project skeleton with the init script.** All default field
   values live in the template `scripts/project_config_tpl.yaml` (nothing is
   hardcoded in the script). The script copies the template into a new project
   directory under `projects/`, fills `project.project_root_path` (the only
   field it sets), and writes `project_config.yaml`:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/init_project.py" \
     --projects-dir /abs/path/projects \
     --project-dir-name air_crash_documentary_1080p_horizontal
   ```
   - `--project-dir-name` is the project directory name, **categorized across
     three dimensions** joined with `_`: content category (e.g. `air_crash` 空难,
     `history`, `tech`, `hardware`) + narrative structure (e.g. `documentary`,
     `knowledge_sharing`, `news_broadcast`) + fine params the user specified
     (e.g. `1080p`, `horizontal`). A numeric suffix is appended if the name
     already exists (`air_crash_documentary_1080p_horizontal`,
     `air_crash_documentary_1080p_horizontal2`, ...). Reuse a project only when
     ALL dimensions match; otherwise create a new one.
   - The JSON output's `data.project_dir` and `data.project_config` give the created
     project directory and `project_config.yaml` locations. `data.agent_supplement`
     lists the fields left empty for you to fill.

2. **Edit the created `project_config.yaml` directly.** **Never modify a field
   that already has a value** (template default OR script-generated) **unless
   the user explicitly asks for a different value.** Only fill fields that are
   empty or placeholder — this applies to the entire project-config edit at
   creation time, not just the fields listed below.

   **Fill these** (empty / placeholder in the template):
   - `project.name` — replace the `my-project` placeholder with the video
     CATEGORY name (the `video_style` value, e.g. `documentary`) — do NOT use the
     specific video title
   - `project.language` — `zh-CN` or `en-US` (match the user's language)
   - `project.video_style` — e.g., `documentary`, `knowledge_sharing`, `news_broadcast`, `product_intro`, `data_report`, `tutorial`
   - `project.target_audience` — e.g., `general`, `tech_enthusiasts`, `students`, `professionals`, `investors`

   **Leave these as-is** (sensible defaults — change only on the user's request):
   `video.orientation` / `resolution` / `fps`, `aigc.*` dimensions and `seed`,
   `tts.backend` / `speed` / `volume` / `pause_seconds`, `theme.*`,
   `content.duration`, `render.*` (segmented-render tuning), `subtitle.*`.
   `tts.voice_instruct` is EMPTY at init —
   fill it with the target voice characteristics — INCLUDE a fast pace
   (e.g., `男，中年，中音调，语速快` / `male, middle-aged, moderate pitch, fast
   pace`): each synthesized narration is time-stretched to the uniform
   speech-rate standard (5 字/秒 @ speed=1.0), and a natively fast reference
   voice keeps those adjustments small (less atempo distortion); see
   `comfyui-scheduler/doc/workflow.md` for valid voice attributes.

   **`dependence_paths` is pre-filled by `init_project.py`** to the workspace's
   `dep/` directory as workspace-relative paths
   (`dep/remotion-video-template` and `dep/comfyui-scheduler`), resolved against
   the workspace (the directory that contains `projects/`) at runtime. These are
   the locations the dependencies should be cloned into (see SKILL.md "Installing
   the two component dependencies" for the repo URLs and commands). Only edit
   these paths if the dependencies actually live somewhere else; if they are not
   yet installed, clone them into the workspace `dep/` directory rather than
   changing the paths.

3. Fields that can wait for later steps:
   - `tts.voice_file` — Step 7 (auto-generated from `voice_instruct`)
   - `theme.*` / `subtitle.*` — defaults are fine; adjust only if the user requests
   - `rss_source_list` — Step 3

4. **Reference:** [demo_projects/project1/project_config.yaml](demo_projects/project1/project_config.yaml)

5. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_project_config.py" --config /abs/path/project_config.yaml
   ```
   Must exit 0 before proceeding.

6. **Environment connectivity check (ComfyUI + TTS).** Confirm the runtime
   services the pipeline depends on are reachable before investing in later
   steps. Node availability is determined EXCLUSIVELY by this script — never
   probe nodes yourself (no curl/nc/Test-NetConnection/manual TCP checks, no
   guessing from config values). The script lists the registered nodes via
   `comfyui-scheduler node list` (empty list → fails fast, no fallback), env-
   expands node URLs, TCP-probes each node, and checks the TTS endpoint only
   for `tts.backend: http_server` (the `comfyui_indextts` backend reuses the
   ComfyUI nodes):
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/check_environment.py" \
     --project-config /abs/path/project_config.yaml
   ```
   - **Exit 0** → environment ready, proceed.
   - **Exit 1** → read `data.guidance`, which tells you to ASK THE USER for the
     node information (ComfyUI address), then fix and re-run. Typically:
     - **ComfyUI unreachable** → ask the user for the ComfyUI node address
       (e.g. `http://<HOST>:8188`), register it with
       `comfyui-scheduler node add --id node1 --url http://<HOST>:8188`, import
       the workflows with `comfyui-scheduler workflow import-all`, then re-run
       this check. (Never guess the address or probe nodes yourself — the
       address always comes from the user.)
     - **TTS unreachable** → for `http_server`, start the TTS server / export the
       required env var (e.g. `BACKEND_PROXY_ENDPOINT`); or set `tts.backend` to
       `comfyui_indextts` in `project_config.yaml`.

   Resolve any failure before continuing — AIGC (Step 9) and TTS (Step 7) cannot
   run without a reachable backend. If a later backend step fails with a
   connectivity error, re-run this script (never diagnose by probing on your
   own) and act on its `data.guidance`.

7. `tts.voice_file` is empty by default and auto-generates during the audio/TTS
   step (pipeline Step 7): `run_tts.py` runs the `qwen3_tts_voice_design`
   workflow itself, post-processes the output, and writes
   `projects/{name}/voice_file.wav` (updating `tts.voice_file`). No manual
   workflow run is needed — keep `voice_file` empty and fill
   `tts.voice_instruct` now (it is REQUIRED before Step 7).

   **Quality note:** the qwen3 voice-design output is band-limited — energy
   above 2 kHz sits ~20 dB below the low band (muffled, s/f/l fricatives
   inaudible), which degrades voice cloning. `run_tts.py` post-processes its
   auto-generated reference with a 24 kHz normalize + high-shelf clarity boost
   (`tts.voice_ref_eq_db`, default 6 dB; content defaults to a fricative-rich
   balanced sentence, override with `tts.voice_ref_content`).

---

## Step 2: Define Topic Direction

**When:** Every new video.

> **Manual mode:** Present the topic (auto-selected or user-specified) and ask
> the user to confirm before proceeding. In auto mode, proceed directly.

**What to do:**

1. Create a **new** video directory: `projects/{project_name}/video{N}/`.
   Every video-making request gets its own directory — use the next available
   `N` (`video1`, `video2`, ...). **Never reuse or overwrite an existing
   `video{N}/`** for a new request.

2. **Auto topic selection** (user only names a category/direction, e.g.
   "制作一个空难视频" / "make an animal documentary"). **Must follow
   [references/topic-selection.md](topic-selection.md) end-to-end:**
   1. **Read existing project topics** — `projects/{project_name}/video{N}/video_config.yaml`
      `topic` fields of ALL existing videos; build the exclusion list
      (exact duplicates AND semantic duplicates are forbidden).
   2. **Web-search candidate topics** — do NOT pick from memory. Run `web_search`
      for the category from multiple angles (famous events, key figures, unsolved
      mysteries, controversies; Chinese + English queries) to collect 8-15
      concrete candidate topics with source/fact-richness notes.
   3. **Scan strategies, score, de-dupe** — apply the full selection strategy
      (content objects → narrative drivers → user value → emotion → title
      packaging), score each candidate with the TopicScore formula, drop
      candidates that duplicate existing project topics, filter weak ones.
   4. **Pick the primary topic** (plus backups) and write it into
      `video_config.yaml`. Example: "make an animal documentary" → "The
      Migration of Arctic Terns" (after web-search confirms rich material).
   - In **manual mode**, present the primary topic + alternatives and wait for
     user approval before writing the config.

3. **Specific topic** (user names a topic):
   - Use the user's topic directly (skip auto selection).

4. Create `video_config.yaml` (the content summaries — `summary`,
   `chapter_summaries` — are added in Step 5 after the scripts are written):
   ```yaml
   topic: <chosen topic title>
   ```

5. **Reference:** [demo_projects/project1/video1/video_config.yaml](demo_projects/project1/video1/video_config.yaml)

---

## Step 3: Topic Research

**When:** After topic is defined.

**What to do:**

1. **Default:** Use the agent's built-in `web_search` tool for initial research.

2. **Extended search** — choose providers based on video type:

   | Video Type | Recommended Providers |
   |-----------|----------------------|
   | Documentary | `search.py` (encyclopedia + search engine) |
   | News / Daily Report | `search_rss.py` (RSS feeds) |
   | Product / Price Report | Custom provider (agent-coded) |
   | Knowledge / Tutorial | `search.py` + agent web_search |

3. **Using search_provider/search.py:**
   ```bash
   python3 "${SKILL_DIR}/scripts/search_provider/search.py" \
     --query "Air France Flight 447 accident investigation" \
     --output /abs/path/projects/air_crash_documentary/video1/search_results/result1.md
   ```
   - Sources auto-detected by locale (China: bing+baike, else: google+wikipedia)
   - Override with `--sources bing,baike`

4. **Using search_provider/search_rss.py:**
   - First check `project_config.yaml` → `rss_source_list` for cached feeds
   - If suitable feeds exist, use them directly:
     ```bash
     python3 "${SKILL_DIR}/scripts/search_provider/search_rss.py" \
       --feed-url "https://rsshub.app/36kr/newsflashes" \
       --keywords "GPU,pricing" \
       --output /abs/path/projects/air_crash_documentary/video1/search_results/result2.md
     ```
   - If no suitable feeds, discover them:
     ```bash
     python3 "${SKILL_DIR}/scripts/tool/search_rss_discovery.py" \
       --query "GPU pricing news" \
       --output /abs/path/projects/{project}/video{N}/tmp/rss_sources.json
     ```
     Then cache discovered feeds into `project_config.yaml` → `rss_source_list`.

5. **Custom providers:** For specialized data (e.g., e-commerce price scraping), the agent writes a custom search provider script. Place it in `search_provider/` and document its usage.

6. Save all results to `projects/{project}/video{N}/search_results/result{M}.md`

7. **Reference:** [search-providers.md](search-providers.md) for provider details.

---

## Step 4: Design Chapter List

**When:** After research is complete.

**What to do:**

1. Based on research, divide the content into **stories** (chapters/sections).
   Lay out the whole `stories` list in one go — just each story's `id` + `name`.
   This is cheap and locks in the overall narrative arc; the scene-level detail
   comes later (Step 6).

   **Chapter count reference** — `content.duration` in project_config.yaml
   controls the number of chapters (stories) only:

   | Duration | Stories (章节数) |
   |----------|------------------|
   | short    | 2-3              |
   | medium   | 5-7              |
   | long     | 8-12             |

2. Create `video_struct.yaml` with the chapter list ONLY — no `section_list` yet:
   ```yaml
   stories:
     - id: story1
       name: <chapter title>
     - id: story2
       name: <chapter title>
   ```

3. **Reference:** [demo_projects/project1/video1/video_struct.yaml](demo_projects/project1/video1/video_struct.yaml)

4. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_stories.py" --video-struct /abs/path/video_struct.yaml
   ```
   If it fails, fix and re-validate. Do NOT proceed until exit 0.
