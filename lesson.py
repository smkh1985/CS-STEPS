#!/usr/bin/env python3
"""Record a narrated VS Code lesson from a lesson folder, in any language.

A lesson folder holds:
    lesson.yaml         the steps: who speaks and what happens on screen (language-independent),
                        plus optional starting `files` and `setup` commands for the workspace
    scenes.py           optional Manim scenes, shown instead of the screen on steps with `scene:`
                        (or, with `layout: split`, on the right half next to the code)
    lang/<lang>.yaml    the words for each step in one language, plus voices and TTS settings

Recording a language writes everything into output/<lang>/:
    video.mp4           screen recording with narration
    narration.wav       the narration track on its own
    timing.json         when each step starts in the video and how long its narration is
    transcript.json     every spoken line with speaker, start and end time
    subtitles.srt       subtitles for YouTube or any player
    chapters.txt        YouTube chapters, ready to paste into the description

The screen actions wait for each line's narration, so every language gets a video that
fits its own speech. Narration clips are cached in <lesson>/cache/tts, so re-runs and
small edits only pay for lines that changed.

Usage:
    .venv/bin/python lesson.py lessons/lesson1                # English (lang/en.yaml)
    .venv/bin/python lesson.py lessons/lesson1 --lang de      # lang/de.yaml
    .venv/bin/python lesson.py lessons/lesson1 --remix        # new audio, same video
    .venv/bin/python lesson.py lessons/lesson1 --export       # only redo transcript/subtitles/chapters
    .venv/bin/python lesson.py lessons/lesson2 --check-sync   # before recording: will the voice cover the typing?
    .venv/bin/python lesson.py lessons/lesson2 --speech       # generate the voice, then the same check, exactly
    .venv/bin/python lesson.py lessons/lesson2 --dry-run      # check the screen actions, no narration
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

from record import Recording, check_requirements, focus, run, vscode_recording, xdotool_key

ROOT = Path(__file__).resolve().parent
SAMPLE_RATE = 24000  # Kokoro's native rate; ElevenLabs is asked for the same

# Click targets as (x, y) inside the VS Code window. They depend only on VS Code's
# default layout (activity bar and a 300px-wide sidebar), not on the window size.
TARGETS = {
    "explorer": (26, 56),
    "new_file": (256, 82),
    "first_file": (110, 106),  # entries inside the folder in the explorer (alphabetical)
    "second_file": (110, 128),
    "editor": (900, 600),
    "terminal": (1000, 900),  # inside the terminal panel once it's open
    "run_menu": (247, 17),  # Run in the menu bar (needs window.menuBarVisibility: visible)
    # the first item of the Run menu: move straight down onto it first (run_menu_down), since
    # gliding across the menu bar while a menu is open switches to the menu under the pointer
    "run_menu_down": (247, 45),
    "start_debugging": (310, 45),
    "add_watch": (279, 473),  # the + on the Watch header in Run and Debug (shows on hover)
    "corner": (1915, 1075),  # bottom-right corner, to park the pointer out of the way
}

# Editor lines for `line: N` clicks: the middle of line 1, the line spacing (editor.fontSize 20
# gives VS Code's default 27px line height) and an x right of any code, so a click lands at
# the end of the line.
EDITOR_FIRST_LINE_Y = 104
EDITOR_LINE_HEIGHT = 27
EDITOR_LINE_END_X = 1280  # left of the checklist panel, so the pointer stays visible
EDITOR_LINE_START_X = 446  # just inside the first character (code starts at x=443), for selections
EDITOR_CODE_X = 443  # where column 0 starts; `line: N:C` clicks at column C
EDITOR_CHAR_WIDTH = 12  # JetBrains Mono at editor.fontSize 20 (0.6 em per character)
SPLIT_CROP_X = 350  # `layout: split`: the left half shows the screen from here (the line numbers on),
                    # 960 px wide: the code and terminal up to column 72, at full size

ELEVENLABS_VOICES = {  # premade voices available to the API key; lang files may also use raw IDs
    "brian": "nPczCjzI2devNBz1zQrb", "adam": "pNInz6obpgDQGcFmaJgB", "daniel": "onwK4e9ZLuTAKqWW03F9",
    "rachel": "21m00Tcm4TlvDq8ikWAM", "sarah": "EXAVITQu4vr4xnSDxMaL", "alice": "Xb7hH8MSUJpSbSDYk0k2",
    "laura": "FGY2WhTYpPnrIDTdsKH5", "charlotte": "XB0fDUnXU5powFXDhCwa", "matilda": "XrExE9yKIg1WjnnlVkGX",
    "jessica": "cgSgspJ2msm6clMCkdW9", "lily": "pFZP5JQG7iQjIQuC4Bku", "dorothy": "ThT5KcBeYPX3keUQqHPh",
    "grace": "oWAxZDx7w5VEj9dCyTzz", "serena": "pMsXgVXv3BLzUgSXRplE", "domi": "AZnzlk1XvdvUeBnXmlld",
    "freya": "jsCqWAovK2LkecY7zXl4", "nicole": "piTKgcLEGmPE4e6mEKli", "emily": "LcfcDJNUP1GQjkzn1xUU",
    "mimi": "zrHiDhphv9ZnVXBqCLjz", "glinda": "z9fAnlkpzviPz146aGWa",
}

# YouTube only shows chapters if these rules hold.
MIN_CHAPTERS = 3
MIN_CHAPTER_SECONDS = 10


@dataclass
class Step:
    id: str
    speaker: str | None = None  # "teacher" | "student"; None for silent actions
    actions: list[tuple[str, object]] = field(default_factory=list)
    text: str = ""  # what was said, as written (subtitles, transcript)
    say: str = ""  # what the voice reads (symbols spelled out)
    chapter: str | None = None  # starts a YouTube chapter with this title
    show: dict | None = None  # an on-screen card shown while this line is spoken (see render_cards)
    scene: str | None = None  # Manim scene shown instead of the screen during this step (see render_scenes)
    layout: str | None = None  # "split": the scene takes the right half, the code stays on the left
    checklist: str | None = None  # show this checklist from this step on ("none" hides it; see render_checklists)
    checklist_at: float = 0.0  # where in the line the checklist appears (0 = start, 0.5 = halfway)
    type_speed: float = 1.0  # this step types faster (2.0 = twice as fast), e.g. for repetitive code
    check: list[int] = field(default_factory=list)  # tick these checklist items (1-based) when this step starts
    zoom: str | None = None  # magnify a ZOOMS region from this step on ("none" ends it; see render_zooms)


@dataclass
class Language:
    code: str
    name: str
    tts: str
    model: str
    voices: dict[str, str]
    kokoro_lang: str
    scene_text: dict[str, str] = field(default_factory=dict)  # translated labels for Manim scenes
    checklists: dict[str, dict] = field(default_factory=dict)  # name -> {title, items}
    voice_settings: dict = field(default_factory=dict)  # ElevenLabs, e.g. {stability: 0.0}


def load_lesson(lesson_dir: Path, lang: str) -> tuple[list[Step], Language, dict]:
    lesson = yaml.safe_load((lesson_dir / "lesson.yaml").read_text())
    lang_file = lesson_dir / "lang" / f"{lang}.yaml"
    if not lang_file.exists():
        sys.exit(f"No language file {lang_file}")
    words = yaml.safe_load(lang_file.read_text())
    lines = words.get("lines") or {}

    steps, problems = [], []
    for raw in lesson["steps"]:
        actions = []
        for action in raw.get("actions", []):
            (kind, arg), = action.items()
            if kind in ("click", "move"):
                if isinstance(arg, str) and (m := re.fullmatch(r"file (\d+)", arg)):
                    # the Nth entry inside the folder in the explorer (alphabetical, 22px rows)
                    actions.append((kind, (110, 106 + 22 * (int(m.group(1)) - 1))))
                    continue
                if arg not in TARGETS:
                    problems.append(f"{raw['id']}: unknown target {arg!r} (known: {', '.join(TARGETS)})")
                    continue
                arg = TARGETS[arg]
            actions.append((kind, arg))
        check = raw.get("check") or []
        step = Step(raw["id"], raw.get("speaker"), actions, scene=raw.get("scene"), layout=raw.get("layout"),
                    checklist=raw.get("checklist"),
                    checklist_at=float(raw.get("checklist_at", 0.0)),
                    type_speed=float(raw.get("type_speed", 1.0)), zoom=raw.get("zoom"),
                    check=[check] if isinstance(check, int) else list(check))
        if step.layout not in (None, "split"):
            problems.append(f"{step.id}: unknown layout {step.layout!r} (known: split)")
        elif step.layout and not step.scene:
            problems.append(f"{step.id}: layout: {step.layout} needs a scene")
        if step.speaker:
            line = lines.get(step.id)
            if not line or not line.get("text"):
                problems.append(f"{step.id}: no text in {lang_file.name}")
                continue
            step.text = line["text"]
            step.say = line.get("say") or step.text
            step.chapter = line.get("chapter")
            step.show = line.get("show")
            cues = line.get("cues") or []
            for k, (kind, arg) in enumerate(step.actions):
                if kind != "at":
                    continue
                if not isinstance(arg, int) or not 1 <= arg <= len(cues):
                    problems.append(f"{step.id}: at: {arg} but its line has {len(cues)} cue(s) in {lang_file.name}")
                elif cues[arg - 1] not in step.say:
                    problems.append(f"{step.id}: cue {cues[arg - 1]!r} isn't in its `say` text in {lang_file.name}")
                else:
                    step.actions[k] = ("at", step.say.index(cues[arg - 1]) / len(step.say))
        elif any(kind == "at" for kind, _ in step.actions):
            problems.append(f"{step.id}: at: needs a speaker and a line with `cues:`")
        steps.append(step)
    ids = [s["id"] for s in lesson["steps"]]
    if len(set(ids)) != len(ids):
        problems.append("lesson.yaml has duplicate step ids")
    problems += [f"{sid}: in {lang_file.name} but not in lesson.yaml" for sid in lines if sid not in ids]
    problems += [f"{s.id}: card shown until unknown step {s.show['until']!r}" for s in steps
                 if s.show and s.show.get("until") and s.show["until"] not in ids]
    checklists = words.get("checklists") or {}
    # A YAML line ending in ":" (like "- Rewrite it with ? :") is read as a mapping, not text,
    # and would only fail at the very end of a recording, while drawing the panel: catch it now.
    for name, spec in checklists.items():
        for item in [spec.get("title")] + list(spec.get("items") or []):
            if not isinstance(item, str):
                problems.append(f"checklist {name!r}: {item!r} isn't text; put it in quotes in {lang_file.name}")
    for s in steps:
        for line in (s.show or {}).get("lines") or []:
            if not isinstance(line, str):
                problems.append(f"{s.id}: card line {line!r} isn't text; put it in quotes in {lang_file.name}")
    active = None
    for s in steps:
        if s.checklist:
            active = None if s.checklist == "none" else s.checklist
            if active and active not in checklists:
                problems.append(f"{s.id}: checklist {active!r} isn't under `checklists:` in {lang_file.name}")
                active = None
        for item in s.check:
            if not active:
                problems.append(f"{s.id}: check: {item} but no checklist is showing")
            elif active in checklists and not 1 <= item <= len(checklists[active]["items"]):
                problems.append(f"{s.id}: checklist {active!r} has no item {item}")
    if problems:
        sys.exit("Lesson problems:\n  " + "\n  ".join(problems))

    language = Language(lang, words.get("language", lang), words.get("tts", "elevenlabs"),
                        words.get("model", "eleven_multilingual_v2"), words["voices"],
                        words.get("kokoro_lang", "a"), words.get("scenes") or {}, checklists,
                        words.get("voice_settings") or {})
    if any(s.scene for s in steps) and not (lesson_dir / "scenes.py").exists():
        sys.exit(f"lesson.yaml uses `scene:` but {lesson_dir / 'scenes.py'} doesn't exist")
    workspace = {"files": lesson.get("files") or {}, "setup": lesson.get("setup") or [],
                 "settings": lesson.get("vscode_settings") or {},
                 "extensions": lesson.get("vscode_extensions") or [],
                 "keybindings": lesson.get("vscode_keybindings") or []}
    return steps, language, workspace


# --- Narration -----------------------------------------------------------------------

def elevenlabs_key() -> str:
    if key := os.environ.get("ELEVENLABS_API_KEY"):
        return key
    for name in ("env", ".env"):
        path = ROOT / name
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip().startswith("ELEVENLABS_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit(f"Set ELEVENLABS_API_KEY or put ELEVENLABS_API_KEY=... in {ROOT / 'env'}")


def elevenlabs_context(model: str) -> bool:
    """Whether the model takes neighbouring lines (previous_text/next_text); eleven_v3 doesn't."""
    return not model.startswith("eleven_v3")


def elevenlabs_tts(key: str, voice: str, model: str, speed: float, settings: dict,
                   text: str, previous_text: str, next_text: str) -> np.ndarray:
    voice_id = ELEVENLABS_VOICES.get(voice.lower(), voice)
    body = {"text": text, "model_id": model}
    if elevenlabs_context(model):
        body.update(previous_text=previous_text, next_text=next_text)
    settings = {**settings, **({"speed": speed} if speed != 1.0 else {})}
    if settings:
        body["voice_settings"] = settings
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_{SAMPLE_RATE}",
        data=json.dumps(body).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    try:
        pcm = urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs error {e.code}: {e.read().decode()[:300]}")
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768


def make_tts(language: Language, voice: str, speed: float):
    if language.tts == "elevenlabs":
        key = elevenlabs_key()
        return lambda text, prev, nxt: elevenlabs_tts(key, voice, language.model, speed,
                                                      language.voice_settings, text, prev, nxt)

    from kokoro import KPipeline  # slow import; only when actually synthesizing

    pipeline = KPipeline(lang_code=language.kokoro_lang, repo_id="hexgrad/Kokoro-82M")
    return lambda text, prev, nxt: np.concatenate(
        [r.audio.numpy() for r in pipeline(text, voice=voice, speed=speed)])


CHARS_PER_SECOND = 12.2  # the teacher's eleven_v3 voice, measured on lesson 7 v2


def narration_lengths(steps: list[Step], language: Language, speed: float, cache: Path) -> list[float]:
    """Seconds of narration per step, without calling ElevenLabs: the cached clip when there is
    one, otherwise an estimate from the text's length (marked by a negative number)."""
    lengths = []
    for step in steps:
        if not step.speaker:
            lengths.append(0.0)
            continue
        path = cache / (tts_cache_key(steps, step, language, speed) + ".npy")
        lengths.append(len(np.load(path)) / SAMPLE_RATE if path.exists() else -len(step.say) / CHARS_PER_SECOND)
    return lengths


def sync_report(steps: list[Step], action_times: list[float], lengths: list[float], tolerance: float = 1.5,
                estimated: bool = False) -> None:
    """After a dry run, or before recording with estimated action times (--check-sync): list the
    steps whose screen actions outlast their narration, i.e. where the video would go quiet while
    something happens on screen."""
    quiet = []
    for step, acted, spoken in zip(steps, action_times, lengths):
        silence = acted - abs(spoken)
        if silence > tolerance:
            quiet.append((step.id, acted, abs(spoken), silence, spoken < 0))
    if not quiet:
        print("Sync: the narration covers every action (no silence longer than %.1fs)." % tolerance)
        return
    print("Sync: these steps go quiet while the screen keeps changing (actions longer than the narration"
          + (", actions estimated):" if estimated else "):"))
    for step_id, acted, spoken, silence, estimated in quiet:
        note = " (narration estimated)" if estimated else ""
        print(f"  {step_id:6} actions {acted:5.1f}s  narration {spoken:4.1f}s{note}  -> {silence:4.1f}s of silence")
    print(f"  Total: {sum(q[3] for q in quiet):.0f}s. Split long typing over more lines, or say more while it happens.")


# How long screen actions take, without running them (see estimate_action_times). Checked on
# 2026-10-30 against the real recordings of lessons 17-20 (the steps whose actions outlasted
# the voice, from timing.json): within about 10%, and on the long side.
XDOTOOL_CALL = 0.025   # seconds per xdotool call while ffmpeg is recording
TYPING_FACTOR = 1.0


def estimate_typing(text: str, delay_ms: int, typo_rate: float) -> float:
    """The expected time type_like_a_person() takes for `text` (its pauses, typos and hesitations)."""
    lognormal_mean = math.exp(0.35 ** 2 / 2)
    seconds = 0.0
    for token in re.findall(r"[A-Za-z0-9_]+|.", text, re.S):
        if len(token) > 1 or token.isalnum() or token == "_":
            seconds += 2 * XDOTOOL_CALL + (len(token) * 0.6 * delay_ms + delay_ms * lognormal_mean) / 1000
            letters = sum(ch.isalpha() and ch.lower() in NEIGHBOURS for ch in token)
            seconds += letters * typo_rate * (4.9 * delay_ms / 1000 + 4 * XDOTOOL_CALL)
        else:
            pause = 0.84 * delay_ms * lognormal_mean
            if token in SHIFTED:
                pause *= 1.4
            if token == " ":
                pause *= 1.5
            if token in ";{}" or token == "\n":
                pause *= 2.75
            seconds += max(pause / 1000, 2 * XDOTOOL_CALL)
        seconds += 0.03 * 4.25 * delay_ms / 1000  # the odd hesitation
    return TYPING_FACTOR * seconds


def estimate_action_times(steps: list[Step], type_delay: int, mouse_time: float, typo_rate: float,
                          lengths: list[float] | None = None, late: list | None = None) -> list[float]:
    """Seconds each step's actions take, as perform() would run them: for checking the sync
    before recording (--check-sync). `scroll` is a guess; the rest follows perform(). With the
    narration `lengths`, `at` waits for its cue, and cues the actions reach more than 0.7s after
    the voice says them are added to `late` as (step id, seconds late)."""
    def glide(duration: float) -> float:
        return duration + (int(duration / 0.015) + 1) * XDOTOOL_CALL

    snap = 0.4 + 3 * XDOTOOL_CALL  # editor_line_y() snapping the view to whole lines
    times, in_editor = [], True
    for i, step in enumerate(steps):
        seconds = 0.0
        length = abs(lengths[i]) if lengths else 0.0
        delay = aligned_delay(step, type_delay, mouse_time, typo_rate, length) if lengths else \
            round(type_delay / step.type_speed)
        for kind, arg in step.actions:
            if kind == "move":
                seconds += glide(mouse_time)
            elif kind == "click":
                seconds += glide(mouse_time) + 0.45 + 2 * XDOTOOL_CALL
                in_editor = arg in (TARGETS["editor"], TARGETS["new_file"])
            elif kind == "type":
                seconds += estimate_typing(arg, delay, typo_rate if in_editor else 0.0)
            elif kind == "key":
                seconds += len(arg.split()) * (0.12 + 2 * XDOTOOL_CALL) + 0.2
                in_editor = in_editor and "ctrl+grave" not in arg.split()
            elif kind == "line":
                seconds += snap + glide(mouse_time) + 0.45 + 2 * XDOTOOL_CALL
                in_editor = True
            elif kind == "select":
                first, last = (int(n) for n in str(arg).split("-")) if "-" in str(arg) else (int(arg),) * 2
                seconds += 2 * snap + glide(mouse_time) + glide(max(mouse_time, 0.25 + 0.04 * (last - first)))
                seconds += 0.45 + 3 * XDOTOOL_CALL
                in_editor = True
            elif kind == "scroll":
                seconds += 0.9
            elif kind == "wait":
                seconds += float(arg)
            elif kind == "at":
                if late is not None and seconds - arg * length > 0.7:
                    late.append((step.id, seconds - arg * length))
                seconds = max(seconds, arg * length)
        times.append(seconds)
    return times


TYPING_FILL = 0.85  # typing ends this far into the step's narration, so code appears as it's described
MAX_SLOWDOWN = 2.5  # at most this much slower than --type-delay (85 ms -> 212 ms a character)


def aligned_delay(step: Step, type_delay: int, mouse_time: float, typo_rate: float, length: float) -> int:
    """The ms between characters for `step`, stretched so its typing spans its narration instead of
    racing ahead of the voice. Steps with `at` cues are already aligned and keep their speed."""
    delay = round(type_delay / step.type_speed)
    if length <= 0 or any(kind == "at" for kind, _ in step.actions) \
            or not any(kind == "type" for kind, _ in step.actions):
        return delay
    once, twice = (estimate_action_times([replace(step, type_speed=type_delay / d)], type_delay, mouse_time,
                                         typo_rate)[0] for d in (delay, 2 * delay))
    typing = twice - once  # the part that grows with the delay
    other = once - typing
    if typing <= 0:
        return delay
    factor = (TYPING_FILL * length - other) / typing
    return round(delay * min(MAX_SLOWDOWN, max(1.0, factor)))


def narration_context(steps: list[Step], step: Step) -> tuple[str, str]:
    """The lines spoken just before and after `step` (previous_text, next_text)."""
    spoken = [s for s in steps if s.speaker]
    j = spoken.index(step)
    return " ".join(s.say for s in spoken[max(0, j - 2):j]), spoken[j + 1].say if j + 1 < len(spoken) else ""


def tts_cache_key(steps: list[Step], step: Step, language: Language, speed: float) -> str:
    """The cache file name of a step's narration."""
    previous_text, next_text = narration_context(steps, step)
    model = language.model if language.tts == "elevenlabs" else language.kokoro_lang
    ident = [language.tts, language.voices[step.speaker], model, speed, step.say]
    if language.tts == "elevenlabs" and elevenlabs_context(language.model):
        ident += [previous_text, next_text]
    if language.tts == "elevenlabs" and language.voice_settings:  # only then, so old caches stay valid
        ident += [language.voice_settings]
    return hashlib.sha256(json.dumps(ident).encode()).hexdigest()[:20]


def synthesize(steps: list[Step], language: Language, speed: float, cache: Path) -> list[np.ndarray]:
    """Return one audio clip per step (empty for silent steps). Clips are cached on disk,
    so re-runs, and edits to other lines, don't regenerate (or pay for) unchanged ones."""
    cache.mkdir(parents=True, exist_ok=True)
    tts = {}  # one synthesizer per voice
    clips = []
    for step in steps:
        if not step.speaker:
            clips.append(np.zeros(0, dtype=np.float32))
            continue
        # Neighbouring lines let ElevenLabs keep intonation continuous between clips.
        previous_text, next_text = narration_context(steps, step)
        voice = language.voices[step.speaker]
        path = cache / (tts_cache_key(steps, step, language, speed) + ".npy")
        if path.exists():
            audio = np.load(path)
            source = "cached"
        else:
            if voice not in tts:
                tts[voice] = make_tts(language, voice, speed)
            audio = tts[voice](step.say, previous_text, next_text)
            np.save(path, audio)
            source = language.tts
        print(f"  {step.id} ({step.speaker}): {len(audio) / SAMPLE_RATE:.1f}s ({source})", flush=True)
        clips.append(audio)
    return clips


def normalize_loudness(clips: list[np.ndarray], target_lufs: float) -> list[np.ndarray]:
    """Bring every clip to the same perceived loudness (ITU BS.1770), so both voices
    and all lines sound equally loud. Peaks are kept below full scale."""
    import pyloudnorm as pyln

    meter = pyln.Meter(SAMPLE_RATE)
    out = []
    for clip in clips:
        # The meter needs at least one 400 ms block; pad very short clips for measuring only.
        padded = np.pad(clip, (0, max(0, SAMPLE_RATE // 2 - len(clip))))
        loudness = meter.integrated_loudness(padded) if len(clip) else float("-inf")
        if not np.isfinite(loudness):
            out.append(clip)
            continue
        gain = 10 ** ((target_lufs - loudness) / 20)
        peak = np.abs(clip).max() * gain
        if peak > 0.95:
            gain *= 0.95 / peak
        out.append((clip * gain).astype(np.float32))
    return out


def fade_edges(clip: np.ndarray, ms: float = 20) -> np.ndarray:
    """Fade a clip in and out over a few milliseconds so it doesn't start or stop with a click."""
    n = min(int(SAMPLE_RATE * ms / 1000), len(clip) // 2)
    if n == 0:
        return clip
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))).astype(np.float32)
    clip = clip.copy()
    clip[:n] *= ramp
    clip[-n:] *= ramp[::-1]
    return clip


def room_tone(samples: int, level_db: float, seed: int = 1) -> np.ndarray:
    """Very quiet pink noise, like the air of a room, so the gaps between lines aren't dead silence."""
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.standard_normal(samples))
    freqs = np.fft.rfftfreq(samples, 1 / SAMPLE_RATE)
    spectrum[1:] /= np.sqrt(freqs[1:])  # pink: equal energy per octave
    spectrum[freqs < 40] = 0  # no rumble
    noise = np.fft.irfft(spectrum, samples)
    noise *= 10 ** (level_db / 20) / np.sqrt(np.mean(noise ** 2))
    return noise.astype(np.float32)


def build_track(clips: list[np.ndarray], offsets: list[float], total_seconds: float,
                room_tone_db: float | None) -> np.ndarray:
    starts = [round(o * SAMPLE_RATE) for o in offsets]
    length = max([round(total_seconds * SAMPLE_RATE)] + [s + len(c) for s, c in zip(starts, clips)])
    track = room_tone(length, room_tone_db) if room_tone_db is not None else np.zeros(length, np.float32)
    for start, clip in zip(starts, clips):
        track[start:start + len(clip)] += fade_edges(clip)
    return track


CARD_FONT_SIZE = 34
CARD_BG = "0x252526@0.96"
CARD_BORDER = "0x3794ff"
CARD_TEXT = "0xe6e6e6"
CARD_ACCENT = "0x4fc1ff"
CARD_ERROR = "0xf14c4c"
CHECKLIST_Y = 100
CHECKLIST_MARGIN = 30  # from the right edge; the panel must stay right of the code (x 1300+)
CHECK_BOX = "0x8b949e"
CHECK_DONE = "0x3fb950"
CHECK_DONE_TEXT = "0x8b949e"
CHECK_GLYPH_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # Inter has no ✓


def card_font() -> str:
    # NL ("no ligatures") first: otherwise != and >= are drawn as single symbols like ≠ and ≥
    for pattern in ("JetBrainsMonoNL Nerd Font:style=Regular", "JetBrains Mono NL:style=Regular",
                    "JetBrainsMono Nerd Font:style=Regular", "JetBrains Mono:style=Regular", "monospace"):
        path = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout
        if path:
            return path
    sys.exit("No font found for on-screen cards (fc-match)")


def checklist_font(style: str) -> str:
    for pattern in (f"Inter:style={style}", f"DejaVu Sans:style={'Bold' if style == 'Bold' else 'Book'}"):
        path = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout
        if path:
            return path
    sys.exit("No font found for the checklist (fc-match)")


def render_checklists(steps: list[Step], timing: dict, language: Language, card_dir: Path,
                      last: str) -> tuple[list[str], str, list[tuple[float, float, int]]]:
    """Build filter chains that draw the plan for the current program in a panel on the right.

    lesson.yaml:  checklist: login   shows lang's checklists.login from this step until the next
                                     `checklist:` (another name, or none) or the end of the video
                  check: 2           ticks item 2 when this step starts (or a list: [1, 2])
    lang/<lang>.yaml:  checklists: {login: {title: LOGIN PROGRAM, items: [...]}}

    The items appear one by one across the narration of the step that shows the list, as the
    teacher reads out the plan. While a Manim scene (`scene:`) is on screen the panel is hidden,
    and it comes back afterwards with its ticks. Returns the chains, the final label and
    (start, end, bottom y) of each panel, so cards can be drawn below it instead of on top of it.
    """
    from PIL import ImageFont

    card_dir.mkdir(parents=True, exist_ok=True)
    regular, bold, mono = checklist_font("Regular"), checklist_font("Bold"), card_font()
    size, title_size, line_h, pad, box = 26, 28, 48, 28, 26
    measure = ImageFont.truetype(regular, size)

    # Panels: [show step, ticks as (item, time), end time, step it (re)appears on], each lasting
    # until the next `checklist:`. A scene pauses the panel; it resumes on the next screen step.
    panels, current, paused = [], None, None
    for s in steps:
        if s.checklist:
            if current:
                current[2] = timing["steps"][s.id]["start"]
            current, paused = None, None
            if s.checklist != "none":
                current = [s, [], timing["video_duration"], s]
                panels.append(current)
        if s.scene and current:
            current[2] = timing["steps"][s.id]["start"]
            current, paused = None, current
        elif not s.scene and paused:
            current = [paused[0], list(paused[1]), timing["video_duration"], s]
            panels.append(current)
            paused = None
        # ticks during a scene (e.g. typing beside a split scene) show when the panel comes back
        if current or paused:
            (current or paused)[1].extend((item, timing["steps"][s.id]["start"] + 0.2) for item in s.check)

    chains, bounds = [], []
    for n, (shown, ticks, end, appears) in enumerate(panels):
        spec = language.checklists[shown.checklist]
        items = spec["items"]
        t = timing["steps"][appears.id]
        # `checklist_at` delays the panel to the part of the line that reads out the plan
        delay = t["duration"] * shown.checklist_at if appears is shown else 0.0
        start = t["start"] + 0.15 + delay
        dur = max(end - start, 0.6)
        # items appear one by one while the plan is read out (0 on a silent step: all at once);
        # a panel coming back after a scene shows everything straight away
        reveal = (t["duration"] - delay) * 0.85 / len(items) if appears is shown else 0
        ticked = {item: at - start for item, at in ticks}

        title_w = ImageFont.truetype(mono, title_size).getlength(spec["title"])
        w = int(max(max(measure.getlength(i) for i in items) + box + 18, title_w)) + 2 * pad
        title_y = pad - 4
        list_y = title_y + title_size + 26
        h = list_y + len(items) * line_h + pad - (line_h - box)

        def text(name, value, x, y, enable, font, fsize, color):
            path = card_dir / f"k{n}_{name}.txt"
            path.write_text(value)
            return (f"drawtext=fontfile='{font}':textfile='{path}':expansion=none:fontsize={fsize}"
                    f":fontcolor={color}:x={x}:y={y}:enable='{enable}'")

        draw = [f"drawbox=x=0:y=0:w={w}:h={h}:color={CARD_BORDER}:t=3",
                text("title", spec["title"], pad, title_y, "1", mono, title_size, CARD_ACCENT),
                f"drawbox=x={pad}:y={list_y - 14}:w={w - 2 * pad}:h=1:color=0x3c3c3c:t=fill"]
        for i, item in enumerate(items, 1):
            y = list_y + (i - 1) * line_h
            shown_at = 0.3 + (i - 1) * reveal
            done = ticked.get(i)
            appear = f"gte(t,{shown_at:.3f})"
            pending = f"between(t,{shown_at:.3f},{done:.3f})" if done is not None else appear
            draw.append(f"drawbox=x={pad}:y={y}:w={box}:h={box}:color={CHECK_BOX}:t=2:enable='{pending}'")
            draw.append(text(f"i{i}", item, pad + box + 18, y - 2, pending, regular, size, CARD_TEXT))
            if done is not None:
                after = f"gte(t,{max(done, shown_at):.3f})"
                draw.append(f"drawbox=x={pad}:y={y}:w={box}:h={box}:color={CHECK_DONE}:t=fill:enable='{after}'")
                draw.append(text(f"v{i}", "✓", pad + 4, y - 1, after, CHECK_GLYPH_FONT, size, "0x1e1e1e"))
                draw.append(text(f"d{i}", item, pad + box + 18, y - 2, after, regular, size, CHECK_DONE_TEXT))
        fade = min(0.3, dur / 4)
        chains.append(
            f"color=c={CARD_BG}:s={w}x{h}:d={dur:.3f},format=rgba," + ",".join(draw)
            + f",fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={dur - fade:.3f}:d={fade}:alpha=1"
            + f",setpts=PTS-STARTPTS+{start:.3f}/TB[list{n}]")
        chains.append(f"[{last}][list{n}]overlay=x=main_w-overlay_w-{CHECKLIST_MARGIN}:y={CHECKLIST_Y}"
                      f":eof_action=pass:enable='between(t,{start:.3f},{start + dur:.3f})'[k{n}]")
        last = f"k{n}"
        bounds.append((start, start + dur, CHECKLIST_Y + h))
    return chains, last, bounds


# Screen regions a step can magnify with `zoom:` (x, y, width, height inside the VS Code window,
# default layout), and where the enlarged copy goes: (scale, x, y), over a part of the screen that
# is empty in that situation.
ZOOMS = {
    # Run and Debug's Watch section (header and the first three or four watches); shown enlarged
    # in the editor's empty right half, below the checklist and above the terminal
    "watch": ((55, 462, 290, 112), 2.0, 1302, 482),
}


def render_zooms(steps: list[Step], timing: dict, last: str) -> tuple[list[str], str]:
    """Build filter chains for `zoom: NAME` in lesson.yaml: from that step until the next `zoom:`
    (another name, or none) the ZOOMS region is shown enlarged in a framed box, e.g. the Watch
    section, whose small sidebar text is hard to read in a video. Keep it off scene steps."""
    spans, current = [], None
    for s in steps:
        if s.zoom:
            if current:
                current[2] = timing["steps"][s.id]["start"]
            current = None
            if s.zoom != "none":
                if s.zoom not in ZOOMS:
                    sys.exit(f"{s.id}: unknown zoom {s.zoom!r} (known: {', '.join(ZOOMS)})")
                current = [s.zoom, timing["steps"][s.id]["start"], timing["video_duration"]]
                spans.append(current)
    chains = []
    for n, (name, start, end) in enumerate(spans):
        (x, y, w, h), scale, to_x, to_y = ZOOMS[name]
        chains.append(f"[{last}]split[zm{n}][zs{n}]")
        chains.append(f"[zs{n}]crop={w}:{h}:{x}:{y},scale={round(w * scale)}:{round(h * scale)}:flags=lanczos,"
                      f"pad=iw+8:ih+8:4:4:color=0x3794ff[zb{n}]")
        chains.append(f"[zm{n}][zb{n}]overlay={to_x}:{to_y}:enable='between(t,{start:.3f},{end:.3f})'[zo{n}]")
        last = f"zo{n}"
    return chains, last


def render_cards(steps: list[Step], timing: dict, card_dir: Path, last: str = "0:v",
                 panels: list[tuple[float, float, int]] = ()) -> tuple[list[str], str]:
    """Build ffmpeg filter-graph chains that draw each step's `show` card over the video
    ([0:v] in, returns the final label). A card appears when its line starts and stays until
    the line's narration ends, or until the step named in `until` starts.

    show: {lines: [...], reveal: seconds}   text card; with `reveal`, lines appear one by one
    show: {lines: [...], error: true}        the same, framed in red (e.g. a compiler error)
    show: {lines: [...], code: true}         lines left-aligned, so indentation shows (a code snippet)
    show: {rectangle: {width: "5", height: "3", sum: "5 + 3 + 5 + 3 = 16"}}
          a rectangle whose edges light up one after another, then the sum

    While a checklist panel is showing (`panels`), the card goes right below it.
    """
    card_dir.mkdir(parents=True, exist_ok=True)
    font = card_font()
    chains = []

    def text(name: str, value: str, x: str, y: str, enable: str = "1", size: int = CARD_FONT_SIZE,
             color: str = CARD_TEXT) -> str:
        path = card_dir / f"{name}.txt"  # textfile= avoids escaping quotes and colons in drawtext
        path.write_text(value)
        # expansion=none: drawtext otherwise reads % as the start of a code, and drops the text
        return (f"drawtext=fontfile='{font}':textfile='{path}':expansion=none:fontsize={size}:fontcolor={color}"
                f":x={x}:y={y}:enable='{enable}'")

    for n, step in enumerate(s for s in steps if s.show):
        t = timing["steps"][step.id]
        start = t["start"] + 0.15
        until = step.show.get("until")
        end = timing["steps"][until]["start"] if until else t["start"] + t["duration"] + 0.3
        dur = max(end - start, 0.6)
        draw = []
        if "rectangle" in step.show:
            r = step.show["rectangle"]
            w, h = 640, 470
            rx, ry, rw, rh, e = 140, 110, 360, 220, 7
            draw.append(f"drawbox=x={rx}:y={ry}:w={rw}:h={rh}:color=0x6e7681:t=3")
            edges = [(rx, ry, rw, e), (rx, ry + rh - e, rw, e), (rx, ry, e, rh), (rx + rw - e, ry, e, rh)]
            for k, (x, y, bw, bh) in enumerate(edges):  # top & bottom (width), then left & right (height)
                draw.append(f"drawbox=x={x}:y={y}:w={bw}:h={bh}:color={CARD_ACCENT}:t=fill"
                            f":enable='gte(t,{1.2 + 0.7 * k})'")
            draw += [
                text(f"c{n}_w1", r["width"], f"{rx + rw // 2}-text_w/2", f"{ry - 52}"),
                text(f"c{n}_w2", r["width"], f"{rx + rw // 2}-text_w/2", f"{ry + rh + 16}"),
                text(f"c{n}_h1", r["height"], f"{rx - 40}-text_w/2", f"{ry + rh // 2}-text_h/2"),
                text(f"c{n}_h2", r["height"], f"{rx + rw + 40}-text_w/2", f"{ry + rh // 2}-text_h/2"),
            ]
            if r.get("sum"):
                draw.append(text(f"c{n}_sum", r["sum"], "(w-text_w)/2", f"{h - 70}",
                                 enable="gte(t,4.4)", color=CARD_ACCENT))
        else:
            lines = step.show["lines"]
            reveal = step.show.get("reveal")
            pad_x, pad_y, line_h = 52, 36, int(CARD_FONT_SIZE * 1.55)
            w = int(max(len(line) for line in lines) * CARD_FONT_SIZE * 0.6) + 2 * pad_x
            h = len(lines) * line_h + 2 * pad_y - (line_h - CARD_FONT_SIZE)
            for i, line in enumerate(lines):
                enable = f"gte(t,{0.3 + i * reveal})" if reveal else "1"
                color = CARD_ACCENT if reveal and i == len(lines) - 1 else CARD_TEXT
                x = str(pad_x) if step.show.get("code") else "(w-text_w)/2"
                draw.append(text(f"c{n}_l{i}", line, x, f"{pad_y + i * line_h}", enable, color=color))
        border = CARD_ERROR if step.show.get("error") else CARD_BORDER  # error: true -> red frame
        draw = [f"drawbox=x=0:y=0:w={w}:h={h}:color={border}:t=3"] + draw
        fade = min(0.25, dur / 4)
        chains.append(
            # drawbox/drawtext don't touch alpha, so start from the (opaque) card background
            f"color=c={CARD_BG}:s={w}x{h}:d={dur:.3f},format=rgba," + ",".join(draw)
            + f",fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={dur - fade:.3f}:d={fade}:alpha=1"
            + f",setpts=PTS-STARTPTS+{start:.3f}/TB[card{n}]")
        below = next((bottom for p_start, p_end, bottom in panels if p_start <= start < p_end), None)
        x, y = (f"main_w-overlay_w-{CHECKLIST_MARGIN}", below + 24) if below else ("main_w-overlay_w-60", 150)
        chains.append(f"[{last}][card{n}]overlay=x={x}:y={y}:eof_action=pass"
                      f":enable='between(t,{start:.3f},{start + dur:.3f})'[v{n}]")
        last = f"v{n}"
    return chains, last


def render_scenes(steps: list[Step], timing: dict, language: Language, lesson_dir: Path, work_dir: Path,
                  size: tuple[int, int], video: Path) -> tuple[list[str], str, list]:
    """Render the Manim scenes and build filter chains that cross-fade them over the screen
    recording ([0:v] in; extra inputs start at 2, after the narration). Consecutive steps with
    the same `scene` form one segment, which lasts until the next step without it starts; the
    scene gets every line's timing within the segment so it can animate along with the words."""
    segments, i = [], 0
    while i < len(steps):
        if not steps[i].scene:
            i += 1
            continue
        j = i
        while j < len(steps) and steps[j].scene == steps[i].scene and steps[j].layout == steps[i].layout:
            j += 1
        segments.append((steps[i].scene, steps[i:j], steps[j].id if j < len(steps) else None))
        i = j

    work_dir.mkdir(parents=True, exist_ok=True)
    t = timing["steps"]
    chains, inputs, last = [], [], "0:v"
    for k, (name, segment, next_id) in enumerate(segments):
        start = t[segment[0].id]["start"] - 0.15
        if start < 1.0 or segment[0] is steps[0]:  # the video opens on this scene: cover the very first frames too
            start = 0.0
        end = t[next_id]["start"] if next_id else timing["video_duration"]
        data = work_dir / f"{k}_{name}.json"
        data.write_text(json.dumps({
            "beats": {s.id: {"start": t[s.id]["start"] - start, "end": t[s.id]["start"] + t[s.id]["duration"] - start}
                      for s in segment},
            "text": language.scene_text,
            "duration": end - start,
        }))
        split = segment[0].layout == "split"
        width = size[0] // 2 if split else size[0]  # a split scene is rendered for the right half
        print(f"  rendering scene {name} ({end - start:.1f}s{', split' if split else ''})...", flush=True)
        media = work_dir / "media"
        subprocess.run(
            [sys.executable, "-m", "manim", "render", "--resolution", f"{width},{size[1]}", "--fps", "30",
             "--disable_caching", "--progress_bar", "none", "--media_dir", str(media), "-o", f"{k}_{name}",
             str(lesson_dir / "scenes.py"), name],
            env={**os.environ, "LESSON_SCENE_DATA": str(data)}, check=True, stdout=subprocess.DEVNULL,
        )
        inputs.append(next(media.rglob(f"{k}_{name}.mp4")))
        fade = 0.35
        fade_in = f"fade=t=in:st=0:d={fade}:alpha=1," if start > 0 else ""  # a video that opens on a scene starts on it
        fades = f"{fade_in}fade=t=out:st={end - start - fade:.3f}:d={fade}:alpha=1,setpts=PTS-STARTPTS+{start:.3f}/TB"
        if split:
            # The left half is the live screen (from the line numbers on), so typing goes on beside
            # the scene. It slides left into place while the scene fades in on the right, and back
            # at the end: at the edges of the slide it matches the full screen underneath exactly.
            # The screen is read again from the scene's start (a split + trim of [0:v] would hold
            # every frame before the scene in memory, and ffmpeg runs out of it).
            length = end - start
            slide = f"{SPLIT_CROP_X}*min(1,min(t/{fade},({length:.3f}-t)/{fade}))" if start > 0 else \
                f"{SPLIT_CROP_X}*min(1,({length:.3f}-t)/{fade})"
            chains.append(f"[{1 + len(inputs)}:v]scale={width}:{size[1]},format=rgba,"
                          f"{fades.split(',setpts')[0]}[sr{k}]")
            inputs.append((["-ss", f"{start:.3f}", "-t", f"{length:.3f}"], video))
            chains.append(f"[{1 + len(inputs)}:v]setpts=PTS-STARTPTS,"
                          f"crop={width}:{size[1]}:'{slide}':0,format=rgba[sl{k}]")
            chains.append(f"[sl{k}][sr{k}]hstack=inputs=2,setpts=PTS-STARTPTS+{start:.3f}/TB[scene{k}]")
        else:
            chains.append(f"[{1 + len(inputs)}:v]scale={size[0]}:{size[1]},format=rgba,{fades}[scene{k}]")
        chains.append(f"[{last}][scene{k}]overlay=0:0:eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'[s{k}]")
        last = f"s{k}"
    return chains, last, inputs


LOWER_THIRD_FIRST = 3.0     # the channel's lower third (lower_third.py) shows 3 s into the video,
LOWER_THIRD_EVERY = 240.0   # then every 4 minutes,
LOWER_THIRD_END_GAP = 20.0  # but not in the last 20 seconds


def lower_third_title(lesson_dir: Path) -> str:
    """The title on the lower third: lesson.yaml's `lower_third`, or "Lesson N – " and the
    lesson title up to its colon (just "Lesson N" when that is too long for the pill)."""
    lesson = yaml.safe_load((lesson_dir / "lesson.yaml").read_text())
    if lesson.get("lower_third"):
        return lesson["lower_third"]
    title = str(lesson.get("title", "")).split(":")[0].strip()
    number = re.match(r"lesson(\d+)", lesson_dir.name)
    if not number:
        return title or "C++ for Beginners"
    return f"Lesson {number[1]} – {title}" if title and len(title) <= 34 else f"Lesson {number[1]}"


def render_lower_third(lesson_dir: Path, timing: dict, work_dir: Path, size: tuple[int, int], last: str,
                       first_input: int) -> tuple[list[str], str, list[Path]]:
    """Overlay the CS-Steps lower third (logo, channel name and this video's title) on top of
    everything else, at LOWER_THIRD_FIRST and every LOWER_THIRD_EVERY seconds."""
    print("  rendering the lower third...", flush=True)
    media = work_dir / "media"
    subprocess.run(
        [sys.executable, "-m", "manim", "render", "-t", "--resolution", f"{size[0]},{size[1]}", "--fps", "30",
         "--disable_caching", "--progress_bar", "none", "--media_dir", str(media), "-o", "lower_third",
         str(ROOT / "lower_third.py"), "LowerThird"],
        env={**os.environ, "LOWER_THIRD_TITLE": lower_third_title(lesson_dir)},
        check=True, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    clip = next(media.rglob("lower_third.mov"))
    length, shown = video_duration(clip), timing["video_duration"]
    times = [LOWER_THIRD_FIRST]
    while times[-1] + LOWER_THIRD_EVERY + length < shown - LOWER_THIRD_END_GAP:
        times.append(times[-1] + LOWER_THIRD_EVERY)
    names = [f"lt{k}" for k in range(len(times))]
    chains = [f"[{first_input}:v]split={len(times)}" + "".join(f"[{n}src]" for n in names)]
    for n, t in zip(names, times):
        chains.append(f"[{n}src]setpts=PTS-STARTPTS+{t:.3f}/TB[{n}]")
        chains.append(f"[{last}][{n}]overlay=0:0:eof_action=pass:enable='between(t,{t:.3f},{t + length:.3f})'[{n}o]")
        last = f"{n}o"
    return chains, last, [clip]


def mux(video: Path, track: np.ndarray, narration: Path, output: Path, encode: bool,
        overlays: tuple[list[str], str, list] | None = None) -> None:
    """Write the narration track and combine it with `video`. With `encode`, the (lossless)
    screen recording is encoded once at high quality; otherwise its video is copied as is.
    An overlay input is a path, or (input options, path), e.g. (["-ss", "12.5", "-t", "8"], screen)."""
    sf.write(narration, track, SAMPLE_RATE)
    tmp = output.with_name(output.stem + ".tmp.mp4")
    video_args = (["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"] if encode
                  else ["-c:v", "copy"])
    maps, extra = ["-map", "0:v", "-map", "1:a"], []
    if encode and overlays and overlays[0]:
        chains, last, inputs = overlays
        maps = ["-filter_complex", ";".join(chains), "-map", f"[{last}]", "-map", "1:a"]
        for item in inputs:
            options, path = item if isinstance(item, tuple) else ([], item)
            extra += [*options, "-i", str(path)]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-i", str(narration), *extra, *maps,
         *video_args, "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", str(tmp)],
        check=True,
    )
    tmp.replace(output)


# --- Screen actions --------------------------------------------------------------------

# Neighbouring keys on a US keyboard, for the occasional typo.
NEIGHBOURS = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh", "u": "yij", "i": "uok",
    "o": "ipl", "p": "ol", "a": "qsz", "s": "awdx", "d": "sefc", "f": "drgv", "g": "fthb",
    "h": "gyjn", "j": "hukm", "k": "jil", "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv",
    "v": "cfgb", "b": "vghn", "n": "bhjm", "m": "njk",
}
SHIFTED = set('~!@#$%^&*()_+{}|:"<>?')  # need Shift: a person types these a little slower


def type_key(win: str, ch: str) -> None:
    if ch == "\n":
        xdotool_key(win, "Return")
    else:
        focus(win)
        run("xdotool", "type", "--clearmodifiers", "--delay", "0", ch)


def type_word(win: str, word: str, delay_ms: int) -> None:
    """Send a run of letters and digits in one xdotool call, with xdotool's own key delay:
    one call per character would add 50-100 ms each and cap the speed."""
    focus(win)
    run("xdotool", "type", "--clearmodifiers", "--delay", str(max(1, delay_ms)), word)


def type_like_a_person(win: str, text: str, delay_ms: int, typo_rate: float = 0.015) -> None:
    """Type like a person: words in quick runs (one xdotool call each), a short pause before a
    word, slower Shift symbols, "thinking" pauses after ; { } and line ends, the odd hesitation,
    and now and then a neighbouring key pressed by mistake and fixed with Backspace (typo_rate per
    letter; 0 turns typos off). The average speed stays about delay_ms per character."""
    for token in re.findall(r"[A-Za-z0-9_]+|.", text, re.S):
        sent = time.monotonic()
        if len(token) > 1 or token.isalnum() or token == "_":
            in_word = round(0.6 * delay_ms * random.uniform(0.85, 1.15))
            typo_at = next((i for i, ch in enumerate(token)
                            if ch.isalpha() and ch.lower() in NEIGHBOURS and random.random() < typo_rate), None)
            if typo_at is not None:
                if typo_at:
                    type_word(win, token[:typo_at], in_word)
                wrong = random.choice(NEIGHBOURS[token[typo_at].lower()])
                type_key(win, wrong.upper() if token[typo_at].isupper() else wrong)
                time.sleep(delay_ms * random.uniform(2.5, 4.5) / 1000)  # notice the mistake
                xdotool_key(win, "BackSpace")
                time.sleep(delay_ms * random.uniform(1.0, 1.8) / 1000)
                type_word(win, token[typo_at:], in_word)
            else:
                type_word(win, token, in_word)
            pause = delay_ms * random.lognormvariate(0, 0.35)  # after a word, before what follows
        else:
            type_key(win, token)
            pause = 0.84 * delay_ms * random.lognormvariate(0, 0.35)
            if token in SHIFTED:
                pause *= 1.4
            if token == " ":
                pause *= 1.5
            if token in ";{}" or token == "\n":
                pause *= random.uniform(2.0, 3.5)  # end of a statement: a moment to think
            # sending a key through xdotool takes 20-100 ms itself: count it as part of the pause
            pause -= (time.monotonic() - sent) * 1000
        if random.random() < 0.03:
            pause += delay_ms * random.uniform(2.5, 6.0)  # the odd hesitation
        time.sleep(max(0.0, pause / 1000))


def glide_mouse(x: int, y: int, duration: float) -> None:
    """Move the pointer to (x, y) along a smooth ease-in-out path so viewers can follow it."""
    loc = dict(kv.split(":") for kv in run("xdotool", "getmouselocation").split()[:2])
    x0, y0 = int(loc["x"]), int(loc["y"])
    steps = max(1, int(duration / 0.015))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # smoothstep easing
        run("xdotool", "mousemove", str(round(x0 + (x - x0) * t)), str(round(y0 + (y - y0) * t)))
        time.sleep(duration / steps)


def editor_line_y(rec: Recording, n: int) -> int:
    """Screen y (inside the window) of editor line n, given how far the editor is scrolled
    right now. VS Code scrolls by itself (typing past the bottom, opening the terminal) and
    can leave the top line half hidden, so first snap the view to whole lines."""
    top_line = rec.editor_top()
    rec.scroll_to(top_line)
    return EDITOR_FIRST_LINE_Y + EDITOR_LINE_HEIGHT * (n - top_line)


def perform(rec: Recording, actions: list[tuple[str, object]], type_delay: int, mouse_time: float,
            typo_rate: float = 0.015, clock: tuple[float, float] | None = None) -> None:
    """`clock` is (when the step started, its narration's length), for `at` to wait for a cue."""
    win = rec.win
    _, _, left, top = rec.region
    for kind, arg in actions:
        if kind in ("click", "move"):
            glide_mouse(left + arg[0], top + arg[1], mouse_time)
            if kind == "click":
                time.sleep(0.15)
                focus(win)
                run("xdotool", "click", "1")
                time.sleep(0.3)
                # typos only where code is typed: the terminal and input boxes (e.g. a watch) can
                # miss the fixing Backspace, and a mistyped command fails on camera
                rec.in_editor = arg in (TARGETS["editor"], TARGETS["new_file"])
        elif kind == "type":
            type_like_a_person(win, arg, type_delay, typo_rate if getattr(rec, "in_editor", True) else 0.0)
        elif kind == "key":
            for key in arg.split():  # several keys, e.g. "Left Left Left"
                xdotool_key(win, key)
                time.sleep(0.12)
                if key == "ctrl+grave":
                    rec.in_editor = False  # the terminal opens with focus
            time.sleep(0.2)
        elif kind == "line":
            rec.in_editor = True
            # click at the end of line `arg`, like a person would (the line must be on screen), or
            # with "N:C" just before column C (0-based), to put the cursor inside the line
            row, _, col = str(arg).partition(":")
            x = EDITOR_CODE_X + int(col) * EDITOR_CHAR_WIDTH if col else EDITOR_LINE_END_X
            glide_mouse(left + x, top + editor_line_y(rec, int(row)), mouse_time)
            time.sleep(0.15)
            focus(win)
            run("xdotool", "click", "1")
            time.sleep(0.3)
        elif kind == "select":
            rec.in_editor = True
            # highlight lines "A-B" by dragging from the start of A to the end of B
            first, last = (int(n) for n in str(arg).split("-")) if "-" in str(arg) else (int(arg),) * 2
            first_y, last_y = (editor_line_y(rec, n) for n in (first, last))
            glide_mouse(left + EDITOR_LINE_START_X, top + first_y, mouse_time)
            time.sleep(0.15)
            focus(win)
            run("xdotool", "mousedown", "1")
            glide_mouse(left + EDITOR_LINE_END_X, top + last_y, max(mouse_time, 0.25 + 0.04 * (last - first)))
            run("xdotool", "mouseup", "1")
            time.sleep(0.3)
        elif kind == "scroll":
            # glide the editor so line `arg` is at the top, from wherever it is now; the cursor
            # stays where it was (works while the terminal has focus, too)
            rec.scroll_to(int(arg))
        elif kind == "wait":
            time.sleep(arg)
        elif kind == "wait_shell":
            wait_for_idle_container(arg)
        elif kind == "at":
            # wait until the voice reaches the cue (a fraction of the line, see load_lesson)
            if clock and (remaining := clock[0] + arg * clock[1] - time.monotonic()) > 0:
                time.sleep(remaining)
        else:
            raise ValueError(f"Unknown action: {kind}")


def wait_for_idle_container(name: str, timeout: float = 900) -> None:
    """Wait until the shell in Docker container `name` has finished its command (only bash
    is left running), e.g. a download or an install whose length we can't know in advance."""
    time.sleep(0.5)  # let a command typed just before get started
    deadline = time.monotonic() + timeout
    idle = 0
    while idle < 2:  # twice in a row, so a gap between two processes doesn't count
        if time.monotonic() > deadline:
            raise RuntimeError(f"The shell in container {name} was still busy after {timeout:.0f}s")
        commands = run("docker", "top", name, "-o", "pid,comm").splitlines()[1:]
        idle = idle + 1 if all(line.split()[-1] == "bash" for line in commands) else 0
        time.sleep(0.4)


def video_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True,
    ).stdout
    width, height = out.strip().split(",")
    return int(width), int(height)


def video_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(out)


# --- Text outputs ----------------------------------------------------------------------

def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def subtitle_cues(text: str, start: float, end: float, width: int = 42) -> list[tuple[float, float, str]]:
    """Split one spoken line into readable cues of at most two lines, timed in proportion
    to their length."""
    chunks = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        wrapped = textwrap.wrap(sentence, width)
        chunks += ["\n".join(wrapped[k:k + 2]) for k in range(0, len(wrapped), 2)]
    total = sum(len(c) for c in chunks)
    cues, t = [], start
    for chunk in chunks:
        dt = (end - start) * len(chunk) / total
        cues.append((t, t + dt, chunk))
        t += dt
    return cues


def youtube_timestamp(seconds: float, with_hours: bool) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if with_hours else f"{s // 60}:{s % 60:02d}"


def export_text(steps: list[Step], timing: dict, out_dir: Path) -> None:
    """Write transcript.json, subtitles.srt and chapters.txt from the recorded timing."""
    entries = []
    for step in steps:
        if step.speaker:
            t = timing["steps"][step.id]
            entries.append({"id": step.id, "speaker": step.speaker, "start": round(t["start"], 3),
                            "end": round(t["start"] + t["duration"], 3), "text": step.text})
    (out_dir / "transcript.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")

    cues = [cue for e in entries for cue in subtitle_cues(e["text"], e["start"], e["end"])]
    (out_dir / "subtitles.srt").write_text("".join(
        f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n" for n, (a, b, text) in enumerate(cues, 1)))

    chapters = [(timing["steps"][s.id]["start"], s.chapter) for s in steps if s.chapter]
    if not chapters:
        return
    chapters[0] = (0.0, chapters[0][1])  # YouTube requires the first chapter at 0:00
    duration = timing["video_duration"]
    with_hours = duration >= 3600
    (out_dir / "chapters.txt").write_text(
        "\n".join(f"{youtube_timestamp(a, with_hours)} {title}" for a, title in chapters) + "\n")

    if len(chapters) < MIN_CHAPTERS:
        print(f"warning: YouTube needs at least {MIN_CHAPTERS} chapters", file=sys.stderr)
    for (a, title), b in zip(chapters, [a for a, _ in chapters[1:]] + [duration]):
        if b - a < MIN_CHAPTER_SECONDS:
            print(f'warning: chapter "{title}" is only {b - a:.0f}s (YouTube needs {MIN_CHAPTER_SECONDS}s+)',
                  file=sys.stderr)
        if "<" in title or ">" in title:
            print(f'warning: chapter "{title}" has < or >, which YouTube descriptions reject', file=sys.stderr)


# --- Main ------------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("lesson", type=Path, help="lesson folder, e.g. lessons/lesson1")
    parser.add_argument("--lang", default="en", help="language file in <lesson>/lang/ (default en)")
    parser.add_argument("--remix", action="store_true",
                        help="don't re-record: rebuild the narration onto the existing video")
    parser.add_argument("--reencode", action="store_true",
                        help="don't re-record: rebuild scenes, checklists and cards on the kept screen.mp4")
    parser.add_argument("--export", action="store_true",
                        help="only rewrite transcript, subtitles and chapters from the saved timing")
    parser.add_argument("--dry-run", action="store_true",
                        help="check the screen actions for free: no narration, ~1s per line, writes dry-run.mp4")
    parser.add_argument("--speech", action="store_true",
                        help="generate (and cache) the narration, then run --check-sync with its real lengths; "
                             "no screen recording")
    parser.add_argument("--check-sync", action="store_true",
                        help="before recording, in a second: estimate how long each step's actions take and "
                             "list the steps the narration doesn't cover (no screen, no narration generated)")
    parser.add_argument("--speed", type=float, default=1.0, help="speech speed (ElevenLabs: 0.7-1.2)")
    parser.add_argument("--loudness", type=float, default=-18.0, help="narration loudness for every line, LUFS")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--type-delay", type=int, default=85, help="average ms between typed characters")
    parser.add_argument("--typo-rate", type=float, default=0.015,
                        help="chance per letter of a typo that is fixed with Backspace (0 = none)")
    parser.add_argument("--mouse-time", type=float, default=0.35, help="seconds for each mouse movement")
    parser.add_argument("--gap", type=float, default=0.6, help="pause after a line when the same person speaks next")
    parser.add_argument("--turn-gap", type=float, default=0.25,
                        help="shorter pause when the other person answers, like a real conversation")
    parser.add_argument("--room-tone", type=float, default=None,
                        help="add a quiet background tone under the narration at this level, dBFS "
                             "(e.g. -65); off by default")
    args = parser.parse_args()

    lesson_dir = args.lesson.resolve()
    steps, language, workspace = load_lesson(lesson_dir, args.lang)
    out_dir = lesson_dir / "output" / args.lang
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "video.mp4"
    narration = out_dir / "narration.wav"
    timing_file = out_dir / "timing.json"

    def saved_timing() -> dict:
        if not timing_file.exists():
            sys.exit(f"No {timing_file}; record this language first")
        timing = json.loads(timing_file.read_text())
        if [s.id for s in steps] != list(timing["steps"]):
            sys.exit("lesson.yaml's steps changed since this video was recorded; record it again")
        return timing

    if args.reencode:
        video = out_dir / "screen.mp4"
        if not video.exists():
            sys.exit(f"{video} isn't there (it's kept from recordings made after 2026-10-28); record again")
        print(f"Narration ({language.name})...", flush=True)
        clips = normalize_loudness(synthesize(steps, language, args.speed, lesson_dir / "cache" / "tts"),
                                   args.loudness)
        timing = saved_timing()
        changed = [i for i, (s, c) in enumerate(zip(steps, clips))
                   if abs(timing["steps"][s.id]["duration"] - len(c) / SAMPLE_RATE) > 1e-6]
        if changed:
            # Changed lines are fine only at the very end, while a scene covers the screen: re-time
            # them one after another, and hold the last frame if the video needs to be longer.
            first = changed[0]
            if not all(s.scene for s in steps[first:]):
                sys.exit("The narration changed in the middle of the video; record it again")
            t = timing["steps"]
            cursor = t[steps[first].id]["start"]
            for s, c in zip(steps[first:], clips[first:]):
                t[s.id] = {"start": cursor, "duration": len(c) / SAMPLE_RATE}
                cursor += len(c) / SAMPLE_RATE + (args.gap if s.speaker else 0)
            ending = cursor + 1.0  # linger, as after a recording
            if ending > timing["video_duration"]:
                padded = out_dir / "screen.padded.mp4"
                extra = ending - timing["video_duration"]
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                                f"tpad=stop_mode=clone:stop_duration={extra:.3f}", "-c:v", "libx264",
                                "-qp", "0", "-preset", "ultrafast", str(padded)], check=True)
                padded.replace(video)
            timing["video_duration"] = max(timing["video_duration"], ending)
            timing_file.write_text(json.dumps(timing, indent=2) + "\n")
            print(f"Re-timed {len(steps) - first} closing line(s); the video is now {timing['video_duration']:.1f}s")
        encode_final(steps, language, lesson_dir, out_dir, video, clips, timing, narration, output, args.room_tone)
        print(f"Re-encoded {output} with transcript, subtitles and chapters in {out_dir}")
        return

    if args.speech:
        print(f"Narration ({language.name})...", flush=True)
        synthesize(steps, language, args.speed, lesson_dir / "cache" / "tts")
    if args.check_sync or args.speech:
        lengths = narration_lengths(steps, language, args.speed, lesson_dir / "cache" / "tts")
        estimated = sum(1 for n in lengths if n < 0)
        print(f"Narration: {len(lengths) - estimated} line(s) from the cache, {estimated} estimated from their length")
        late = []
        sync_report(steps, estimate_action_times(steps, args.type_delay, args.mouse_time, args.typo_rate, lengths,
                                                 late), lengths, tolerance=1.0, estimated=True)
        for step_id, behind in late:
            print(f"  {step_id:6} reaches a cue {behind:.1f}s after the voice says it: start it earlier or say less before it")
        return

    if args.export:
        export_text(steps, saved_timing(), out_dir)
        print(f"Wrote transcript, subtitles and chapters to {out_dir}")
        return

    if args.dry_run:
        clips = []
        durations = [1.0 if s.speaker else 0.0 for s in steps]
    else:
        print(f"Narration ({language.name})...", flush=True)
        clips = synthesize(steps, language, args.speed, lesson_dir / "cache" / "tts")
        durations = [len(c) / SAMPLE_RATE for c in clips]
        clips = normalize_loudness(clips, args.loudness)

    if args.remix:
        timing = saved_timing()
        if any(abs(timing["steps"][s.id]["duration"] - d) > 1e-6 for s, d in zip(steps, durations)):
            sys.exit("The narration changed since the video was recorded; record it again without --remix")
        offsets = [t["start"] for t in timing["steps"].values()]
        mux(output, build_track(clips, offsets, timing["video_duration"], args.room_tone), narration, output,
            encode=False)
        export_text(steps, timing, out_dir)
        print(f"Remixed narration into {output}")
        return

    check_requirements()
    video = out_dir / ("dry-run.mp4" if args.dry_run else "screen.mp4")
    step_times, action_times = [], []
    with vscode_recording(ROOT / "work", None, video, args.fps, show_mouse=True, fullscreen=True,
                          lossless=not args.dry_run, **workspace) as rec:
        time.sleep(0.5)
        for i, (step, duration) in enumerate(zip(steps, durations)):
            started = time.monotonic()
            step_times.append(started)
            perform(rec, step.actions, aligned_delay(step, args.type_delay, args.mouse_time, args.typo_rate, duration),
                    args.mouse_time, args.typo_rate, clock=(started, duration))
            action_times.append(time.monotonic() - started)
            # Hold the step until its narration has finished, plus a short pause: shorter when
            # the other person replies straight away, as in a real conversation.
            following = steps[i + 1] if i + 1 < len(steps) else None
            turn = step.speaker and following and following.speaker and following.speaker != step.speaker
            remaining = started + duration + (args.turn_gap if turn else args.gap) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        time.sleep(1)  # linger on the final frame
        rec.stop()
    # what the actions really took, to check estimate_action_times() against
    (out_dir / "actions.json").write_text(json.dumps(
        {s.id: round(t, 2) for s, t in zip(steps, action_times) if s.actions}, indent=1) + "\n")

    if args.dry_run:
        print(f"Dry run saved to {video}; final workspace in {ROOT / 'work'}")
        sync_report(steps, action_times,
                    narration_lengths(steps, language, args.speed, lesson_dir / "cache" / "tts"))
        return

    # ffmpeg takes a moment to grab its first frame after launch; measure that startup
    # delay (wall time recorded minus video length) so narration lines up with the video.
    length = video_duration(video)
    startup = max(0.0, (rec.stopped_at - rec.started_at) - length)
    offsets = [max(0.0, t - rec.started_at - startup) for t in step_times]
    timing = {
        "language": args.lang,
        "video_duration": length,
        "steps": {s.id: {"start": o, "duration": d} for s, o, d in zip(steps, offsets, durations)},
    }
    timing_file.write_text(json.dumps(timing, indent=2) + "\n")
    encode_final(steps, language, lesson_dir, out_dir, video, clips, timing, narration, output, args.room_tone)
    print(f"Saved {output} with transcript, subtitles and chapters in {out_dir}")


def encode_final(steps: list[Step], language: Language, lesson_dir: Path, out_dir: Path, video: Path,
                 clips: list[np.ndarray], timing: dict, narration: Path, output: Path, room_tone: float) -> None:
    """Draw the scenes, checklists and cards over the screen recording and add the narration.
    The screen recording (screen.mp4) is kept, so `--reencode` can redo this step alone."""
    print("Encoding the final video...", flush=True)
    offsets = [timing["steps"][s.id]["start"] for s in steps]
    length = timing["video_duration"]
    scene_chains, last, scene_inputs = render_scenes(steps, timing, language, lesson_dir, out_dir / "scenes",
                                                     video_size(video), video)
    zoom_chains, last = render_zooms(steps, timing, last)
    list_chains, last, panels = render_checklists(steps, timing, language, out_dir / "cards", last)
    card_chains, last = render_cards(steps, timing, out_dir / "cards", last, panels)
    brand_chains, last, brand_inputs = render_lower_third(lesson_dir, timing, out_dir / "scenes", video_size(video), last,
                                                          2 + len(scene_inputs))
    mux(video, build_track(clips, offsets, length, room_tone), narration, output, encode=True,
        overlays=(scene_chains + zoom_chains + list_chains + card_chains + brand_chains, last,
                  scene_inputs + brand_inputs))
    shutil.rmtree(out_dir / "cards", ignore_errors=True)
    shutil.rmtree(out_dir / "scenes", ignore_errors=True)
    export_text(steps, timing, out_dir)


if __name__ == "__main__":
    main()
