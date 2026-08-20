# Workflow Steps — Content Creation (Steps 5–7)

> **When to load:** Step 5 through Step 7 — writing narration scripts, designing
> scene lists, TTS synthesis, and frame calculation. Covers the transformation from
> research into a fully-scored scene structure with audio.

**Prerequisite:** [workflow-setup.md](workflow-setup.md) Steps 1–4 must be complete
(`video_struct.yaml` with a validated chapter list and `search_results/` populated).

---

## Step 5: Write Chapter Narration Scripts

**When:** After the chapter list passes validation.

**What to do:**

1. Write the narration script (讲稿) for each chapter using the format **one
   narration per line** — each line is exactly one narration (a complete thought;
   no character cap). Step 6 turns each line into a section (one narration) with
   a default single scene; you may then split a narration into 1-N scenes. The
   script is the chapter's single source of narration: **all narration contents
   merged together equal this script** (one line = one narration).

   ```text
   1956年夏天，达特茅斯学院的一场研讨会，正式确立了人工智能这门学科的名字。
   麦卡锡和明斯基等学者提出，要让机器去模拟人类的学习、推理和解决问题的能力。
   早期的研究者满怀乐观，他们相信用不了几十年，就能造出真正会思考的机器。
   ```

   **Write one chapter at a time, in story order, in multiple passes — do NOT
   write all chapters at once.** Finish one chapter's script before starting the
   next. Focusing on a single chapter produces richer, more detailed narration.

2. Save each chapter's script to `stories/{story_id}/script.md` (one file per
   chapter, under the video directory). Write **only narration lines** — no
   titles or headers; blank lines are allowed (ignored).

3. **Total narration length — no per-chapter minimum.** The COMBINED character
   count of ALL chapter scripts must reach `content.min_story_chars` × <number of
   chapters> (project_config.yaml, default **500** per chapter). A single chapter
   may be short as long as the overall narration is substantive. Enforced by
   `verify_story_scripts.py` (Step 5).

4. **Writing style — MUST follow [natural-narration.md](natural-narration.md):**
   - No AI filler phrases
   - No rule-of-three abuse
   - Vary sentence length
   - State facts directly
   - Write for the ear, not the eye

5. **Reference:** [demo_projects/project1/video1/stories/story1/script.md](demo_projects/project1/video1/stories/story1/script.md)

6. **After ALL chapter scripts are written — write the content summaries into
   `video_config.yaml`** (this completes Step 5):
   ```yaml
   topic: <chosen topic title>
   summary: <整部视频的内容梗概 — 1-3 句话，概括全片主题与叙事主线>
   chapter_summaries:
     <story_id>: <该章节的内容梗概 — 1-2 句话，概括本章内容与作用>
   ```
   - Write the summaries in your own words, derived from the actual script
     content — not from the topic alone. Each chapter gets exactly one entry,
     keyed by its `story_id` from `video_struct.yaml`; every story MUST appear.
   - Keep each summary substantive (a real synopsis, not a placeholder like
     "本章介绍该主题").

7. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_story_scripts.py" \
     --video-struct /abs/path/video_struct.yaml \
     --project-config /abs/path/project_config.yaml
   ```
   If it fails (script missing, below the minimum, or missing summaries), fix
   and re-validate. Do NOT proceed until exit 0.

---

## Step 6: Design Scene List from Scripts

**When:** After all chapter scripts pass validation.

**What to do:**

1. **Generate the narration skeleton with a script.** Run `generate_scene_list.py`
   to turn each chapter's `script.md` (one narration per line) into the
   `section_list` in `video_struct.yaml` — one section per line, each carrying
   that line as `narration.content` and a single default scene
   (`percentage: 100`). The display fields are left empty for you to fill next.
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/generate_scene_list.py" --video-struct /abs/path/video_struct.yaml
   ```
   - One section (narration) is created per non-empty line; scene/narration ids
     are assigned globally and stay unique. Stories that already have a
     `section_list` are skipped (pass `--force` to regenerate).
   - **Do NOT hand-write the `section_list` / narrations** — let the script
     generate them so they match `script.md` exactly. `verify_video_struct.py`
     checks that merging all narration contents reproduces `script.md`.

2. **Split each narration into 1-N scenes and set `percentage`.** Do NOT default
   every narration to a single scene — most narrations should drive **MORE than
   one** visual. Split a narration's `scene_list` into multiple scenes when:
   - the narration is **long (roughly > 30-40 characters)** — split it into 2+
     scenes so each scene shows a portion,
   - the narration contains **multiple distinct ideas / shots** (an event plus
     its aftermath, a person plus their work, a concept plus its impact, a wide
     establishing shot plus a close-up detail) — give each idea its own scene,
   - the pacing or the video style benefits from a visual change mid-narration.
   Set each scene's integer `percentage` so they sum to **100** (e.g. 60/40,
   70/30, 50/50, or three scenes 40/30/30). Keep a single scene
   (`percentage: 100`) only for short, single-idea narrations.
   Scene frames are derived from the percentages in Step 12 (largest-remainder,
   so Σ scene frames == narration.total_frame). Verify sums to 100 per narration
   (`verify_video_struct.py`).

3. **Fill the visuals, data and text — one story at a time.** Working one chapter
   at a time, complete that story's scenes before moving to the next (do NOT fill
   every story in one bulk pass). For each scene:
   - **Visual-first for narrative styles.** In `documentary`,
     `knowledge_sharing` and `news_broadcast` videos, default EVERY narration to
     a visual scene (image/video/MediaSection); a data/text component is the
     exception, used only when the narration's point IS the text/data (a spoken
     quote, a key metric, a structure the viewer must study). Before picking a
     data/text component, ask "能换成画面吗?" — see the **Visual-First
     Principle** in [expression_intent_mapping.md](expression_intent_mapping.md)
     and the **hard minimums** in [special-rules.md](special-rules.md)
     (documentary ≥ 75%, knowledge_sharing / news_broadcast ≥ 60% visual
     scenes, enforced by `verify_video_struct.py`).
   - Decide the expression method using
     [expression_intent_mapping.md](expression_intent_mapping.md):
     - **AIGC scenes** (`is_aigc_scene: true`, `asset_generation_method: aigc`): need AI-generated imagery/video
     - **Stock scenes** (`is_aigc_scene: true`, `asset_generation_method: stock`): search web stock media — only for generic, non-specific visuals (see the stock mapping files below)
     - **Data/text scenes** (`is_aigc_scene: false`): filled with text/data directly into Remotion components
   - **Apply style-specific constraints** from [special-rules.md](special-rules.md)
     based on `project.video_style` (e.g. a product intro opens on the product's
     appearance; a documentary closes on a wide shot + quote). These rules
     override the general mapping where they apply.
   - **Check `stock_media` flags before choosing stock:** read `project_config.yaml`
     → `stock_media.search_image` (default true) and `stock_media.search_video`
     (default false), and only then load the matching reference:
     - `search_image: true` → consult [stock_image_mapping.md](stock_image_mapping.md)
       for which intents suit a stock image (AssetImage / KenBurnsImage).
     - `search_video: true` → consult [stock_video_mapping.md](stock_video_mapping.md)
       for which intents suit stock video (AssetVideo).
     If a flag is false, do NOT load that file and do NOT set
     `asset_generation_method: stock` for that type — use AIGC instead. Example:
     if `search_video: false`, all video-type scenes must use
     `asset_generation_method: aigc` even when the content is generic. Also,
     `stock_media.sources` must be non-empty for stock search to work at all.
   - Fill the display fields from the research and the chapter script: `intent`,
     `is_aigc_scene`, `type`, `remotion_component`, `visual_content`, `data`,
     `text`, `workflows`.
   - **Multi-image scenes** (`remotion_component: MediaSection`): fill the
     `media_list` field instead of a single scene-level visual. Each item is one
     image: `id` (convention `<scene_id>-<n>`), `visual_content`, optional
     `caption`, `type: image`, `asset_generation_method` (`stock` | `aigc`), and
     `workflows` (aigc items only). Scene-level `visual_content`/`type`/
     `workflows`/`asset_path` are then unused for asset production. `is_aigc_scene`
     must be true if ANY item is aigc; aigc items become per-item tasks in
     `video_tasks.yaml` (referenced by their item id). See
     [expression_intent_mapping.md](expression_intent_mapping.md).
   - Leave EMPTY (auto-filled later): `asset_path`, `origin_asset_path`,
     `narration.total_frame`, `narration.audio_path`.
   - **Do NOT change `narration.content`** — it must stay equal to its `script.md`
     line (`verify_video_struct.py` enforces this).
   - **Data/text fields are data points, not sentences.** For `data`-component
     scenes, the `data` JSON's `label`/`title`/`suffix`/`headers` fields must be
     short labels (a few words, no sentence punctuation); the narrative sentence
     stays whole in `narration.content`. Do not create a `StatCounter`/`DataBar`
     scene just because the narration contains a number — only when the metric
     is the scene's point. See [special-rules.md](special-rules.md) general
     rules 4–5. (`verify_remotion_data` rejects sentence punctuation in labels.)

4. **One narration = one section:** the narration (section.narration) is the
   audio unit — one `speech.wav` per section, generated in Step 7. Its `total_frame`
   is split across the section's scenes by their `percentage` in Step 12.

5. **Reference:** [demo_projects/project1/video1/video_struct.yaml](demo_projects/project1/video1/video_struct.yaml)

6. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_video_struct.py" \
     --video-struct /abs/path/video_struct.yaml \
     --project-config /abs/path/project_config.yaml
   ```
   With `--project-config`, the script also enforces the narrative-style
   visual-scene minimums (documentary ≥ 75%, knowledge_sharing /
   news_broadcast ≥ 60%). If it fails, fix and re-validate. Do NOT proceed
   until exit 0.

---

## Step 7: TTS Synthesis + Frame Calculation

**When:** After video_struct.yaml passes validation.

**What to do:**

1. Run TTS synthesis **(run in the background — Bash `run_in_background: true`; use `--timeout 10800` (3h) for safety — TTS may take several minutes per narration and many narrations run sequentially)**:
   ```bash
   python3 "${SKILL_DIR}/scripts/tool/run_tts.py" \
     --project-config /abs/path/project_config.yaml \
     --video-struct /abs/path/video_struct.yaml \
     --timeout 10800
   ```
   - `--timeout 10800`: per-TTS subprocess timeout (3h) — never use the 1h default for this step
   - Do NOT block waiting: continue with other ready work; when the background completion
     notification arrives, check the exit status and `video_struct.yaml` updates
   This will:
   - Generate `speech.wav` for each narration (one per section)
   - Normalize each narration's loudness via ffmpeg loudnorm (`tts.loudnorm`,
     default true) to `tts.loudness_target` LUFS (default -14; higher = louder)
     so the narration is clearly audible over the mix
   - Measure audio duration via ffprobe
   - Calculate `narration.total_frame = ceil((duration + tts.pause_seconds) × fps)`
     (`tts.pause_seconds` = silence after the narration, default 0.5s — the next
     narration starts after a short pause while the visual stays continuous)
   - Update `video_struct.yaml` `narration.audio_path` (pointing to .wav) and `narration.total_frame`.
     Scene frames are derived later (Step 12) by splitting `narration.total_frame`
     across the section's scenes via `percentage`.

   **Idempotent:** re-running skips narrations whose audio already exists
   (reported as `skipped`) — safe to resume after an interruption. Pass
   `--force` to regenerate ALL audio. Use `--force` after editing any
   `narration.content`, otherwise the stale audio is kept.

2. **Validate:**
   ```bash
   python3 "${SKILL_DIR}/scripts/verify/verify_audio.py" --video-struct /abs/path/video_struct.yaml
   ```
