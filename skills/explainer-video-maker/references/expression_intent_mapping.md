# AI Narration Video Production: Expression Intent Mapping

## Visual-First Principle (narrative styles)

**In `documentary`, `knowledge_sharing` and `news_broadcast` videos, the DEFAULT
expression method for every narration is a VISUAL scene** — an AIGC/stock image
(`AssetImage` / `KenBurnsImage`) or video (`AssetVideo`), or a `MediaSection`
image grid. The intent tables below are per-intent component picks, but their
text/data rows are FALLBACKS — use them only when the narration's point is
inherently textual/data and no image or footage can carry it.

**Balance target (enforced, Step 6 gate):** visual scenes must be the majority
of ALL scenes — `documentary` ≥ 75%, `knowledge_sharing` / `news_broadcast`
≥ 60% (verified by `verify_video_struct.py`; see special-rules.md).

**Decision checklist for each scene — before picking a data/text component, ask
"能换成画面吗？":**

1. **Does the narration describe something you could SEE?** An event, a person,
   a place, an era, a product, a change, an atmosphere, a scene → SHOW it:
   `AssetVideo` (dynamic), `KenBurnsImage` (cinematic still), `AssetImage`,
   or stock media for generic visuals. When the narration has 2+ ideas, give
   each idea its own visual scene (split by `percentage`).
2. **Is the narration essentially "X 达到 N" / "N 个…" (the metric IS the
   point)?** → `StatCounter` / `StatHighlight` / `DataBar` (or keep the metric
   INSIDE a visual scene's caption/text when it is secondary).
3. **Is it a spoken quote or judgment?** → `QuoteBlock` — the one text component
   that is a legitimate documentary accent. Use sparingly (1-2 per video).
4. **Is it a process, structure, or comparison the viewer must study?**
   (knowledge/tutorial styles) → `FlowChart` / `DiagramReveal` / `FeatureGrid` /
   `ComparisonCard`. For documentary/news, still prefer footage: narrate the
   process OVER a visual scene instead of drawing a diagram.
5. **Only a timeline of facts with no visual hook?** → convert to a `MediaSection`
   of 2-4 era/example images (with `caption`s) or a sequence of visual scenes —
   NOT a bare `Timeline`/`IconCard`/`DataTable` for narrative styles.

**Common overused text intents → visual alternatives:**

| Text intent (avoid for narrative styles) | Visual alternative |
|---|---|
| Show historical stages / evolution (`Timeline`) | 3-4 era images in `MediaSection`, or one visual scene per stage |
| Summarize achievements / key points (`IconCard`, `FeatureGrid`) | `MediaSection` images with captions; achievements narrated over footage |
| Highlight a metric (`StatCounter`, `StatHighlight`) | Visual scene of the subject; keep the number in `narration.content` or as a `MediaSection` stat row |
| Show rankings / specifications (`DataTable`) | `MediaSection` images of the ranked items |
| Emphasize key terms (`KeywordCloud`) | Visual scene representing the term |
| Show categories (`FeatureGrid`) | `MediaSection` with one image per category |

---

## Choosing AssetImage vs KenBurnsImage vs AssetVideo

When a scene uses a text-to-image workflow (or any static image), choose the Remotion component based on the Expression Intent:

| Intent | Component | Rationale |
|--------|-----------|-----------|
| Image is primary visual, needs cinematic feel | **KenBurnsImage** | Slow zoom/pan adds engagement without video cost |
| Image is background/atmosphere only | **KenBurnsImage** (or AssetImage) | Subtle motion enriches the backdrop |
| Heavy text/data overlay on top of image | **AssetImage** | Static image avoids distracting motion behind text |
| Image is informational (diagram, chart, screenshot) | **AssetImage** | Ken Burns motion adds no value to data |
| Quick scene, short duration | **AssetImage** | Motion may not be noticeable in very short scenes |
| Portrait / character introduction | **KenBurnsImage** (zoom="in") | Cinematic zoom draws focus to the subject |
| Product showcase, detail scanning | **KenBurnsImage** (with pan) | Pan reveals different product areas over time |

### Stock media (asset_generation_method: stock)

Stock media (searched from Pexels / Pixabay / Unsplash) is an alternative to
AIGC for **generic, non-specific** visuals. It is controlled by two switches in
`project_config.yaml` → `stock_media` and documented in **separate files that
you load only when the matching switch is on**:

- **Stock images** (`search_image: true`) → [stock_image_mapping.md](stock_image_mapping.md)
- **Stock video** (`search_video: true`, default **false**) → [stock_video_mapping.md](stock_video_mapping.md)

If a switch is off, do not use that stock type — fall back to the AIGC rows in
the tables below.

---

## Choosing MediaSection (multi-image + text + data)

`MediaSection` renders **one scene with multiple images** (grid), plus an
optional description line above and a stat row below. Use it when a single
visual cannot carry the content — several parallel examples, screenshots, or
cases that share one narration.

| Expression Intent | Example | Component | Reason |
|---|---|---|---|
| Multi-case showcase | 3 application scenarios of AI | **MediaSection** | A grid shows cases in parallel; one narration covers them all. |
| Product screenshots / UI series | Login, main page, settings | **MediaSection** | Multiple screenshots are clearer side by side than a single image. |
| Series of images + metric | 3 milestones + total count | **MediaSection** (text + data) | Images carry the cases, the stat row carries the number. |
| Before / after pairs | Two states of the same subject | **MediaSection** (2 items) | A 2-column grid reads naturally as a comparison. |

Keep single-image intents on the single-image components:

- One representative image → **AssetImage** / **KenBurnsImage** (see table above)
- Video material → **AssetVideo** (never put videos in `media_list` — the grid
  renders images only)

### Scene authoring rules (Step 6)

```yaml
- intent: 多案例展示
  id: scene3a
  percentage: 100
  remotion_component: MediaSection
  is_aigc_scene: true            # true if ANY media item uses aigc
  text: 'AI 落地三大场景'          # description above the grid
  data: '[{"value":"3","label":"落地场景","suffix":"个"}]'   # stat row below
  media_list:
  - id: scene3a-1                # convention: <scene_id>-<n>; aigc items are
    visual_content: 'AI 医疗影像'  # referenced as task scene_id in video_tasks
    caption: '医疗影像'            # optional per-image caption
    type: image                  # image only
    asset_generation_method: stock   # stock | aigc
    workflows: []                # required for aigc items
  - id: scene3a-2
    visual_content: 'AI 自动驾驶'
    asset_generation_method: stock
```

- `media_list` items are **image-only**; aigc items need their own `workflows`
  and become **per-item tasks** in `video_tasks.yaml` (`scene_id: scene3a-1`),
  each with its own `video_prompt_{item_id}.yaml`.
- `data` is the stat row (`value`/`label`/`suffix` — labels ≤10 chars), NOT a
  QuoteBlock-style JSON object; `text` is the plain description.
- Item asset paths are auto-filled by the pipeline (stock search → upscale →
  compress), same as single-image scenes.

---

## 1. Narrative / Atmosphere

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Establish a scene | 1950s New York street | text-to-video | AssetVideo | Dynamic environments are more immersive than static images. |
| Recreate historical scenes | Ancient Egyptian pyramid construction | text-to-video | AssetVideo | Historical events require dynamic visual reconstruction. |
| Create emotional atmosphere | A city under tension before war | text-to-video | AssetVideo | Motion, lighting, and camera movement enhance emotional impact. |
| Express abstract concepts | Artificial intelligence is changing the world | text-to-image → image-to-video | AssetVideo | Abstract ideas benefit from symbolic imagery and subtle animation. |
| Visualize future scenarios | A smart city in 2050 | text-to-image → image-to-video | AssetVideo | Future concepts require creative generation with cinematic motion. |
| Express era transitions | Agricultural age to industrial age | text-to-video | AssetVideo | Long-term evolution is best represented through animated scenes. |
| Show before-and-after changes | City before and after renovation | image-edit → first-last-frame-to-video | AssetVideo | Explicit start and end states make transition animation natural. |
| Express memories | Childhood rural life | text-to-video | AssetVideo | Video better conveys nostalgia and emotional storytelling. |
| Voice/audio emphasis | Podcast-style voice segment | - | AudioWaveform | The visible spectrum reacts to the narration — the voice itself becomes the visual. |
| Geographic narrative | Where the AI hubs are | - | MapPins | Schematic pulsing pins place the story on a map without stock footage. |

---

## 2. Character / People

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Introduce a person | Who is Steve Jobs | text-to-image | AssetImage | A portrait provides the clearest visual introduction. |
| Introduce a person (cinematic) | Who is Steve Jobs | text-to-image | KenBurnsImage | Slow zoom-in on portrait creates a dramatic, documentary feel. |
| Show personal journey | From startup failure to success | - | Timeline | Personal growth is naturally represented chronologically. |
| Present a quotation | "Innovation comes from different ideas." | - | QuoteBlock | Quotes deserve visual emphasis and attribution. |
| Summarize achievements | Three major contributions | - | IconCard | Key achievements are easy to scan as individual cards. |
| Compare two people | Steve Jobs vs Bill Gates | - | ComparisonCard | Side-by-side comparison highlights differences clearly. |
| Show relationship network | Collaboration between scientists | - | DiagramReveal | Network diagrams effectively visualize relationships. |

---

## 3. Concept Explanation

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Define a concept | What is quantum computing? | text-to-image | AssetImage | A representative illustration quickly establishes context. |
| Show key features | Three advantages of AI | - | FeatureGrid | Feature grids organize parallel information effectively. |
| Highlight key points | Five renewable energy trends | - | IconCard | Bullet-style cards improve readability. |
| Show system structure | Components of a computer | - | DiagramReveal | Structural relationships are best shown as diagrams. |
| Explain a mechanism | How an engine works | - | AnimationDemo | Animated demonstrations simplify complex mechanisms. |
| Show a workflow | AI model training pipeline | - | FlowChart | Sequential processes are naturally represented as flowcharts. |
| Show categories | Types of AI | - | FeatureGrid | Categories are easy to compare in a grid layout. |
| Show hierarchy | Internet technology architecture | - | DiagramReveal | Hierarchical structures benefit from node diagrams. |
| Emphasize key terms | 深度学习核心名词 | - | KeywordCloud | Floating weighted chips focus attention on the terms themselves. |
| Text + visual side-by-side | Principle + product photo | text-to-image (or stock) | SplitLayout | Explanation on one side, image/icon list on the other — no full-bleed needed. |

---

## 4. Data / Facts

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Highlight a metric | 1 billion users | - | StatCounter | Animated counters emphasize important numbers. |
| Show growth trend | Market grew by 300% | - | DataBar | Animated bars make trends immediately visible. |
| Show rankings | Top 5 brands | - | DataTable | Rankings are easiest to read in tabular form. |
| Show specifications | CPU / RAM / Battery | - | DataTable | Technical parameters require structured presentation. |
| Show proportions | Energy mix | - | DataBar | Relative values are easy to compare visually. |
| Highlight statistics | 95% customer satisfaction | - | StatCounter | Large animated numbers attract attention. |
| Show yearly evolution | Company history over 20 years | - | Timeline | Time-based data belongs on a timeline. |
| Hero metric (whole scene) | 1 billion users | - | StatHighlight | One number owns the entire scene — maximum impact for the single most important metric. |
| Multiple KPIs | 3 key performance indicators | - | MetricsRow | Dashboard-style cards compare several numbers in one scene. |
| Completion / share rate | 85% adoption, 60% penetration | - | ProgressRing | The animated donut arc reads a 0-100% quantity better than a bar. |

---

## 5. News

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Recreate a news event | Rocket launch | text-to-video | AssetVideo | Dynamic footage increases realism. |
| Introduce background | Historical context | text-to-image | AssetImage | Background information usually requires only a representative image. |
| Introduce background (cinematic) | Historical context | text-to-image | KenBurnsImage | Slow zoom out reveals the wider context; pan moves across a scene. |
| Show event timeline | Development of the incident | - | Timeline | News events naturally follow chronological order. |
| Explain impact | Impact on supply chain | - | FlowChart | Cause-and-effect relationships are clearly visualized. |
| Present expert opinions | Expert quotes | - | QuoteBlock | Quotations highlight authority and credibility. |
| Show statistics | GDP growth | - | DataBar | Quantitative information is best shown visually. |

---

## 6. Product Introduction

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Showcase appearance | Smartphone design | text-to-image | AssetImage | Static product images clearly display appearance. |
| Scan product details | Smartphone design, detail view | text-to-image | KenBurnsImage | Ken Burns pan slowly reveals different product areas. |
| Showcase dynamically | 360° product rotation | text-to-image → image-to-video | AssetVideo | Motion better demonstrates product design. |
| Present selling points | Three core features | - | FeatureGrid | Features are easy to compare side by side. |
| List functions | Fast charging, waterproof | - | IconCard | Icon-based cards improve readability. |
| Compare products | iPhone vs Android | - | ComparisonCard | Comparison layouts simplify decision making. |
| Explain technology | Chip architecture | - | AnimationDemo | Animation clarifies technical principles. |
| Show user workflow | Product setup process | - | FlowChart | Step-by-step guidance fits a workflow diagram. |

---

## 7. Tutorials / Education

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Demonstrate steps | Register an account | - | FlowChart | Procedures are naturally sequential. |
| Demonstrate an experiment | Volcano simulation | - | AnimationDemo | Animation effectively illustrates dynamic processes. |
| Show source code | Python example | - | CodeBlock | Preserves syntax and readability. |
| Explain an algorithm | Machine learning workflow | - | FlowChart | Algorithms are process-oriented. |
| Show architecture | Cloud computing architecture | - | DiagramReveal | Architecture is best communicated visually. |
| Summarize knowledge | Three key takeaways | - | IconCard | Summary cards improve retention. |
| Step-by-step progression | 3 stages of a process | - | StepProgress | The active-step highlight shows "where we are now" in a sequence. |

---

## 8. Software Engineering

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Display code | REST API example | - | CodeBlock | Source code requires monospace formatting. |
| Show execution | Program execution | - | AnimationDemo | Execution flow is easier to understand dynamically. |
| Show architecture | Microservices | - | DiagramReveal | Node diagrams communicate architecture clearly. |
| Explain API flow | Request lifecycle | - | FlowChart | API interactions follow a sequential flow. |
| Show version history | Software evolution | - | Timeline | Version changes are chronological. |
| Highlight performance | 10× QPS improvement | - | StatCounter | Key metrics deserve numerical emphasis. |

---

## 9. Opinion / Commentary

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Highlight an opinion | The future belongs to AI | - | QuoteBlock | Important statements should stand out visually. |
| Summarize trends | Three future trends | - | IconCard | Trends are easy to digest as key points. |
| Compare viewpoints | Pros vs Cons | - | ComparisonCard | Contrasting ideas are clearer side by side. |
| Explain reasoning | Why renewable energy matters | - | FlowChart | Logical reasoning follows a causal flow. |
| Support with data | User growth statistics | - | DataBar | Data strengthens arguments visually. |
| Alternating points | Pros and cons list | - | ZigzagCards | Left/right alternating cards scan better than a uniform grid for contrasting points. |

---

## 10. History / Timeline

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Show historical stages | 30 years of the Internet | - | Timeline | Historical progression is inherently chronological. |
| Show product evolution | iPhone generations | - | Timeline | Product iterations are timeline-based. |
| Show technology evolution | Semiconductor roadmap | - | Timeline | Technology development unfolds over time. |
| Show transformation | Building renovation | image-edit → first-last-frame-to-video | AssetVideo | Transformation is best shown through animated transitions. |

---

## 11. Relationships / Structure

| Expression Intent | Example | Workflow Type | Remotion Component | Reason |
|---|---|---|---|---|
| Show organization | Company structure | - | DiagramReveal | Organizational hierarchies are graph structures. |
| Show industry chain | Automotive supply chain | - | FlowChart | Supply chains follow directional flows. |
| Show ecosystem | AI ecosystem | - | DiagramReveal | Ecosystems contain interconnected entities. |
| Show causality | Causes of an economic crisis | - | FlowChart | Cause-and-effect relationships are sequential. |
| Show decision path | Customer purchase journey | - | FlowChart | Decision making follows a stepwise process. |
---

## New component quick reference (added 2026-08-04)

| Component | Best intent | Key remotion_data fields |
|---|---|---|
| StatHighlight | One metric owns the whole scene | `value`, `unit`, `label`, `description?`, `icon?` |
| MetricsRow | Compare 2-4 KPIs in one scene | `title?`, `items[{value, label, suffix?, icon?}]` |
| ProgressRing | 0-100% rate / share / adoption | `value`, `suffix?`, `unit?`, `label`, `size?` |
| StepProgress | Sequential stages, "where we are now" | `title?`, `steps[{label, description?}]`, `activeStep?` |
| SplitLayout | Text + image/icon list side-by-side | `title`, `description?`, `rightImage?` (auto from asset_path), `rightCaption?`, `rightItems?`, `accent?` |
| ZigzagCards | Feature list / pros-cons / short sequences | `title?`, `items[{icon?, title, description?}]` |
| KeywordCloud | Term/concept emphasis (names, keywords) | `title?`, `keywords[{text, weight? 1-3}]` |
| MapPins | Geographic narrative (abstract, no real borders) | `title?`, `pins[{label, x, y (0-100), description?}]`, `lines?[{from, to}]` |
| AudioWaveform | Voice/audio emphasis; reacts to narration | `audioSrc` (required — narration wav or http), `mode?` bars/wave/dots, `position?` bottom/top/inline, `barCount?`, `height?`, `opacity?` |

**Usage decisions:**
- `SplitLayout` right side: set `rightItems` in `data` for an icon list (no asset needed), or leave `rightItems` empty and let the scene's `asset_path` auto-inject `rightImage` (single stock/AIGC image).
- `AudioWaveform.audioSrc` points at the narration WAV (e.g. `stories/{story_id}/{narration_id}/speech.wav`, relative to the video dir) or any http URL. `barCount` must be a power of 2.
- `MapPins` x/y are percent coordinates (0-100) of the schematic grid — place pins freely; `lines` connects pins by index with dashed arcs.
- All 9 components are theme-aware and vertical-safe (9:16 stacks/condenses automatically).
