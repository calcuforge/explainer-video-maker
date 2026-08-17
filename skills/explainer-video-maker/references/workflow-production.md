# Workflow Steps — Production Phase (Steps 8–13)

> **When to load:** Step 8 through Step 13 — stock media search, AIGC prompt design,
> task execution, upscale, background music, Remotion config generation, and final
> render. Also includes step completion reporting and resumption logic.

**Prerequisite:** [workflow-content.md](workflow-content.md) Steps 5–7 must be
complete (all narration audio generated, `total_frame` fields populated).

---

## Step 8: Search Stock Media

**When:** After TTS is complete. Only runs if there are scenes with
`asset_generation_method: stock` in `video_struct.yaml`.

**Purpose:** Search and download stock photos/videos from web sources for scenes
that show generic, non-specific visuals (atmosphere, mood, environment) where
AIGC precision is unnecessary and stock media is faster and cheaper.

**Prerequisite — configure sources:** Stock media search requires at least one
provider configured in `project_config.yaml` → `stock_media.sources`, each with
its `api_key` set directly in the config:

```yaml
stock_media:
  sources:
    - provider: pexels       # photos + videos
      api_key: "your-key"
    - provider: pixabay      # photos + videos
      api_key: "your-key"
    - provider: unsplash     # photos only
      api_key: "your-key"
```

If no sources are configured (or all entries lack an `api_key`), this step is
skipped entirely.

**What to do:**

1. Run the stock media search script:
   ```bash
   python3 "${SKILL_DIR}/scripts/search_provider/search_stock_media.py" \
     --project-config /abs/path/project_config.yaml \
     --video-struct /abs/path/video_struct.yaml
   ```
   - Iterates all scenes where `asset_generation_method: stock` and
     `origin_asset_path` is empty.
   - Builds a search query from each scene's `visual_content` + `intent`.
   - Searches configured providers at the project's target resolution
     (`video.resolution` / `video.orientation`).
   - Downloads the best match to
     `stories/{story_id}/{narration_id}/scenes/origin_{scene_id}.{ext}`.
   - If the downloaded resolution >= target, sets `asset_path` directly
     (no upscale needed). Otherwise leaves `asset_path` empty for Step 10.
   - **Idempotent:** re-running skips scenes whose `origin_asset_path` already
     exists. Pass `--force` to re-download all.

2. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_stock_assets.py" \
     --video-struct /abs/path/video_struct.yaml
   ```
   Must exit 0 before proceeding. If scenes failed to download, check API keys
   and network, then re-run the search script (it resumes from where it left off).

---

## Step 9: Design AIGC Prompts and Plan Tasks

**When:** After TTS is complete and frames are calculated.

This step has two parts: **8a** designs structured video prompts (saved per
scene), and **8b** plans the AIGC tasks in `video_tasks.yaml` using those prompts.

### Step 9a — Design Structured Video Prompts

1. Review `video_struct.yaml` — identify all scenes where `is_aigc_scene: true`.
   For each AIGC scene, based on its `intent` and `visual_content`, design a
   structured video prompt and save it to
   `stories/{story_id}/{narration_id}/scenes/video_prompt_{scene_id}.yaml`
   — **one prompt file PER SCENE** (a narration split into 1-N scenes has one
   `video_prompt_<scene_id>.yaml` per scene):

   ```yaml
   video_prompt:
     type: text_to_video  # text_to_video / image_to_video / text_to_image
     common:
       subject:    {main: "...", description: "..."}
       scene:      {location: "...", environment: "..."}
       time:       {period: "...", lighting: "..."}
       style:      {visual: "...", color: "...", quality: "..."}
       action:     {description: "..."}
       camera:     {shot: "...", movement: "...", angle: "..."}
     text_to_video:
       prompt: "<one-sentence prompt>"
       negative_prompt: ["term1", "term2"]
     image_to_video:
       motion:
         type: camera_and_object_motion
         camera: {movement: "..."}
         object: {movement: "..."}
     text_to_image:
       prompt: "<one-sentence prompt>"
       negative_prompt: ["term1", "term2"]
   ```

   - For video scenes (`type: video`): include both `text_to_video` and
     `image_to_video` sections (one prompt file covers both workflow tasks).
   - For image scenes (`type: image`): include only the `text_to_image` section.
   - Work **one story at a time** (consistent with Steps 5-6).
   - **Text in images — 文字嵌入专用模板.** When an AIGC image scene needs
     readable text (a screen, sign, label, book cover, ...), describe the text
     content, font style, and layout explicitly in the prompt — a vague phrase
     like "shows some text" will not render legibly:
     - 当你需要在图像中包含可读文字时，务必使用明确的语言描述内容、字体风格和排版位置。
     - 举例：画面中央有一个发光的LED屏幕，上面显示'Hello World'和'你好世界'，中英文并列，无衬线字体，蓝色渐变背景
     - 小贴士：使用"displaying"、"written on"、"engraved with"等动词明确指出文字存在形式
     - 小贴士：指定字体类型（如serif, sans-serif, calligraphy）有助于提升一致性

2. **Cross-scene consistency — recurring subjects.** Before writing any prompt
   files, scan ALL scenes across ALL stories to identify subjects that appear
   more than once: recurring characters (e.g., "Einstein"), specific objects
   (e.g., "a red 1965 Ford Mustang"), branded items, or consistent environments
   (e.g., "a 1950s New York street"). For each recurring subject, write ONE
   canonical `common.subject.description` and `common.style` block, then reuse
   it **verbatim** across all scenes where that subject appears. Do NOT rephrase
   or vary the wording — even small differences cause ComfyUI to produce
   visually inconsistent outputs. This is mandatory for generated imagery; AIGC
   models have no persistent identity across independent generations, so prompt
   consistency is the only mechanism to approximate visual continuity.

### Step 9b — Plan AIGC Tasks

1. **Plan tasks one story at a time** — do NOT plan all stories' tasks in a
   single pass. For the current story, identify its AIGC scenes, generate their
   prompts, and append the tasks to `video_tasks.yaml`.

2. For each AIGC scene in the current story:
   - **Generate the flat prompt** by calling `build_video_prompt.py` on the
     scene's `video_prompt_{scene_id}.yaml` (call once per task type for scenes
     with both t2v and i2v tasks):
     ```bash
     python3 "${SKILL_DIR}/scripts/tool/build_video_prompt.py" \
       --prompt-yaml /abs/path/to/video_prompt_{scene_id}.yaml --type text_to_video
     ```
     Use the output `data.prompt` in the task payload's `prompt` field.
   - **Workflow pipeline:** Choose from available workflows (see `comfyui-scheduler/doc/workflow.md`):
     - `z_image_fp16` — text-to-image
     - `ltx2.3_t2v_int8` — text-to-video
     - `ltx2.3_i2v_int8` — image-to-video
     - `ltx2.3_flf2v_int8` — first-last-frame-to-video
     - `qwen_image_edit_2511_int8_step4` — image-to-image
   - **Dependencies:** e.g., text-to-image → image-to-video (two groups)

3. Append the current story's tasks to `video_tasks.yaml`:
   - **Group by `workflow_code`** — tasks are organized by workflow and shared
     across stories. Append this story's tasks to the matching group (create the
     group the first time a `workflow_code` appears). Groups that others depend
     on go first (`task_group_ordinal`).
   - **Global ordinals** — keep one continuous `ordinal` counter across all
     stories; do NOT restart it per story.
   - Use `$taskN` in a payload to reference a dependent task's output (a scene's
     image-to-video task depends on its own text-to-image task).
   - Use dimensions from `aigc` config:
     - Image tasks: `origin_image_width` × `origin_image_height` (default 1280×720)
     - Video tasks: `origin_video_width` × `origin_video_height` (default 1280×720)
   - Calculate `total_frame` for video tasks as the scene's percentage share of
     the narration: `scene_frames = round(percentage/100 × narration.total_frame)`
     (largest-remainder, so Σ scene frames == narration.total_frame).

4. Repeat for every story until all AIGC tasks are in `video_tasks.yaml`.

5. **Reference:** [demo_projects/project1/video1/video_tasks.yaml](demo_projects/project1/video1/video_tasks.yaml)

6. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_video_tasks.py" \
     --video-tasks /abs/path/video_tasks.yaml \
     --video-struct /abs/path/video_struct.yaml
   ```

---

## Step 10: Execute AIGC Tasks

**When:** After video_tasks.yaml passes validation.

**What to do:**

1. Run AIGC generation **(run in the background — Bash `run_in_background: true`; use `--total-timeout 10800` (3h) minimum for safety — video generation may take 1-2h per task, set higher for many tasks)**:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/run_aigc.py" \
     --project-config /abs/path/project_config.yaml \
     --video-struct /abs/path/video_struct.yaml \
     --video-tasks /abs/path/video_tasks.yaml \
     --total-timeout 10800
   ```
   - `--timeout 1800` (default): per-task subprocess timeout (30min per task)
   - `--total-timeout 10800` (3h): entire script wall-clock timeout. **Must be at least 10800 — never use the 2h default; increase further for longer videos with many tasks.**
   - Do NOT block waiting: continue with other ready work (e.g. next story's prompts); when the background completion notification arrives, check the exit status and generated assets.
   - Executes task groups in order, resolves `$taskN` dependencies,
     saves outputs as `origin_{scene_id}.{ext}`, and updates `origin_asset_path`.
   - **Idempotent:** tasks whose `origin_{scene_id}.{ext}` already exists
     (non-empty) are skipped (reported as `skipped`) — safe to resume after an
     interruption. Pass `--force` to re-execute ALL tasks. Use `--force` (or
     `--retry`) after editing task payloads, otherwise the stale outputs are kept.

   **Partial retry ("抽卡"):** To re-generate specific tasks (e.g., user is
   unsatisfied with a scene's result in manual mode):
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/run_aigc.py" \
     --project-config /abs/path/project_config.yaml \
     --video-struct /abs/path/video_struct.yaml \
     --video-tasks /abs/path/video_tasks.yaml \
     --retry 1,3
   ```
   - `--retry` accepts comma-separated task ordinals from video_tasks.yaml.
   - If a retried task has dependents (other tasks with `dependent_task` pointing
     to it), those dependents are **automatically included** in the retry set
     (transitive — the entire downstream chain re-executes).
   - The script deletes origin files for the retry set, then runs the normal
     pipeline. Unaffected tasks are skipped (their files still exist).
   - After retry, re-run `run_upscale.py` to regenerate upscaled assets for the
     affected scenes.

2. Run upscale (skips automatically if origin dimensions >= target):
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/run_upscale.py" \
     --project-config /abs/path/project_config.yaml \
     --video-struct /abs/path/video_struct.yaml
   ```
   This upscales origin assets to target resolution, **compresses video assets
   with h264 crf 18** (significantly reduces file size for Remotion render
   without visible quality loss), and updates `asset_path`.

3. **Compress image assets to JPEG quality 95:**
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/compress_images.py" \
     --video-struct /abs/path/video_struct.yaml
   ```
   Converts all image assets (.png / .webp / .bmp / .tiff) to JPEG at quality
   95 via ffmpeg, updates `asset_path` and `origin_asset_path` in
   `video_struct.yaml`, and deletes the original files. Video files (.mp4 etc.)
   are left untouched — they were already compressed with h264 crf 18 during
   upscale. **Run this BEFORE Step 12** so `generate_remotion_sections.py`
   picks up the compressed .jpg paths.

   **Idempotent:** re-running skips files that are already JPEG.

4. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_aigc_assets.py" \
     --video-struct /abs/path/video_struct.yaml --check-upscaled
   ```

---

## Step 11: Generate Background Music

**When:** Once per project, after AIGC is done and before generating the remotion
config (the config step copies the BGM into the video dir for render). The BGM is
a project-level resource shared by all videos — it is generated a single time.

**Purpose:** Generate a background music track for the video from a text prompt
using comfyui-scheduler's text-to-music workflow (`stable_audio_3_medium`), and
record its path in `project_config.yaml` (`bgm.audio`). The music is mixed into
the final video in-render by Remotion `<Audio>` (no post-render ffmpeg step).

**Prerequisite:** A ComfyUI server reachable via `comfyui-scheduler` that has the
`stable_audio_3_medium` checkpoint and its text encoders installed, and the
workflow imported (`comfyui-scheduler workflow import-all` — the agent runs
this once after registering the node, following `check_environment.py`'s
Step 1 guidance).

**Config:** `project_config.yaml` → `bgm` block:

```yaml
bgm:
  enabled: true   # set false to skip BGM entirely
  audio: ""       # generated file path — written back by run_bgm.py
  prompt: ""      # REQUIRED — agent fills with a music description before running
  loop: true      # loop the BGM to fill the whole video
  length: 120     # target length in seconds
  volume: 0.10    # volume 0–0.3
```

**What to do:**

1. **Fill `bgm.prompt`** in `project_config.yaml` with a music description
   (style, instruments, mood — matching the video's tone), e.g.
   `舒缓的纪录片背景音乐，钢琴与弦乐，节奏平缓，情绪温和克制，无人声。` for a
   documentary or `upbeat corporate tech background music` for a product intro.
   It is left empty at project init; `run_bgm.py` errors if it is still empty.

2. Run the BGM generation script **(run in the background — Bash `run_in_background: true`; use `--timeout 10800` (3h) for safety)**:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/run_bgm.py" \
     --project-config /abs/path/project_config.yaml \
     --timeout 10800
   ```
   - Calls `comfyui-scheduler run -w stable_audio_3_medium` with `prompt` +
     `duration` (from `bgm.length`), downloads the result to
     `projects/{name}/bgm.mp3`, and writes `bgm.audio` back into
     `project_config.yaml`.
   - **Idempotent:** skipped when `bgm.enabled: false` or when `bgm.audio` already
     points to an existing file. Pass `--force` to regenerate.
   - If you already have your own music, just set `bgm.audio` to its path (and
     adjust `bgm.loop` / `bgm.volume`) — the step then skips generation.
   - If generation fails (scheduler unreachable, missing model), either fix the
     environment and re-run, or set `bgm.enabled: false` to render without BGM.

3. The remotion config step (Step 12) then copies `bgm.mp3` into the video
   directory and emits a `bgm:` block in `remotion_sections.yaml`, which
   `YamlVideo.js` renders as a looping `<Audio>` track at `bgm.volume`.

---

## Step 12: Generate Remotion Rendering Config

**When:** After all assets are verified.

**What to do:**

1. Generate the config skeleton:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/generate_remotion_sections.py" \
     --project-config /abs/path/project_config.yaml \
     --video-struct /abs/path/video_struct.yaml \
     --output /abs/path/remotion_sections.yaml
   ```

2. **Fill `remotion_data` for each scene.** The generated structure is nested:
   each `section_list` entry corresponds to ONE narration (`audio`) and its 1-N
   scenes (`scene_list`), with each scene's `total_frame` = its percentage share
   of the narration's `total_frame`. The script auto-populates `remotion_data`
   for AssetVideo/AssetImage and data/text scenes, but complex components may
   need enrichment. Consult the remotion-video-template README.md:

   | Component | Key Fields |
   |-----------|-----------|
   | QuoteBlock | `heading`, `quote`, `attribution` |
   | FeatureGrid | `heading`, `columns`, `items[{icon, title, description}]` |
   | IconCard | `heading`, `icon`, `title`, `description` |
   | ComparisonCard | `heading`, `left{title, items[], highlight}`, `right{...}` |
   | StatCounter | `heading`, `items[{value, suffix, label, icon}]` |
   | DataBar | `heading`, `items[{label, value}]` |
   | Timeline | `heading`, `items[{label, description}]` |
   | FlowChart | `heading`, `steps[{label, description, icon}]` |
   | CodeBlock | `heading`, `title`, `lines[]` |
   | DataTable | `heading`, `headers[]`, `rows[][]`, `highlightRows[]` |
   | DiagramReveal | `heading`, `direction`, `nodes[{id, label}]`, `edges[{from, to}]` |
   | AnimationDemo | `heading`, `type`, `color` |
   | AssetImage | `src`, `role`, `caption` |
   | AssetVideo | `src`, `role`, `muted` |
   | KenBurnsImage | `src`, `role`, `zoom` (in/out/none), `pan` (left/right/up/down/up-left/up-right/down-left/down-right/none), `caption`, `dim`, `totalFrame` |
   | MediaSection | `items[{src, alt, caption}]`, `columns` (2/3), `layout` (card/full), `text`, `data[{value, label, suffix}]` — auto-populated from `media_list` + `text` + `data` |
   | StatHighlight | `value`, `unit`, `label`, `description`, `icon` |
   | MetricsRow | `title`, `items[{value, label, suffix, icon}]` |
   | ProgressRing | `value` (0-100), `suffix`, `unit`, `label`, `size` |
   | StepProgress | `title`, `activeStep` (0-based), `steps[{label, description}]` |
   | SplitLayout | `title`, `description`, `rightImage` (auto-injected from asset_path), `rightCaption`, `rightItems[{icon, title, description}]`, `accent` (left/right) |
   | ZigzagCards | `title`, `items[{icon, title, description}]` |
   | KeywordCloud | `title`, `keywords[{text, weight}]` (weight 1-3) |
   | MapPins | `title`, `pins[{label, x, y, description}]` (x/y 0-100), `lines[{from, to}]` |
   | AudioWaveform | `audioSrc` (required — narration wav path), `mode` (bars/wave/dots), `position` (bottom/top/inline), `barCount`, `height`, `opacity` |

   **Icon field usage** — Components `FeatureGrid`, `IconCard`, `StatCounter`,
   `FlowChart` accept an `icon` field. Two formats are supported:

   | Format | Example | Description |
   |--------|---------|-------------|
   | Lucide name | `zap`, `arrow-right`, `Lightbulb`, `trending-up` | Any [Lucide icon](https://lucide.dev/icons/) name, kebab-case or PascalCase |
   | Emoji | `🚀`, `💡`, `📊` | Any emoji (≤4 chars), rendered as text |

   Commonly used icons for explainer videos:

   | Category | Icons |
   |----------|-------|
   | Tech | `cpu`, `code`, `server`, `database`, `cloud`, `wifi`, `smartphone` |
   | Data | `bar-chart`, `trending-up`, `pie-chart`, `activity`, `percent` |
   | People | `users`, `user`, `award`, `star`, `heart` |
   | Process | `zap`, `rocket`, `target`, `check-circle`, `arrow-right` |
   | Concepts | `lightbulb`, `book-open`, `globe`, `shield`, `key` |
   | Business | `dollar-sign`, `briefcase`, `shopping-cart`, `package`, `truck` |

   If an icon name is not found in Lucide, it renders as `[name]` placeholder text.

3. **Reference:** [demo_projects/project1/video1/remotion_sections.yaml](demo_projects/project1/video1/remotion_sections.yaml)

4. **Validate (structure):**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_remotion_sections.py" \
     --remotion-sections /abs/path/remotion_sections.yaml
   ```

5. **Validate (remotion_data per component):** calls remotion-video-template's
   `validate-remotion-data.mjs` to check each scene's `remotion_data` against
   the component's expected field schema (required fields, array items, enums):
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_remotion_data.py" \
     --remotion-sections /abs/path/remotion_sections.yaml \
     --project-config /abs/path/project_config.yaml
   ```
   Both validators must exit 0 before proceeding to Step 13.

---

## Step 13: Render Video

**When:** After remotion_sections.yaml passes validation.

**What to do:**

1. (Optional) Preview in Studio first:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/render.py" \
     --remotion-sections /abs/path/remotion_sections.yaml \
     --project-config /abs/path/project_config.yaml \
     --output /abs/path/result.mp4 \
     --studio
   ```

2. Render final video **(run in the background — Bash `run_in_background: true`; always pass `--timeout 10800` (3h) minimum — renders of long/4K videos can take hours)**:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/render.py" \
     --remotion-sections /abs/path/remotion_sections.yaml \
     --project-config /abs/path/project_config.yaml \
     --output /abs/path/projects/{project}/video{N}/result.mp4 \
     --timeout 10800
   ```
   Do NOT block waiting: continue with other ready work; when the background completion
   notification arrives, verify `result.mp4` exists and is non-empty.
   Rendering is **segmented + adaptive**: the video is split into frame-range
   segments (default 600 frames each) and concatenated with ffmpeg. Per-render
   concurrency (parallel frames inside one headless Chrome) is capped at 8 so
   frame buffers stay bounded (~1 GB @1080p / ~2 GB @4K per Chrome); when the CPU
   target (≈ half the effective cores; cgroup v2 limits are read in containers)
   exceeds the cap, surplus cores spill into more segment workers, which are also
   memory-bounded (~75% of RAM). On ≤16-core machines this is effectively
   single-process. Override via `render.segment_frames` / `render.segment_workers`
   in project_config.yaml (default auto). The render start log prints the
   detected resources and the chosen `segment_workers` / concurrency / estimated
   peak memory.

3. Verify the output file exists and is non-empty.

4. **If the render fails or is interrupted:** `render.py` writes the full
   Remotion/Node output to `render.log` (same directory as the output video).
   **Always read `render.log` first** to diagnose the cause — do NOT re-run
   blindly. Common failure patterns:

   | Symptom in render.log | Likely cause | Fix |
   |----------------------|-------------|-----|
   | `JavaScript heap out of memory` | Very long composition or high total parallelism | Workers are memory-bounded, but if it still OOMs lower `render.segment_workers` (set it explicitly) and/or `render.segment_frames` (smaller segments), or render at 1080p instead of 4K; as a last resort set `NODE_OPTIONS=--max-old-space-size=<MB>` for the render command |
   | `ENOENT: no such file` on an asset/audio path | Missing or mis-pathed file in remotion_sections.yaml | Check `src` / `audio` paths; re-run Step 10 (AIGC) or Step 12 (remotion config) |
   | `FFmpeg ... error` during concat | A segment failed to render, producing a corrupt partial file | Look earlier in the log for the segment's error; fix and re-render |
   | `timeout` / process killed | Render exceeded `--timeout` (default 1h) | Increase `--timeout` (min 10800 / 3h), or reduce video length / complexity |
   | `Cannot find module` / bundler error | `node_modules` missing or stale in remotion-video-template | Run `npm install` in the template directory |

5. **Deliver the video — faststart + progressive playback.** When outputting the
   finished `result.mp4` as a player component in the chat, embed it so it streams
   progressively instead of loading the whole file at once — e.g.
   `<video controls preload="metadata" src="...">`. The render output is already
   faststart (moov atom at the front), which is what enables progressive playback;
   if the player would buffer the entire file (`preload="auto"`), switch it to
   `preload="metadata"` (loads only the header/seek map first).

---

## Step Completion Reporting (Manual Mode)

In manual mode, after each step finishes, report artifacts and wait for user
confirmation. Use this template:

```
✅ Step {N} complete: {step name}

Generated artifacts:
- {file_path_1}
- {file_path_2}
...

{Optional: key summary, e.g. "3 stories, 8 sections / 15 scenes (each section = one narration)" or
"TTS generated 15 audio files, total duration 4:32"}

Shall I proceed to Step {N+1}: {next step name}?
```

Per-step artifact summary:

| Step | Artifacts to report |
|------|-------------------|
| 1 | `project_config.yaml`, `voice_file.wav` (if generated) |
| 2 | `video_config.yaml` (show the chosen topic) |
| 3 | `search_results/result{N}.md` (list all, count of results) |
| 4 | `video_struct.yaml` (story count — chapter list) |
| 5 | `stories/{story_id}/script.md` (count; total meets `min_story_chars` × chapters); `video_config.yaml` (summary + chapter_summaries) |
| 6 | `video_struct.yaml` (section + scene counts; each section = one narration) |
| 7 | `speech.wav` files (count, total duration) |
| 8 | `scenes/origin_*` stock downloads (count, provider, resolution) |
| 9 | `video_tasks.yaml` (task group count, total tasks) |
| 10 | `scenes/origin_*` AIGC + upscaled files (count) |
| 11 | `bgm.mp3` (project root; path written to `bgm.audio`) |
| 12 | `remotion_sections.yaml` (section count) |
| 13 | `result.mp4` (file size, duration) |

---

## Resuming After Interruption

> This applies only to continuing an **interrupted** pipeline for the *current*
> video request (recovery). It is NOT reuse: a brand-new video-making request
> always starts in a new `video{N}/` directory (see Step 2).

If the pipeline is interrupted, inspect the video directory to determine
where to resume:

| Files present | Resume from |
|--------------|-------------|
| `video_config.yaml` only | Step 3 |
| + `search_results/` | Step 4 (design chapters) |
| + `video_struct.yaml` (chapters only, no scripts) | Step 5 (write scripts) |
| + `stories/*/script.md` + `video_config.yaml` summaries (scripts, no scenes yet) | Step 6 (design scenes) |
| + `video_struct.yaml` (full scenes, no audio) | Step 7 (TTS) |
| + audio files + frames set | Step 8 (search stock media) |
| + `scenes/` with stock assets (or no stock scenes) | Step 9 (plan AIGC) |
| + `video_tasks.yaml` | Step 10 (execute AIGC) |
| + `scenes/` with all assets | Step 11 (generate bgm) |
| + `bgm.mp3` at project root (or `bgm.enabled: false`) | Step 12 (generate remotion) |
| + `remotion_sections.yaml` | Step 13 (render) |
