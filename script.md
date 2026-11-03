# Lesson 0 — Hello, World! Your first Python program

Target length: about 7–8 minutes. Voice: your clone. Screen: VS Code (zoom 2), as in the install video.

Each block is: what you **say**, what we **do** on screen, and what the code / terminal shows.

---

## 1. Cold open (graphics, ~15 s)

**Show:** dark screen, a terminal types out by itself: `Hello, World!`

**Say:**
> One line of code. That's all it takes to make your computer talk to you.
> Everything is installed, so no more setup. Today we roll up our sleeves, get our hands dirty, and write our very first Python program.

**Card:** "Lesson 0 · Hello, World!"

## 2. What we'll do (sidebar checklist, ~15 s)

**Say:**
> Here's the plan. We'll get to know VS Code, create a folder for our code, add our first Python file, write one line, and run it. Then we'll take that one line apart, so you really understand what you wrote.
> Remember: don't just watch. Code along with me.

**Sidebar "TODAY":** 1 Open a folder · 2 Create hello.py · 3 Write & run · 4 Understand print()

---

## 3. Open a folder (VS Code, ~45 s)

**Do:** VS Code is open and empty.

**Say:**
> This is VS Code. On the left is the sidebar, the big area in the middle is the editor where we write code, and the terminal will show up at the bottom.
> In VS Code, we always work inside a folder. Open the File menu, and click Open Folder.

**Do:** File → Open Folder… The Windows folder dialog opens in Documents.

**Say:**
> Let's make a new folder for this lesson. Click New folder, and call it lesson0, with no space.

**Do:** New folder → type `lesson0` → Enter → Select Folder.

**Say (trust dialog appears):**
> VS Code asks if you trust the authors of the files in this folder. That's us, so click Yes, I trust the authors.

**Do:** Yes, I trust the authors. LESSON0 appears in the Explorer.

## 4. Create hello.py (~30 s)

**Say:**
> There's our folder in the Explorer. Now hover over it, and click the New File icon. Call it hello dot p y.
> The dot p y ending is important: it tells VS Code, and Windows, that this is a Python file. See the little Python icon? VS Code got it.

**Do:** New File icon → `hello.py` → Enter. The empty file opens.

---

## 5. Write the code (~20 s)

**Say:**
> And now, the moment you've been waiting for. Type print, open parenthesis, double quote, Hello, World!, double quote, close parenthesis.

**Do:** type `print("Hello, World!")`

```python
print("Hello, World!")
```

**Say:**
> Notice that VS Code helps you while you type: it suggests print, and closes the parenthesis and the quotes for you.
> See the white dot on the tab? That means the file isn't saved yet. Press Control S to save.

**Do:** Ctrl+S — the dot disappears.

## 6. Run it (~40 s)

**Say:**
> Time to run it. Open the Run menu, and click Run Without Debugging.
> Debugging is a powerful tool for finding mistakes in your code, and we'll learn it later in the course. For now, we just want to run.

**Do:** Run → Run Without Debugging. *(If VS Code asks which debugger to use the first time, pick Python Debugger → Python File — we'll narrate it.)*

**Do:** camera zooms in on the terminal. Output:

```
Hello, World!
```

**Say:**
> And there it is! Hello, World! — printed in the terminal by our very own program.
> One line of code, and the computer did exactly what we told it to. That's your first Python program. Congratulations!

**Sidebar:** ✓ Write & run

## 7. The shortcut (~15 s)

**Say:**
> Going through the menu every time is slow. Here's a shortcut worth learning right now: Control F5. It runs your file without debugging. Try it.

**Do:** Ctrl+F5 — the output appears again. **Card:** `Ctrl + F5` = Run Without Debugging.

**Say:**
> Super easy. Try to learn the shortcuts as we go, they make you much faster.

---

## 8. What did we just write? print() is a function (graphics, ~50 s)

**Card (animated machine):** `"Hello, World!"` → [ print ] → appears in the terminal

**Say:**
> Now let's understand what we wrote. print is a built-in Python function. Built-in means it comes with Python, ready to use.
> A function is like a machine. You give it some inputs, it does some work with them, and sometimes it hands you back a result.
> The inputs we give to a function are called arguments.
> The print function takes a message as its argument, and its job is to show that message in the terminal.

## 9. The parentheses (~25 s)

**Do:** back to the code, the parentheses are highlighted.

**Say:**
> To use a function, or as programmers say, to call it, you write its name, and then the parentheses. Don't forget them! Without the parentheses, Python doesn't run the function, and nothing gets printed.
> Whatever we put inside the parentheses is what we give to the function. That's where our message goes.

## 10. Why the quotes? (~35 s)

**Say:**
> But why is the message inside double quotes?
> Because it's text, and Python should print it exactly as it is. Text in quotes is called a string. When we write it straight into our code like this, it's a string literal: literally these characters.
> Without the quotes, Python would think Hello is the name of something in our program. You'll see the difference soon, when we learn about variables.

## 11. Single or double quotes (~35 s)

**Say:**
> And here's some good news: Python is not very strict about which quotes you use. You can change the double quotes to single quotes.

**Do:** change to `print('Hello, World!')` → Ctrl+F5 → same output.

**Say:**
> Same result. Just remember one rule: they have to match. If you open with a double quote, close with a double quote.

**Do:** change the end to `print("Hello, World!')` — VS Code shows red squiggles. Don't run.

**Say:**
> See the red squiggly line? That's VS Code telling you something is wrong, even before you run it. Let's fix it.

**Do:** back to `print("Hello, World!")`.

---

## 12. More than one argument (~40 s)

**Say:**
> I told you a function can take several inputs. So far we gave print just one. Let's give it more!
> Separate them with commas.

**Do:** change the line, Ctrl+F5.

```python
print("Hello", "World", "from Python")
```
```
Hello World from Python
```

**Say:**
> print took all three messages, and printed them on one line, with a space between each of them.

## 13. The separator: sep (~60 s)

**Say:**
> But what if you don't want spaces? What if you want commas between them?
> print is more powerful than it looks. It has another input, called the separator.
> But careful: if we just add a comma as another message, print thinks it's a fourth message to print. We have to say clearly: this one is not a message, it's the separator.
> We do that by writing its name: sep, equals, and then the separator in quotes.

**Do:** add `sep=","`, Ctrl+F5.

```python
print("Hello", "World", "from Python", sep=",")
```
```
Hello,World,from Python
```

**Say:**
> It worked! The messages are separated with commas. But it looks a bit squashed. The separator can be any text you like, so let's use a comma and a space.

**Do:** change to `sep=", "`, Ctrl+F5.

```
Hello, World, from Python
```

**Say:**
> Perfect. You control exactly what goes between the messages.

## 14. More lines (~45 s)

**Say:**
> One line is nice, but real programs have many lines. Let's call print two more times.

**Do:** add two lines, Ctrl+F5.

```python
print("Hello", "World", "from Python", sep=", ")
print("This is my first Python program.")
print("I'm learning Python!")
```
```
Hello, World, from Python
This is my first Python program.
I'm learning Python!
```

**Say:**
> Python runs your code from top to bottom, one line at a time, and every print starts on a new line.
> And look at the last line: I'm has an apostrophe, which is a single quote. That's exactly why double quotes are handy here: the single quote inside doesn't end the string.

**Sidebar:** ✓ Understand print()

---

## 15. Recap + assignment + outro (~40 s)

**Card "What you learned":** open a folder · create a .py file · run with Ctrl+F5 · print() is a function · arguments · strings in quotes · sep

**Say:**
> Let's recap. You opened a folder in VS Code, created your first Python file, and ran it with Control F5. You learned that print is a function, that we give it arguments inside the parentheses, that text goes in matching quotes, and that sep controls what goes between the messages.
> Your turn! In the assignments folder of the GitHub repo, you'll find this lesson's challenge: print a short card about yourself, your name, your city, and why you're learning Python. Pause the video and try it yourself first, then check the solutions folder.
> In the next video, we'll learn about variables, and you'll finally see why those quotes matter so much. See you there!

---

## Production notes (not narrated)

- **Run Without Debugging the first time:** VS Code may ask "Select debugger" → Python Debugger → Python File. I'll check that on this PC with `drive.py` (no full take) and add the click and a line of narration if it appears.
- **Terminal output:** Run Without Debugging first prints a long launcher command in the terminal, then the output. The zoom will frame the output line.
- **Which Python runs:** VS Code's Python extension has to pick an interpreter. On this PC it could pick the old C:\Python310 instead of uv's Python 3.15.2. I'll check and set it to the uv one (it doesn't change any output here, but it should match what students have).
- **Folder location:** Documents\lesson0. If you'd rather have one course folder (for example Documents\python-crash-course\lesson0, so every lesson goes next to it), say so.
- **Clean state per take:** lesson0 is deleted before each take, and VS Code's "recent folders" are cleared so the welcome page looks fresh.
- The assignment text needs to exist in the repo (`assignments/`) before the video is published.
