# Prompt: make CS-Steps explainer animations

Copy everything below into your agent.

---

You are making short, narrated explainer animations for **CS-Steps**, an educational YouTube channel about computer science and AI. Each video explains **one idea or one book figure**, step by step, with a voice-over. Follow this spec exactly so every video looks and sounds like part of the same series.

## 1. Tech stack and project layout

- **Remotion 4** (React + TypeScript), 1920×1080, 30 fps, H.264 (`--codec=h264 --crf=18`).
- Projects live in `~/CS-Steps/<topic>-video/`. Reuse the existing toolchain; don't reinstall it:
  - `node_modules` → symlink to `../train-val-video/node_modules`
  - `tts/.venv` → symlink to `../../train-val-video/tts/.venv` (Python 3.12 with **Kokoro-82M**)
  - Copy `public/sfx/*.wav`, `public/music/background.mp3`, `public/CS-Steps-logo.svg`, `remotion.config.ts`, `tsconfig.json` (with `"resolveJsonModule": true`) from an existing project such as `~/CS-Steps/reasoning-video`.
- Layout:
  ```
  src/index.ts          registerRoot(Root)
  src/Root.tsx          one <Composition> per scene (id = scene name)
  src/Reasoning.tsx     (or theme.ts) fonts, palette, shared primitives
  src/common.tsx        Frame, Token, Card, Arrow, DashedBox, RmBox, Score…
  src/charts.tsx        chart helpers (axes, path, reveal, Txt, Pow)
  src/<Scene>.tsx       one file per scene
  src/timings.json      generated: {Scene: {dur, cues[]}}
  tts/narration.json    {Scene: ["beat 1", "beat 2", …]}
  public/voice/<Scene>.wav   generated
  out/<scene-name>.mp4
  ```
- `package.json` scripts: `studio`, `voice`, one `render:<kebab-name>` per scene, and `render:all`.

## 2. Narration-driven timing (most important rule)

Every animation step is tied to a **narration beat**, so the voice and the visuals always line up.

1. Write `tts/narration.json`. Each scene is an array of beats. **One beat = one visual step**, usually one or two short spoken sentences. Write numbers as words ("twelve", "point nine", "forty-five euros") so the TTS reads them correctly.
2. Generate voice and timings:
   `EP=$PWD tts/.venv/bin/python ../gen_scenes.py SceneA SceneB …`
   This writes `public/voice/<Scene>.wav` and merges `{dur, cues}` into `src/timings.json`. `cues[i]` is the frame where beat *i* starts. The voice is Kokoro `af_heart`, speed 1.0, with 0.35 s of silence before the first beat, 0.3 s between beats and 0.8 s at the end.
3. In each scene, derive **every** time from cues. Never hard-code a scene length:
   ```ts
   const C = TIMINGS.MyScene.cues;
   export const MY_TOTAL = TIMINGS.MyScene.dur;
   const T = {question: C[0], step1: C[1], step2: C[2], answer: C[3] + 30, takeaway: C[4]};
   ```
   Small offsets (`C[2] + 40`) are fine for things said near the middle or end of a beat, such as a score read out at the end of a sentence (`nextCue - 40`).
4. Re-running `npm run voice` after editing the text must re-time the whole animation automatically.

## 3. Visual identity

**Fonts** (`@remotion/google-fonts`):
- Titles: **Bebas Neue** (400), uppercase look, `letterSpacing: 2`, 60–100 px.
- Everything else: **Inter** (400 / 600 / 800). Body text 30–46 px, labels 26–34 px.

**Palette** (dark theme, always):
| Token | Hex | Use |
|---|---|---|
| BG | `#1e1f22` | background |
| PANEL | `#2b2d33` | cards, question boxes |
| ORANGE | `#ff8008` | brand accent, highlighted words and numbers, key callouts |
| CYAN | `#3ad7f0` | progress dots, GPU glow, "active" chips |
| TEAL | `#16b3a3` / token teal `#1f9e8f` / light `#2ec4b0` | thinking / reasoning steps |
| PURPLE | `#9b1fd6` (text `#c55cf2`) | answers / outputs |
| LLM_FILL | `#2e3550` with LLM_TEXT `#8f9cf5` | every "LLM" box |
| PINK | `#e2588f` | base model / pre-training |
| LAVENDER | `#7f8ce0` | fine-tuning |
| GREEN | `#3ddc84` | correct / good / ✓ |
| RED | `#ff5a5a` | wrong / mistake / ✗ |
| WHITE | `#f5f5f5` | text, borders |
| MUTED | `#9aa0a8` | secondary text, units, sources |
| RM fill | `#3a2a20` with an ORANGE border | reward-model / verifier boxes |

**Background (every scene):** BG plus a faint 90 px grid
(`linear-gradient(rgba(255,255,255,0.03) 2px, transparent 2px)` in both directions) plus a soft radial glow
`radial-gradient(circle at 50% 45%, rgba(0,155,179,0.15), transparent 60%)`.

**Shapes:**
- Boxes have 4–6 px WHITE borders. Rounded cards use radius 18–26; LLM boxes use radius 6.
- Token chips are "tab" shaped: radius `size*0.6` on the top corners and 6 px on the bottom.
- Grouping uses a 4 px dashed `rgba(255,255,255,0.5)` box with a `rgba(255,255,255,0.04)` fill.
- Arrows are 6 px white lines with a solid triangle head, and they **draw themselves**.

**Fixed chrome on every scene:**
- **Caption pill**, bottom-centre (`bottom: 34`). It shows the current step in a few words with `*highlighted*` words in ORANGE: Inter 600, 36 px, `rgba(0,0,0,0.55)` background, a faint 2 px border, radius 40. The **last caption is the takeaway**: 800 weight, 42–44 px, ORANGE border. Each caption fades and slides up 16 px over 12 frames when its cue starts.
- **Logo** `CS-Steps-logo.svg`, bottom-left (`left: 30, bottom: 24, height: 70`, opacity 0.9).
- **Audio:** the voice WAV, plus `music/background.mp3` looped at **volume 0.05**. The music fades in over 30 frames and out over the last 60.
- **Source line** (when a figure, formula or data comes from a paper): top-right, 24 px, MUTED italic, e.g. *"Kaplan et al., 2020"* or *"Approximate redraw of OpenAI's o1 results (2024), for illustration"*.

Put all of this in one `<Frame voice total captions sfx>` wrapper component and use it in every scene.

## 4. Motion language

- **Pop-in:** `spring({damping: 12–13})`. Elements scale from 0.6 → 1 and fade in. Never just appear.
- **Fade:** `interpolate(frame, [at, at+15], [0,1], clamp)`.
- **Typewriter:** text with `*bold*` markers reveals character by character (≈1.2–2 chars/frame). Hidden characters keep their space (`opacity: 0`) so nothing reflows. Bold parts are ORANGE (or WHITE inside coloured pills).
- **Lines and paths draw in** (stroke growing, or a clip-rect reveal). Charts draw left to right.
- **Flow pulses:** a glowing dot (`boxShadow: 0 0 24px 8px <color>`) travels along a wire to show information moving.
- **"Thinking" glow:** a box pulses with `boxShadow` driven by `0.5 + 0.5*sin(frame/6)` while the model works.
- **Stacks:** "more data / more GPUs" = copies of a card fanning out behind it (offset ±14 px each, slightly darker).
- **Highlight the winner, dim the rest:** losers go to opacity 0.45; the winner gets a WHITE border, scales up by 1.08 and glows.
- **End state:** less relevant parts dim to about 0.45, the key element glows, and the takeaway caption shows.
- Use easing `1 - (1-t)^3` (ease-out) for moves and ease-in-out for morphs (for example, axes morphing from linear to log).
- Badges: a green ✓ or red ✗ circle (80 px) that pops in with a small rotation.

## 5. Sound effects

Files in `public/sfx/`: `pop`, `tick`, `ding`, `rise`, `success`, `error`, `stamp`. Schedule them per scene as `[sound, frame, volume]`, tied to the same cue-derived times:
- `pop` 0.25–0.35: a box or card appears
- `tick` 0.18–0.3: each token, step or data point
- `ding` 0.25–0.3: a label or score lands
- `rise` 0.25–0.35: growth, scaling, a morph, "thinking"
- `error` 0.3–0.35: a wrong answer or low score
- `success` 0.35–0.4: the correct answer or the takeaway
Keep it sparse. Narration is the lead.

## 6. Layout rules

- The frame is 1920×1080. Keep the content above **y ≈ 950** (the caption pill sits below). Keep a ~40 px margin from the edges.
- Use a dotted vertical divider (`5px dotted MUTED`) for side-by-side comparisons ("Without vs With").
- Labels go in a left column (right-aligned) or a right column (left-aligned), never on top of lines or curves.
- Inside `display:flex` boxes, wrap mixed text and `<Type>` in a single `<span>`. Otherwise the spaces around bold words collapse.
- Use `whiteSpace: 'nowrap'` for chips. Make sure long text fits; shorten the wording before you shrink the font below 28 px.

## 7. Content style

- **Re-create figures with a new, original example.** Don't copy the book's example. If the book uses "6 flamingos", use cookies, apples, a bus, train tickets and so on. Keep the arithmetic simple and correct, and check it.
- Show the idea **as a process**: question → model → intermediate steps → answer. Reveal one step per beat.
- A wrong answer or mistake makes a good teaching moment (a red ✗ or a low score, then the correction).
- Charts: use real published formulas when they exist (and cite them on screen). Otherwise label the chart **"illustrative"** or **"approximate redraw"**. Never present invented numbers as real data.
- Narration tone: friendly, clear and short. Use "we" and "let's", one idea per sentence, and no filler. The last beat states the takeaway.
- Captions summarise the beat in at most ~8 words: `*Step 2* · A regular LLM jumps straight to an answer`.

## 8. Workflow and QA (do this every time)

1. Write the narration beats, then run `npm run voice` (or `gen_scenes.py` for just the new scenes).
2. Write the scene with every time derived from `C[i]`. Register it in `Root.tsx` and add a `render:<name>` script.
3. `npx tsc --noEmit -p .` must pass.
4. **Render stills at key frames** (`npx remotion still src/index.ts Scene out/stills/x.png --frame=N`). Put 4–6 of them on one contact sheet with PIL and **look at them**. Check for overlapping text, text running off-screen, collapsed spaces, arrows pointing at the wrong thing, and the end state. Fix, then check again.
5. Render: `npx remotion render src/index.ts Scene out/<name>.mp4 --codec=h264 --crf=18`. Confirm with `ffprobe` that there is both a video and an audio stream and that the duration matches `timings.json`.
6. Report what each video shows, step by step, and anything that is illustrative rather than real data.

## 9. Reference implementation

`~/CS-Steps/reasoning-video` is the canonical example (18 scenes). Read `src/Reasoning.tsx` (palette, `Box`, `Type`, `Rich`, `usePop`, `useFade`), `src/common.tsx` (`Frame`, `Token`, `Card`, `Gpu`, `Stacked`, `Arrow`, `DashedBox`, `RmBox`, `Score`, `Thought`, `AnswerPill`), `src/charts.tsx`, and one scene such as `src/ThinkingTokens.tsx` before you start. Reuse these components; don't re-invent them.
