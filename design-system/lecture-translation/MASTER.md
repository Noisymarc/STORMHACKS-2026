# Lecture translation: interface rules

## Purpose and scope

Help a student follow an English lecture in Japanese, explain a selected phrase,
and reuse their personal glossary. This is a local hackathon demo. The interface
uses HTML, CSS and JavaScript served by FastAPI; no frontend framework is required.

These are the project's curated rules, informed by UI UX Pro Max v2.15.0.
Its first design-system query recommended Minimalism & Swiss Style, but also a
marketing hero. A narrower retry still returned marketing guidance. Those page
patterns were unsuitable and were not adopted. Layout and interaction decisions
below are specific to our working lecture flow.

## Screen structure

- Header: project title, English → Japanese direction, Start microphone and Stop.
- Status: microphone/connection state and a separate live-caption error.
- Main reading area: Japanese captions first; original English transcript below.
- Help area: help language, selected-phrase explanation, remembered help, glossary.
- At widths up to 760px, help follows the reading area; each caption pane keeps a
  bounded scrolling region. Essential text wraps instead of clipping.
- Use concise section headings and progressive disclosure for saved explanations.

## Visual tokens

| Token | Value | Purpose |
| --- | --- | --- |
| Background | `#f1f5f9` | Page canvas |
| Surface | `#ffffff` | Main workspace |
| Soft surface | `#f8fafc` | Transcript and settings |
| Text | `#0f172a` | Primary text |
| Secondary text | `#475569` | Instructions and secondary status |
| Border | `#cbd5e1` | Section boundaries |
| Accent | `#0f766e` | Primary actions and keyboard focus |
| Accent hover | `#115e59` | Pressable action emphasis |
| Highlight | `#ccfbf1` | Recognized saved terms |
| Error | `#9f1239` on `#fff1f2` | Actionable failures |

Palette derives from the Frost Bright family; semantic roles are defined once in
`frontend/live.css`. Use a 4/8/12/16/20/24/32px spacing scale, 6px button corners,
simple borders and no decorative animations or shadows.

## Typography

- Japanese-capable stack: Noto Sans JP, Yu Gothic, Hiragino Sans, sans-serif.
  Noto Sans JP was confirmed in the skill's font catalog; it is not downloaded
  at runtime. Available local fonts supply the fallback.
- Japanese captions: 24–30px, line-height 1.9; natural Japanese line breaking.
- English transcript: 18–19px, line-height 1.85.
- Interface: 16px; supporting text: 14px. Do not shrink core content to fit.
- Set Japanese output `lang="ja"`; explanation language follows the selector.
  Use automatic text direction for multilingual help, including Arabic.

## Interaction and states

- Captions remain Japanese. Help language affects explanations and saved help only.
- Each caption pane follows updates until the user scrolls back or focuses a saved
  term. Jump to live resumes following without smooth-scroll animation.
- Batch scroll/layout work with requestAnimationFrame. Caption updates do not wait
  for database search, explanation generation, or audio.
- New phrase selection remains available after stopping the microphone.
- Saved exact terms support click, hover and keyboard focus. Meaning-based results
  retain a visible Possibly related label and their saved example.
- Keep text usable when audio or database requests fail. Display each error beside
  the affected feature, with the existing retry action available.
- Audio controls appear when audio is ready. Explain is disabled during listening,
  with no selected phrase, or while a request is running.
- Do not hide an actively focused Jump to live button; hide it once focus leaves
  and following has resumed.

## Accessibility and verification

- Native buttons, labels, details and audio controls; semantic headings/landmarks.
- Visible focus, a skip link, keyboard-operable caption scroll regions, text status.
- Do not announce the entire accumulating transcript on every token. Status and
  explanation changes use live regions; captions remain available for reading.
- Standalone controls have at least 44px height. Inline saved terms retain normal
  reading rhythm and support keyboard access.
- Respect reduced motion. Check readable contrast, long text, zoom, small widths,
  reading-position stability, selection, saving and failures with sample data.
- A fixture replay verifies browser interactions only; it cannot establish Gemini
  transcription quality, translation latency, ElevenLabs pronunciation or TiDB accuracy.

## Team use

Read this file before changing the demo UI. Reuse tokens and existing control IDs;
those IDs connect the interface to microphone, explanation and glossary behavior.
Coordinate changes to `frontend/live.html` with the frontend teammate before merging.
Optional features should have working backend behavior before being presented here.
