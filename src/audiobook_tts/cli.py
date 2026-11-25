"""Build audiobook MP3s from a story folder: narrator, speaker voices, clone prompts.

Story folder layout (every path is relative to the story folder)::

    chapters/chNN_*.md              prose, read in one narrator voice
    speaker_tags/chNN_*.md          prose with [[Speaker]] tags (--speakers)
    speaker_tags/voices.json        engine and one voice per speaker
    speaker_tags/pronunciations.json  optional respellings, e.g. {"read by": "reed by"}
    speaker_tags/candidates.json    optional voice candidates, for choosing by ear
    speaker_tags/samples/           optional sample clips, one per candidate
    voices/<Speaker>.pt             clone prompts (written by --clone-voices)
    01_cover*                       optional cover image, embedded in the MP3s
    audiobook/                      output: one MP3 per chapter (rebuilt on --force)

``voices.json`` looks like this, with one entry per speaker. A ``design`` is an
engine voice-design string (OmniVoice) or an engine voice name (edge). A relative
``.pt`` path is a clone prompt inside the story folder::

    {"engine": "omnivoice",
     "voices": {"Narrator": {"design": "voices/Narrator.pt"},
                "Gero": {"design": "male, middle-aged, low pitch, american accent"}}}

Usage::

    audiobook-build <story> [--speakers] [--voice VOICE] [--chapter C] [--force]
                    [--album TITLE] [--author NAME] [--no-heteronyms]
    audiobook-build <story> --samples        # one clip per candidate voice
    audiobook-build <story> --clone-voices   # lock each design-string voice

``--speakers`` builds from the tagged chapters, one voice per speaker. Without
it, the chapters are read in the Narrator's voice. ``--voice`` overrides the
Narrator's voice for one run.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pydub import AudioSegment

from audiobook_tts.build import build_chapter
from audiobook_tts.chapters import chapter_files, select_chapter
from audiobook_tts.engines import get_engine
from audiobook_tts.heteronyms import apply_heteronyms
from audiobook_tts.text import apply_pronunciations

NARRATOR = "Narrator"
TAGS_DIR = "speaker_tags"
PROSE_DIR = "chapters"
VOICES_DIR = "voices"
OUT_DIR = "audiobook"

# Fixed sample for choosing voices by ear: a narrator sentence, dialogue, and a
# homograph ("read"), so every candidate is heard on the same words.
SAMPLE_TEXT = (
    "The storyteller came in on the last of the light. "
    "\"Fair question,\" said Gero, who had read the letter twice."
)


def _load_voices(story: Path) -> tuple[str, dict[str, str]]:
    """Read speaker_tags/voices.json: the engine name and each speaker's voice.

    A relative ``.pt`` design is resolved inside the story folder, so a story
    keeps its own clone prompts.
    """
    path = story / TAGS_DIR / "voices.json"
    if not path.is_file():
        raise SystemExit(
            f"no {path}; create it with the create-audiobook or audiobook-speakers skill"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    engine = data.get("engine")
    voices = data.get("voices", {})
    if not engine or not voices:
        raise SystemExit(f"{path} needs an 'engine' and a 'voices' map")
    if NARRATOR not in voices:
        raise SystemExit(f"{path} has no '{NARRATOR}' voice")
    resolved: dict[str, str] = {}
    for speaker, entry in voices.items():
        design = entry.get("design", "")
        if not design:
            raise SystemExit(f"{path}: '{speaker}' has no design")
        if design.endswith(".pt"):
            design = str(story / design)
        elif engine == "omnivoice":
            print(
                f"warning: '{speaker}' is a design string, so its voice drifts between "
                "paragraphs; run --clone-voices to lock it",
                file=sys.stderr,
            )
        resolved[speaker] = design
    return engine, resolved


def _load_pronunciations(story: Path) -> dict[str, str]:
    path = story / TAGS_DIR / "pronunciations.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def build_samples(story: Path) -> None:
    """Write one clip per candidate voice to speaker_tags/samples/.

    Reads speaker_tags/candidates.json: {"engine": ..., "candidates": {label: design}}.
    """
    path = story / TAGS_DIR / "candidates.json"
    if not path.is_file():
        raise SystemExit(f"no {path}; write the candidate voices first")
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("candidates", {})
    if not candidates:
        raise SystemExit(f"{path} has no 'candidates'")
    engine = get_engine(data.get("engine", "omnivoice"))
    text = apply_heteronyms(apply_pronunciations(SAMPLE_TEXT, _load_pronunciations(story)))
    out_dir = story / TAGS_DIR / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    async def run() -> None:
        for label, design in candidates.items():
            audio = await engine.synthesize(text, design)
            out = out_dir / f"{label}.mp3"
            audio.export(str(out), format="mp3")
            print(f"  wrote {out}")

    asyncio.run(run())


def build_clone_prompts(story: Path) -> None:
    """Lock every design-string voice to a saved clone prompt in voices/.

    A design string is sampled again for every call, so the voice drifts after
    each pause. A clone prompt keeps one voice throughout. The reference clip is
    the candidate sample already heard for that design when there is one, else
    a fresh synthesis. voices.json is updated to point at the prompts.
    """
    path = story / TAGS_DIR / "voices.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    engine = get_engine(data.get("engine", "omnivoice"))
    if not hasattr(engine, "save_clone_prompt"):
        raise SystemExit(f"engine {engine.name!r} has no clone prompts")

    cand_path = story / TAGS_DIR / "candidates.json"
    candidates = {}
    if cand_path.is_file():
        candidates = json.loads(cand_path.read_text(encoding="utf-8")).get("candidates", {})
    label_by_design: dict[str, str] = {}
    for label, design in candidates.items():
        label_by_design.setdefault(design, label)

    spoken = apply_heteronyms(apply_pronunciations(SAMPLE_TEXT, _load_pronunciations(story)))
    out_dir = story / VOICES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    try:
        for speaker, entry in data.get("voices", {}).items():
            design = entry.get("design", "")
            if not design or design.endswith(".pt"):
                continue
            ref_wav = tmp / f"{speaker}.wav"
            label = label_by_design.get(design)
            sample = story / TAGS_DIR / "samples" / f"{label}.mp3"
            if label and sample.is_file():
                AudioSegment.from_file(sample).export(ref_wav, format="wav")
                source = f"sample {label}"
            else:
                audio = asyncio.run(engine.synthesize(spoken, design))
                audio.export(ref_wav, format="wav")
                source = "fresh synthesis"
            out = out_dir / f"{speaker}.pt"
            engine.save_clone_prompt(str(ref_wav), spoken, str(out))
            rel = f"{VOICES_DIR}/{speaker}.pt"
            # Targeted replacement keeps voices.json's layout; the design must be unique.
            needle = f'"design": {json.dumps(design)}'
            if text.count(needle) != 1:
                raise SystemExit(f"{path}: design of '{speaker}' is not unique; edit by hand")
            text = text.replace(needle, f'"design": {json.dumps(rel)}', 1)
            print(f"  {speaker}: {rel} (from {source})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    path.write_text(text, encoding="utf-8")
    print(f"updated {path}")


def _find_cover(story: Path) -> Path | None:
    found = sorted(story.glob("01_cover*"))
    return found[0] if found else None


def _default_album(story: Path) -> str:
    return story.name.replace("_", " ").replace("-", " ").title()


def _default_author() -> str | None:
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return name or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


async def build_story(
    story: Path,
    *,
    speakers: bool,
    voice: str | None,
    chapter: str | None,
    force: bool,
    album: str,
    author: str | None,
    heteronyms: bool,
) -> None:
    engine_name, voices = _load_voices(story)
    engine = get_engine(engine_name)
    narrator_voice = voice or voices[NARRATOR]
    pronunciations = _load_pronunciations(story)

    if speakers:
        chapters_dir = story / TAGS_DIR
        speaker_voices: dict[str, str] | None = voices
    else:
        chapters_dir = story / PROSE_DIR
        speaker_voices = None
    out_dir = story / OUT_DIR

    if not chapters_dir.is_dir():
        raise SystemExit(f"no {chapters_dir.name}/ directory in {story}")
    chapters = chapter_files(chapters_dir)
    if not chapters:
        raise SystemExit(f"no chNN_*.md files found in {chapters_dir}")
    if chapter is not None:
        matches = select_chapter(chapters, chapter)
        if not matches:
            raise SystemExit(f"no chapter matching {chapter!r}")
        chapters = matches

    out_dir.mkdir(parents=True, exist_ok=True)
    cover = _find_cover(story)
    track_by_stem = {p.stem: i + 1 for i, p in enumerate(chapter_files(chapters_dir))}
    track_total = len(track_by_stem)

    print(f"Engine: {engine_name}")
    if speakers:
        print(f"Speakers: {', '.join(voices)}")
    print(f"Narrator voice: {narrator_voice}")
    print(f"Respellings: {len(pronunciations)}")
    if heteronyms and importlib.util.find_spec("spacy") is None:
        print(
            "note: spaCy is not installed, so homographs such as 'read' are not "
            "respelled (install audiobook-tts[heteronyms])",
            file=sys.stderr,
        )
    print(f"Output: {out_dir}")
    print(f"Cover: {cover if cover else '(none)'}")
    print(f"Album: {album}")
    print(f"Author: {author if author else '(unknown)'}")
    print(f"Chapters: {len(chapters)}\n")

    failed: list[str] = []
    for path in chapters:
        try:
            await build_chapter(
                path,
                out_dir,
                narrator_voice,
                pronunciations=pronunciations,
                speaker_voices=speaker_voices,
                default_speaker=NARRATOR if speakers else "",
                engine=engine,
                heteronyms=heteronyms,
                cover_image=cover,
                force=force,
                album=album,
                artist=author,
                track=track_by_stem.get(path.stem),
                track_total=track_total,
            )
        except Exception as exc:  # noqa: BLE001 - reported, and re-run per chapter
            failed.append(path.stem)
            print(f"  FAILED {path.stem}: {type(exc).__name__}: {exc}", file=sys.stderr)

    if failed:
        print(f"\n{len(failed)} chapter(s) failed:", file=sys.stderr)
        for stem in failed:
            print(f"  --chapter {stem}", file=sys.stderr)
        raise SystemExit(1)
    print("\nDone.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="audiobook-build", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("story", type=Path, help="the story folder")
    parser.add_argument("--speakers", action="store_true", help="multi-voice build from speaker_tags/")
    parser.add_argument("--voice", help="narrator voice (design string or .pt path) for this run")
    parser.add_argument("--chapter", help='build only this chapter ("1", "ch01", or its stem)')
    parser.add_argument("--force", action="store_true", help="rebuild existing MP3s")
    parser.add_argument("--album", help="book title for the ID3 tags")
    parser.add_argument("--author", help="author for the ID3 tags")
    parser.add_argument("--no-heteronyms", action="store_true", help="do not respell homographs")
    parser.add_argument("--samples", action="store_true", help="write candidate sample clips and exit")
    parser.add_argument("--clone-voices", action="store_true", help="lock voices to clone prompts and exit")
    args = parser.parse_args(argv)

    story: Path = args.story
    if not story.is_dir():
        raise SystemExit(f"no such directory: {story}")
    if args.samples:
        build_samples(story)
        return
    if args.clone_voices:
        build_clone_prompts(story)
        return

    asyncio.run(
        build_story(
            story,
            speakers=args.speakers,
            voice=args.voice,
            chapter=args.chapter,
            force=args.force,
            album=args.album or _default_album(story),
            author=args.author or _default_author(),
            heteronyms=not args.no_heteronyms,
        )
    )


if __name__ == "__main__":
    main()
