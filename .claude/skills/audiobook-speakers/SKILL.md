---
name: audiobook-speakers
description: Prepare a short story for a multi-voice audiobook. Lists the speakers, agrees the voice set with the author, adds [[Speaker]] tags to each chapter without changing a word, and saves a reusable tagged copy. Use when the author asks to add speaker tags, plan character voices, or prepare a story's dialogue for the audiobook builder.
---

# Audiobook speakers

This skill tags a story's dialogue with speaker names, so the audiobook builder can
give each speaker a voice. It does not synthesize audio. The voices are
OmniVoice voice-design descriptions, and the builder reads the tags through
`audiobook_tts.speakers`.

Run it on one story at a time. Whole story at once for now.

In this document `<story>` is the story's folder, which holds `notes.md`,
`chapters/` and, after the skill has run, `speaker_tags/`. Run commands from the
`audiobook_tts` repo root, with `<story>` given as a path to that folder.

The builder that turns the tagged chapters into MP3s is
`scripts/build_audiobook_chapters.py` in the short_stories repo. Its path is
`../short_stories/scripts/build_audiobook_chapters.py` from here. The tagging
script is `scripts/tag_speakers.py` in this repo.

## Inputs

- `<story>/notes.md`: the cast, with the names and roles, and the locked terms.
- `<story>/chapters/chNN_*.md`: the prose. Skip the `_notes.md` companions.
- The author's answers to the questions below.

Do not change the prose. The only change to the text is tags and paragraph breaks.

## Step 1: List the speakers

Read every chapter. For each character who speaks, note the name, role, chapters
where they speak, and roughly how many lines. Add a `Narrator` for everything
that is not spoken dialogue. Group minor speakers (guards, crowds, one-line
speakers) so the voice list stays short.

Show the list in chat before asking anything.

## Step 2: Agree the voice set

Use AskUserQuestion, with at most four questions per call. Cover:

1. The narrator's voice (male or female, and the register).
2. Which main characters get their own voice (multi-select).
3. How family or secondary characters get voices: own voice each, shared by
   group (for example male and female), or one shared voice.
4. How minor speakers (guards, crowd) are voiced.

Then write `<story>/speaker_tags/voices.json`. Each entry has a `design`
string built only from OmniVoice's attribute list (see the OmniVoice repo,
`docs/voice-design.md`): gender, age, pitch, whisper, and English accent. Pick
attributes that keep neighbouring voices apart. Mark the strings as drafts. The
author listens to them before a build.

### Step 2b: Hear the voices, then map them

The design strings are guesses until someone listens, so when the author wants
to choose by ear:

1. Write `<story>/speaker_tags/candidates.json`: `{"engine": "omnivoice", "candidates":
   {"label": "design string", ...}}`. Give each character role two or three
   candidates (for example a low and a middle male voice, each with two accents).
   Label them plainly, such as `male_low_british`.
2. Run `uv run --no-project python ../short_stories/scripts/build_audiobook_chapters.py <story> --samples`.
   It writes `<story>/speaker_tags/samples/<label>.mp3`, every clip saying the same
   fixed sentence, so the voices can be compared fairly.
3. Tell the author which clips to listen to, then ask which candidate goes to
   each character (AskUserQuestion, with the candidate labels as options, at
   most four per question; group by role when there are more). The author can
   also let the agent map them, with a list of its choices for review.
4. Copy the chosen design string into `voices.json` for each speaker.

AskUserQuestion cannot play audio, so the author listens to the files outside
the chat first.

### Step 2c: Lock each voice to a clone prompt (required)

A design string is sampled again for every paragraph, so the voice drifts after
each pause. Once `voices.json` is final, lock every speaker:

```
uv run --no-project python ../short_stories/scripts/build_audiobook_chapters.py <story> --clone-voices
```

This writes `voices/<story>/<Speaker>.pt` (a saved OmniVoice clone prompt, made
from the candidate sample for that design, or a fresh synthesis of it) and
rewrites `voices.json` to point at it. Run it again after any voice change. The
builder warns about each speaker still on a design string. Do not build the
audiobook until every speaker is locked.

## Step 3: Add speaker tags

Work chapter by chapter. For each chapter, write an ops file with one entry per
speaker change, in text order:

```json
[
  {"at": "\"Fair question,\"", "speaker": "Gero"},
  {"at": "She picked up her tray.", "speaker": "Narrator"},
  {"at": "Still here.", "speaker": "Sister", "n": 2}
]
```

- `at` is exact text from the chapter that starts the new speaker's segment. It
  must occur at least `n` times (default 1, the first occurrence). Pick text that
  is unique, or give `n`.
- Dialogue goes to its speaker. Attribution clauses ("he said", "Linnea said")
  stay with the speaker.
- Narration goes to `Narrator`, including action sentences in the middle of a
  speech paragraph ("She picked up her tray.").
- Italic recollections of a told story go to `Narrator`, unless the author decides otherwise.
- The script skips a tag when the speaker is already talking, so repeating the
  narrator is harmless.

Run the script:

```bash
uv run --no-project python scripts/tag_speakers.py <story>/chapters/chNN_name.md ops/chNN.json <story>/speaker_tags/chNN_name.md
```

It fails, and writes nothing, if an anchor is missing or if any word changed.
Fix the ops file and run again.

### Ambiguous lines

A line is ambiguous when its speaker is not clear from the text (a chorus, an
unattributed reply, a chant, or a recollection). Two modes:

- **Ask one by one (default).** Put the lines in an AskUserQuestion, with the
  candidate speakers as options. Batch up to four per call. Write the author's
  answers into the ops file and into `decisions.md`.
- **Agent decides, review list.** Pick a speaker for each ambiguous line. Write
  every pick to `decisions.md` as a list: chapter, line, the pick, and why. Tell the
  author the list needs reviewing before the tags are final.

Ask the mode question once per story, at the first ambiguous line, and keep to
the answer.

### Homographs: same spelling, different sound

The builder respells words such as "read" (past tense "red", present "reed")
from context, with spaCy, when the `heteronyms` extra is installed. That covers
the common cases. The skill's job is the rest:

- List the homographs in the story (for example read, lead, wound, tear, live,
  close, dove, bow, wind, row, minute, content). Show each with its sentence.
- For a word the context rules cannot settle, or one the author names, ask the
  reading the same way as the ambiguous lines (or let the agent decide, with a
  review list).
- Write the agreed respellings to `<story>/speaker_tags/pronunciations.json`, a map from
  the word as written to the spelling the engine should say, such as
  `{"lead": "leed"}`. A phrase works too, such as `{"read by": "reed by"}`, for
  a case where the context rules get it wrong. The builder applies it to the
  spoken text only.

## Step 4: Save the reusable copy

Under `<story>/speaker_tags/`:

- `chNN_name.md`: the tagged chapters, ready for the builder.
- `ops/chNN.json`: the decisions. If a chapter's prose changes, rerun the script
  against the same ops file. It fails clearly where an anchor no longer matches.
- `voices.json`: the voice set and design strings.
- `pronunciations.json`: the agreed respellings, if any.
- `candidates.json` and `samples/`: the voice candidates and their clips, if the
  voices were chosen by ear. Keep them, so a voice can be changed after a full
  chapter has been heard.
- `decisions.md`: the voice set, ambiguous decisions, homograph decisions, and
  any assumptions.

Do not commit unless the author asks.

## Format rules for the tagged text

- A tag is a line that holds only `[[Name]]`, with a blank line on each side. The
  audiobook builder switches voice at that line until the next tag.
- Keep the heading `# Chapter N: Title` as it is. The builder reads it as the title.
- Keep scene breaks (`---`) as they are.
- Paragraph pauses follow the blank lines in the source: one blank line is a
  normal break, two blank lines a longer one. Do not add blank lines to the prose
  just to lengthen a pause without the author's agreement, since the chapter
  file is the text that is published.
- The style rules of the story repo apply to notes and headings: no double
  hyphens, and no em dashes except in dialogue.
