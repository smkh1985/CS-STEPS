# Prompt: writing the code sections of a lesson video

You are building the **coding parts** of a beginner programming lesson video. A recorder program
drives VS Code on screen (it types, clicks, presses keys) while a teacher voice reads the narration.
Your job is to write two files per lesson: the **screen actions** (`lesson.yaml`) and the **words**
(`lang/en.yaml`). Animations/slides are made by someone else; where one belongs, just leave a step
with `scene: <Name>` and its narration, nothing more.

The voice is **Kokoro TTS** (free, local). There is one speaker: the teacher.

---

## 1. Files and structure

```
lessons/lessonN/
  lesson.yaml      # steps in order: id, speaker, actions, scene, checklist, check
  lang/en.yaml     # per step id: text (subtitles), say (what the voice reads), chapter, cues, checklists
```

Every step has an `id` (short and grouped by section: `k01` intro, `p01` plan, `a01..` first program,
`b01..` next part, `y01` your turn, `r1..` review). The same id appears in both files: actions in
`lesson.yaml`, words in `lang/en.yaml`. Every step has a line, and no line is unused.

### Actions available in `lesson.yaml`

```
type: text to type (\n = Enter)          key: keys, e.g. "ctrl+s", "Escape", "shift+Right", "ctrl+grave"
wait: seconds                            click / move: explorer | new_file | first_file | editor | terminal | corner
line: N        click at the END of editor line N
line: "N:C"    click just BEFORE column C of line N (0-based, indentation counts; always quoted)
select: A-B    highlight lines A to B (select: 9 highlights one line)
scroll: N      glide the editor so line N is the top line
at: N          wait until the voice reaches cue N of the step's `cues:` list in lang/en.yaml
scene: Name    an animation shown instead of the screen during this step (made elsewhere)
layout: split  the animation takes the right half; the editor + terminal stay visible on the left
checklist: NAME   show the plan checklist      checklist_at: F   appear F of the way into the line
check: N          tick checklist item N when this step starts
type_speed: S     this step types S times faster (boilerplate / repetitive code)
```

Put a comment header at the top of `lesson.yaml` describing: the lesson, each program file and its
final line numbers (which line holds what), and the two deliberate mistakes (exact broken code, the
exact g++ error message, and the exact fix with line:column).

---

## 2. The rules for the code sections (each came from a correction; don't skip any)

### Workspace and files
- **Empty workspace** at the start. Don't pre-seed files from earlier lessons. Exception: if the
  lesson revisits an earlier program, seed only that one, open it with `click: first_file` and explain
  it; don't retype it.
- **Every new program is a new `.cpp` file.** The first time: `click: explorer`, then `click: new_file`,
  type `name.cpp\n`, then `move: editor`. For later files only `click: new_file` (clicking explorer
  again closes it).

### Plan checklist first
- Before each program, the teacher reads a **checklist** of what we'll build. Title in CAPITALS, 4–6
  items, each **38 characters or fewer**. Show it on the plan step (`checklist: NAME`,
  `checklist_at: 0.1`), and tick each item with `check: N` on the step **right after** its code is typed
  (or tested).

### Typing
- **Type top to bottom** with explicit indentation (4 spaces). Auto-indent and auto-close are OFF, so
  type every space, brace and closing bracket yourself.
- **Chunks of about 40–90 characters per step, one narration line per chunk**, so the voice is talking
  while the code appears. Never type a big block silently. Boilerplate (includes, `using`, `int main()`
  and `{`) can be one step with `type_speed: 1.3`.
- **Code lines under 68 characters** (the split layout shows only 72 columns).
- **No silent typing:** the narration of a step must describe what is typed in it, in the same order,
  and be long enough to cover it. The recorder slows typing (up to 2.5x) so it ends about 85% into the
  line. If an action belongs at the END of a long line (e.g. New File after reading the plan), cue it
  with `at:` instead of letting the whole line stretch it.
- About 22 editor lines are visible while the terminal is open. Before clicking a line below that, use
  `scroll: N`.

### Editing existing code: minimal edits only
- **Change only the characters that change.** Never retype or delete a whole line; never use
  `ctrl+Left` word jumps; never use ctrl+Home + Down presses to reach a line.
- To insert: `line: "N:C"` then `type:`.
- To replace a few characters: `line: "N:C"`, then `key: "shift+Right"` once per character, then `type:`.
- To add a new line after line N: `line: N` (end of line) then `type: "\n    new code;"`.
- Put `wait: 0.3` between clicks/keys so the viewer can follow.
- Example (fix `[` `]` to `{` `}` on line 9):
  ```yaml
  - key: "Escape"
  - wait: 0.3
  - line: "9:21"
  - wait: 0.3
  - key: "shift+Right"
  - wait: 0.3
  - type: "{"
  - wait: 0.4
  - line: "9:38"
  - wait: 0.3
  - key: "shift+Right"
  - wait: 0.3
  - type: "}"
  ```

### Compile and run
Same pattern every time:
```yaml
- wait: 0.3
- key: "ctrl+s"
- wait: 0.5
- key: "ctrl+grave"        # first time: open the terminal; later: click: "terminal"
- wait: 0.5
- type: "clear\n"
- wait: 0.4
- type: "g++ arrays.cpp -o arrays\n"
- wait: 1.5
- type: "./arrays\n"
```
Then a separate step that reads the output aloud (`wait: 2.0` then e.g. `select: 12` to point at the
line responsible), and finally `move: "corner"` to get the mouse out of the way.

### Program input typed exactly when it is said
In a run step that needs keyboard input, type each input at the word that says it:
```yaml
# lesson.yaml
- id: d15
  speaker: teacher
  actions:
  - type: "./sum\n"
  - at: 1
  - type: "3\n"
  - at: 2
  - type: "4\n"
  - wait: 0.3          # keep the wait after the last input short
```
```yaml
# lang/en.yaml
d15:
  text: Let's run it. The first number, three. The second number, four. Sum, seven!
  cues: ["three", "four"]     # each phrase must appear in `say` (or `text` if no say)
```
Never use fixed `wait:`s to time inputs; they drift from the voice.

### Two mistakes on purpose, always fixed
- Each lesson has **one syntax error and one logical error**, typed naturally as if by accident.
- **The narration must not give the bug away while typing it.**
- Compile the broken version yourself first (`g++ x.cpp`) and quote **g++'s exact error message**
  (with line:column) in the narration. If g++ prints several errors, point at the useful one.
- Fix it on screen with a **minimal edit** (see above), then save, recompile and re-run.
- Logical error: the program compiles and runs but the output is wrong; the teacher notices it from the
  output ("First guest, Sarah? But Alex is our first guest!"), highlights the line with `select:`,
  explains, fixes, re-runs.

### Teacher only
- There is no student voice. If the source script has Student lines, turn them into the teacher's own
  questions ("You might wonder…", "You might ask…") and adjust the answer that follows.

---

## 3. The narration file (`lang/en.yaml`)

```yaml
language: English
tts: kokoro
voices:
  teacher: <kokoro voice id, e.g. am_michael>
checklists:
  arrays:
    title: INTRODUCING ARRAYS
    items:
    - Understand the declaration syntax
    - Create an int array
lines:
  a03:
    text: First, our int array. int numbers, five, equals two, four, ten, thirty-four, and forty-two.
    say:  First, our int array. Int numbers, five, equals two, four, ten, thirty-four, and forty-two.
    chapter: Writing arrays.cpp
```

- `text` = subtitles (correct spelling of code names). `say` = what the voice reads (optional;
  defaults to `text`). Use `say` to spell out anything the TTS would read badly.
- **Spell code for the voice in `say`**: `cout` → see-out, `cin` → see-in, `iostream` → eye-oh-stream,
  `g++` → g plus plus, `arrays.cpp` → arrays dot C P P, camelCase as words (`isPrime` → is prime),
  symbols as words (`<=` → less than or equal to, `[1]` → "one" said as "guests, one"), numbers as words
  when ambiguous (1004 → one thousand and four). **Kokoro is a different engine from before: listen to a
  test of `int`, `C++`, `std`, `char`, `string` and fix the spellings that sound wrong** (ElevenLabs
  needed `int` → "innt"; Kokoro may not).
- Quote any YAML text that ends in a colon.
- **Chapters**: `chapter:` on the first step of each section; the first at 0:00; each at least 10 s long.
- Read code the way a teacher would say it: "guests, four, equals Daniel" — not character by character.
- Short, lively sentences. Beginners. One idea per line.

---

## 4. A complete example (one program)

```yaml
# ===== The plan =====
- id: p01
  speaker: teacher
  checklist: arrays
  checklist_at: 0.1
# ===== arrays.cpp =====
- id: a01
  speaker: teacher
  check: 1
  actions:
  - wait: 0.3
  - click: "explorer"
  - wait: 0.8
  - click: "new_file"
  - wait: 0.5
  - type: "arrays.cpp\n"
  - move: "editor"
- id: a02
  speaker: teacher
  type_speed: 1.3
  actions:
  - type: "#include <iostream>\n#include <string>\n\nusing std::cout;\nusing std::string;\n\nint main()\n{\n"
- id: a03
  speaker: teacher
  actions:
  - type: "    int numbers[5] = [2, 4, 10, 34, 42];\n"      # syntax error on purpose
- id: a04
  speaker: teacher
  check: 2
  actions:
  - type: "    string guests[] = {\"Alex\", \"Sarah\", \"Sam\", \"Mina\", \"Omar\"};\n\n"
- id: a05
  speaker: teacher
  check: 3
  actions:
  - type: "    cout << \"First guest: \" << guests[1] << '\\n';\n\n    return 0;\n}"   # logical error on purpose
- id: a06                      # save, terminal, compile
  speaker: teacher
  actions:
  - wait: 0.3
  - key: "ctrl+s"
  - wait: 0.5
  - key: "ctrl+grave"
  - wait: 0.5
  - type: "clear\n"
  - wait: 0.4
  - type: "g++ arrays.cpp -o arrays\n"
  - wait: 1.5
- id: a07                      # read the error, point at the line
  speaker: teacher
  actions:
  - wait: 3.0
  - select: 9
- id: a08                      # minimal fix
  speaker: teacher
  actions:
  - key: "Escape"
  - wait: 0.3
  - line: "9:21"
  - wait: 0.3
  - key: "shift+Right"
  - wait: 0.3
  - type: "{"
  - wait: 0.4
  - line: "9:38"
  - wait: 0.3
  - key: "shift+Right"
  - wait: 0.3
  - type: "}"
- id: b01                      # explanation animation (built elsewhere), code stays visible
  speaker: teacher
  scene: BracesVsBrackets
  layout: split
- id: a09                      # recompile and run
  speaker: teacher
  actions:
  - wait: 0.3
  - key: "ctrl+s"
  - wait: 0.4
  - click: "terminal"
  - type: "clear\n"
  - wait: 0.4
  - type: "g++ arrays.cpp -o arrays\n"
  - wait: 1.5
  - type: "./arrays\n"
- id: a10                      # spot the logical error from the output
  speaker: teacher
  actions:
  - wait: 2.0
  - select: 12
- id: a11                      # minimal fix: replace one character
  speaker: teacher
  actions:
  - key: "Escape"
  - wait: 0.3
  - line: "12:38"
  - wait: 0.3
  - key: "shift+Right"
  - wait: 0.3
  - type: "0"
- id: a12                      # add a line after line 12
  speaker: teacher
  type_speed: 1.4
  actions:
  - wait: 0.3
  - line: 12
  - wait: 0.3
  - type: "\n    cout << \"Last guest: \" << guests[4] << '\\n';"
```

Matching narration:
```yaml
  a01:
    text: Let's write it. We open the explorer, click New File, and call it arrays.cpp.
    say: Let's write it. We open the explorer, click New File, and call it arrays dot C P P.
    chapter: Writing arrays.cpp
  a02:
    text: We include iostream for output, and string for the guest names. We bring in cout and string, and start main.
    say: We include eye-oh-stream for output, and string for the guest names. We bring in see-out and string, and start main.
  a03:
    text: First, our int array. int numbers, five, equals two, four, ten, thirty-four, and forty-two.
  a04:
    text: Then the guests. string guests, with empty square brackets, and five names. We gave five values, so the compiler counts them and makes five elements.
  a05:
    text: Let's display the first guest. The array's name, then the position in square brackets. guests, one. And main ends with return zero.
  a06:
    text: Let's test it. We save, open the terminal, clear it, and compile it with g++.
    say: Let's test it. We save, open the terminal, clear it, and compile it, with g plus plus.
    chapter: Square brackets or curly braces?
  a07:
    text: Errors! The first ones are confusing. Look for this one. Array must be initialized with a brace-enclosed initializer. On line nine, we put the values in square brackets!
  a08:
    text: So we select the opening square bracket, and type a curly brace. Then the closing bracket, and type a closing curly brace.
  a09:
    text: Let's save, click on the terminal, clear it, compile again, and run it. No errors this time.
  a10:
    text: First guest, Sarah? But Alex is our first guest! A logical error.
    chapter: Indices start at 0
  a11:
    text: So we select the one, and type zero. guests, zero. Alex.
  a12:
    text: Now the last guest. On a new line, the label Last guest, followed by guests, four. The fifth guest, at index four.
```

---

## 5. Check before handing over

1. **Replay the edits** (apply every `type`, `line`, `line: "N:C"` + `shift+Right` + `type` in order to
   an empty buffer) and confirm the result equals the intended final program character for character.
   Also replay the broken intermediate states and confirm each mistake is where the header says.
2. **Compile** the final program with `g++ -Wall -Wextra`, run it with the lesson's inputs, and check
   the output matches what the narration says. Compile the broken versions and check the quoted error
   messages are exact.
3. **Sync**: for each step, estimate the action time (typing ≈ chars / speed + waits) against the voice
   length (Kokoro audio duration, or ≈ 2.6 words/s). Lengthen the narration of any step whose actions
   run more than 1 s past its voice. No silent typing.
4. Every step id has a line, every line has a step, every `cues:` phrase is in its `say`/`text`, every
   column click lands on the intended character, and every code line is under 68 characters.
5. Keep it lean: video length proportional to content (a topic like arrays ≈ 6 minutes). Cut side
   topics from the source script rather than padding.
