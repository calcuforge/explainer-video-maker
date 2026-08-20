# Special Rules — Style-Specific Scene Constraints

> **When to load:** During Step 6 (design scene list), after choosing the
> expression method from `expression_intent_mapping.md`. These are hard
> constraints that override the general mapping for specific `video_style`
> values. Read `project.video_style` from project_config.yaml and apply the
> matching section below, plus the general rules that apply to every style.

These rules capture craft conventions that the generic intent→component mapping
does not express — for example, that a product intro must open on the product
itself, or that a documentary should close on a wide shot + quote. When a rule
conflicts with a cheaper default (e.g. "use a text card"), the rule wins.

---

## General rules (all styles)

1. **First scene must be a strong visual.** The opening scene of the whole
   video (first scene of the first story) must be a full-bleed visual — an
   AIGC/stock video, an AIGC/stock image, or a `KenBurnsImage`. Never open on a
   pure text/data component (QuoteBlock, FeatureGrid, DataTable, etc.).
2. **Vary consecutive components.** Do not put two identical data/text
   components back-to-back (e.g. two DataTables or two StatCounters in a row).
   Break them up with a visual scene or a different component type.
3. **Vary the first scene of each chapter.** Each story's opening scene should
   use a different component/visual approach than the previous story's opener,
   so chapters feel distinct.
4. **On-screen data fields hold data points, never sentences.** In data/text
   components (`StatCounter`, `DataBar`, `DataTable`, `IconCard`, `FeatureGrid`,
   `Timeline`, `FlowChart`), the structured fields (`value`, `suffix`, `label`,
   `title`, `headers`, `rows`, etc.) must contain **concise metrics and short
   labels** — a few words at most, no sentence punctuation (，。；！？、). The
   full narrative sentence — the complete thought the viewer hears — belongs
   ONLY in `narration.content`. Never fracture one sentence across a big number
   and a label field; that renders as a number floating above a broken
   half-sentence (the #1 cause of "incoherent data" displays).
   - ✓ StatCounter → `value: 30`, `suffix: "天"`, `label: "搜救时长"`; and
     `narration.content: "最初的几轮搜索一无所获，黑匣子的信号在三十天后才出现。"`
   - ✗ StatCounter → `value: 30`, `suffix: "天"`, `label: "最初的几轮搜索一无所获，黑匣子的信号也在"` (narration leaked into the label).
   `verify_remotion_data` (validate-remotion-data.mjs) rejects sentence
   punctuation in these fields, so a leak fails the gate.
5. **A number inside a sentence ≠ a StatCounter scene.** Do not pick
   `StatCounter`/`DataBar` just because the narration contains a number. Use
   them only when the **metric itself is the point of the scene** (the
   narration is essentially "X reached N" / "N people …"). If the number is
   incidental to a story sentence (e.g. "the signal returned after 30 days"),
   make it a visual scene (`KenBurnsImage`/`AssetVideo`/`AssetImage`) and keep
   the whole sentence as narration.

---

## Content type balance (scene mix)

Every scene falls into one of two buckets:

- **Visual scenes** — scenes that actually SHOW an image/video asset
  (`AssetImage`, `AssetVideo`, `KenBurnsImage`, `MediaSection`), AIGC or stock.
  They show, set mood, and carry cinematic weight.
- **Data/text scenes** — structured components (`QuoteBlock`, `FeatureGrid`,
  `IconCard`, `ComparisonCard`, `StatCounter`, `DataBar`, `Timeline`,
  `FlowChart`, `CodeBlock`, `DataTable`, `DiagramReveal`, `AnimationDemo`,
  `StatHighlight`, `MetricsRow`, `ProgressRing`, `StepProgress`, `SplitLayout`,
  `ZigzagCards`, `KeywordCloud`, `MapPins`, `AudioWaveform`). They explain,
  quantify, and organize information.

Narrative styles are **footage-led**: visuals must be the majority of ALL
scenes, data/text scenes are accents. The minimum is **hard-enforced** by
`verify_video_struct.py` (Step 6 gate) for the narrative styles below; use the
band as the planning target for the whole video:

| Style | Visual scenes (min, enforced) | Target band | Character |
|-------|-----------------------------:|-------------|-----------|
| documentary | **≥ 75%** | 75–85% | Show, don't tell — footage-led, data as seasoning |
| knowledge_sharing | **≥ 60%** | 60–80% | Concepts shown over footage; diagrams only for truly structural content |
| news_broadcast | **≥ 60%** | 60–85% | Footage-led reporting; stats as accents |

A lopsided video (e.g. a documentary that is 80% text cards) feels off-genre
and FAILS the Step 6 gate. Default every narration to a visual scene
(see expression_intent_mapping.md "Visual-First Principle"); convert to a
data/text scene only when the narration's point IS the text/data.

---

## documentary (纪录片)

1. **Favor cinematic visuals.** Establishing shots, era/atmosphere scenes, and
   the closing scene should be video or `KenBurnsImage`; avoid stacking static
   `AssetImage` scenes.
2. **Close on a wide shot + quote.** The final scene should be a cinematic
   visual (video or KenBurnsImage) or a `QuoteBlock` summarizing the theme.
3. **Content balance: ≥ 75% visual (enforced by `verify_video_struct.py`).**
   Footage (video + KenBurnsImage) is the body of a documentary; use data/text
   components only as occasional accents (a key StatCounter, a closing
   QuoteBlock). Avoid consecutive data/text scenes.

## knowledge_sharing (知识分享)

1. **Open by stating what the viewer will learn.** The first scene should set
   up the concept with a visual (an image/video of the subject), not jump
   straight into dense data.
2. **Visual-first: ≥ 60% visual scenes (enforced).** Show the concept over
   footage (`AssetVideo`, `KenBurnsImage`, `AssetImage`, `MediaSection`) by
   default — narrate the explanation over the visual. Keep `DiagramReveal`,
   `FlowChart`, `FeatureGrid`, and `AnimationDemo` ONLY for content that is
   inherently structural (an architecture, a pipeline, a mechanism the viewer
   must study).

## news_broadcast (新闻播报)

1. **Open with a headline feel.** The first scene should establish the event —
   a `video`/image of the subject, or a bold `QuoteBlock`/title framing the
   story.
2. **Footage-led: ≥ 60% visual scenes (enforced).** Recreate the event and its
   context with video/images; use `StatCounter`, `DataBar`, and `DataTable`
   sparingly as accents for the key numbers, and keep claims tied to data.

## product_intro (产品介绍)

1. **First scene showcases the product.** The opening scene MUST show the
   product's appearance — an `AssetImage` or `KenBurnsImage` (pan to reveal
   details) of the product, not a text card.
2. **Selling points via structured components.** Use `FeatureGrid` /
   `IconCard` for features and `ComparisonCard` for positioning against
   alternatives.

## data_report (数据报告)

1. **Open with the key metric or trend.** The first scene should present the
   headline number/trend (`StatCounter` or `DataBar`) or a visual that frames
   the dataset — not unrelated atmosphere.
2. **Every number needs a component.** Present figures with `StatCounter`,
   `DataBar`, or `DataTable` rather than embedding raw numbers in narration-only
   scenes.

## tutorial (教程)

1. **Open with the goal or end result.** The first scene should show what the
   viewer will build/achieve (a visual or a framing card).
2. **Steps are sequential.** Present procedures with `FlowChart` and show code
   with `CodeBlock`; keep step order explicit.
