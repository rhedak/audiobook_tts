---
name: create-audiobook
description: Make a complete audiobook from a story folder, end to end. Asks the author every decision (TTS backend, narrator, single or multi-voice, speaker voices, homographs, cover and metadata) with question prompts, then runs the builder and checks the result. Use when the author asks to create, build or narrate an audiobook for a story. For only the speaker tagging, use audiobook-speakers.
---

# Create an audiobook

This skill takes a story folder from prose to MP3 chapters. It asks the author
each decision first, with AskUserQuestion, then runs the steps. It uses the
`audiobook-build` command and, for multi-voice books, the audiobook-speakers
skill.

## Before you ask

1. Check the story folder. It needs `chapters/chNN_*.md` (the prose). Skip
   `_notes.md` companions. A single `story.md` is not supported by this builder.
2. Check the install. Run `audiobook-build --help` from the audiobook_tts repo
   root. If it fails, tell the author to run:

   ```bash
   uv sync --extra omnivoice --extra heteronyms
   ```

   Add `--extra kokoro`, `--extra qwen` or `--extra chatterbox` only for those
   backends.
3. Read the prose and list the characters who speak (name, role, rough line
   count). Show the list in chat. This is the input to the multi-voice questions.

## Step 1: Ask the author

Use AskUserQuestion, at most four questions per call. Ask in this order, and
skip a question only when the answer is already known from the request.

**Call 1: the engine and the narrator's shape**

- *Backend.* Options, with the recommended one first:
  - `omnivoice` (recommended): local, runs on the machine. Voices are described
    in words ("male, middle-aged, british accent") and locked to clone prompts,
    so each voice stays the same across a book. Needs a model download and an
    Apple Silicon or CUDA machine.
  - `edge`: Microsoft's online voices. Fast and free, but the voices are fixed
    names (such as `en-US-AndrewNeural`), there is no voice design, and it needs
    an internet connection.
  - `kokoro`: local and fast, with a fixed set of voices. No voice design.
  - `qwen` or `chatterbox`: local voice cloning from a reference recording.
    More setup, and they need their own extras.
- *Structure.* Single narrator (the chapters read in one voice) or multi-voice
  (dialogue in the character voices).
- *Homographs.* Respell "read" (red or reed) and similar from context. Options:
  on (recommended, needs the heteronyms extra), off.

**Call 2: the narrator's voice**

For `omnivoice`, offer three designs that differ in gender and accent, plus a
"describe my own" option. For `edge`, offer three voice names from the engine's
list. For `kokoro`, list its voices. Ask for the narrator's voice only once.

**Call 3: the book's metadata and cover**

- Album title (default: the folder name, title-cased).
- Author name for the ID3 tags (default: `git config user.name`).
- Cover: is there a `01_cover*` image in the story folder? If not, the MP3s get
  no cover art. Ask whether to proceed without one.

**Call 4, multi-voice only: the cast**

- Which characters get their own voice (multi-select, from the list in chat).
- How family or secondary characters get voices: their own voice each, one
  shared voice per group, or one shared voice.
- How minor speakers (guards, a crowd) are voiced.

Write the answers into `speaker_tags/voices.json`. The `design` for the narrator
is the chosen design, or an edge or kokoro voice name. Mark OmniVoice designs as
drafts.

## Step 2: Choose the voices by ear (omnivoice only)

Design strings are guesses until someone hears them. For each speaker role,
write two or three candidates to `speaker_tags/candidates.json`, run
`audiobook-build <story> --samples`, and tell the author which clips to listen to
in `speaker_tags/samples/`. Then ask which candidate each character gets, with
AskUserQuestion, using the candidate labels as options. The author can also let
the agent choose, with a review list in `decisions.md`.

Copy the chosen designs into `voices.json`, then lock every voice:

```bash
audiobook-build <story> --clone-voices
```

Locking is required for omnivoice. Without it each paragraph re-samples the
voice, and the voice drifts after each pause. The builder warns about any
unlocked speaker.

## Step 3: Tag the speakers (multi-voice only)

Follow the audiobook-speakers skill, Steps 3 and 4, for the chapters: the ops
files, the ambiguous lines (ask the author which mode they want), and the
homograph list. Do not change the prose.

## Step 4: Build

Single narrator:

```bash
audiobook-build <story> --album "<title>" --author "<name>"
```

Multi-voice:

```bash
audiobook-build <story> --speakers --album "<title>" --author "<name>"
```

The output goes to `<story>/audiobook/`, one MP3 per chapter, numbered as track
numbers. Build one chapter first with `--chapter NN` and listen to its opening
and a dialogue passage before the full run, since a full book takes a while on
local models. Rerun with `--force` to replace MP3s that already exist.

## Step 5: Check the result

- List the MP3s, their durations and their track numbers.
- Check that every chapter built. A failed chapter is listed at the end of the
  run, and it can be rebuilt with `--chapter`.
- Tell the author what to listen for: the opening of chapter 1, the title pause,
  a dialogue passage with attribution, and any homograph they were unsure of.
- Do not commit anything unless the author asks.

## Summary for the author

Report what was built, where it is, which voices were used, and anything you
chose on their behalf (for example a homograph reading the author did not
answer), with the decisions file to review.
