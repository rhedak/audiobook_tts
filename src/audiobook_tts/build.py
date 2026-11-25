"""High-level audiobook chapter builder.

Supports two modes:

- **Single-voice** (Valley of Mist): each paragraph is synthesized with one
  voice.  Pass no *speaker_voices* and set *default_speaker* to ``""``.
- **Multi-voice** (Panzer Island): ``[[Name]]`` tags switch the voice
  mid-chapter.  Pass a *speaker_voices* mapping and set *default_speaker*
  to the narrator's name.

Both modes use the streaming synthesis with onset-clip fix and retry from
``synthesis.py`` by default. Pass an *engine* (see ``audiobook_tts.engines``)
to narrate with another backend, and ``heteronyms=True`` to respell
context-dependent words such as "read" (requires the ``heteronyms`` extra).
"""

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydub import AudioSegment

from audiobook_tts.chapters import select_chapter
from audiobook_tts.cover import embed_cover
from audiobook_tts.engines.base import Engine
from audiobook_tts.heteronyms import apply_heteronyms
from audiobook_tts.metadata import chapter_title, chapter_track, write_tags
from audiobook_tts.speakers import strip_redundant_speaker_prefix
from audiobook_tts.synthesis import synthesize
from audiobook_tts.text import (
    apply_pronunciations,
    is_speakable,
    normalize_unicode,
    parse_blocks,
)

# Silence before a paragraph, by the blank source lines before it: one is a
# normal paragraph break, two or more is a longer break (3 is the cap).
PAUSE_BY_BLANK_LINES_MS = {1: 450, 2: 900, 3: 1500}
# Silence after a chapter heading, before the text that follows it.
TITLE_PAUSE_MS = 1500
# Silence before the first paragraph after a ``---`` scene break.
SCENE_BREAK_PAUSE_MS = 900
# Silence before a paragraph whose speaker changed (one blank line only).
SPEAKER_CHANGE_PAUSE_MS = 400

Synth = Callable[[str, str], Awaitable[AudioSegment]]


async def build_chapter(
    path: Path,
    out_dir: Path,
    voice: str,
    pronunciations: dict[str, str] | None = None,
    speaker_voices: dict[str, str] | None = None,
    default_speaker: str = "",
    cover_image: Path | None = None,
    force: bool = False,
    album: str | None = None,
    artist: str | None = None,
    title: str | None = None,
    track: int | None = None,
    track_total: int | None = None,
    engine: Engine | None = None,
    heteronyms: bool = False,
) -> None:
    """Synthesize a single chapter Markdown file to MP3.

    When *speaker_voices* is provided, the chapter is split into
    speaker-tag segments and each gets the voice mapped from the dict
    (falling back to *voice* for unmapped speakers).  Otherwise every
    paragraph uses *voice*.

    *album* / *artist* set the ID3 book title and author.  *title* and
    *track* override the values otherwise derived from the chapter's first
    heading and its ``chNN_`` filename; pass *track_total* to record the
    track count as ``n/total``.

    *engine* selects the TTS backend (default: edge-tts). *heteronyms* turns on
    context-aware respelling of words like "read" before synthesis.
    """
    stem = path.stem
    out = out_dir / f"{stem}.mp3"

    if out.exists() and not force:
        print(f"  skip  {out.name} (already exists; use --force to rebuild)")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    content = path.read_text(encoding="utf-8")
    if pronunciations is None:
        pronunciations = {}

    synth: Synth = engine.synthesize if engine is not None else synthesize
    audio = await _build_audio(
        content, voice, pronunciations, speaker_voices, default_speaker, synth, heteronyms,
    )

    if audio is None or len(audio) == 0:
        print(f"  empty {path.name}, skipping")
        return

    audio.export(str(out), format="mp3")

    if cover_image is not None:
        embed_cover(out, cover_image)

    write_tags(
        out,
        title=title if title is not None else chapter_title(content, stem),
        album=album,
        artist=artist,
        track=track if track is not None else chapter_track(stem),
        track_total=track_total,
    )

    print(f"  built {out.name}")


def _prepare(text: str, pronunciations: dict[str, str], heteronyms: bool) -> str:
    """Apply pronunciation respellings, then context-aware heteronym fixes."""
    text = apply_pronunciations(text, pronunciations)
    return apply_heteronyms(text) if heteronyms else text


def pause_before_ms(
    blanks: int, heading_before: bool, scene_before: bool, speaker_changed: bool
) -> int:
    """Silence before a paragraph, from the source layout.

    A scene break wins, then the pause after a chapter heading, then a speaker
    change (a single blank line gets the shorter speaker-change pause). Otherwise
    the blank lines decide: one blank line is a normal paragraph break, two or
    more is a longer break.
    """
    if scene_before:
        return SCENE_BREAK_PAUSE_MS
    if heading_before:
        return TITLE_PAUSE_MS
    if speaker_changed and blanks <= 1:
        return SPEAKER_CHANGE_PAUSE_MS
    return PAUSE_BY_BLANK_LINES_MS[min(max(blanks, 1), 3)]


@dataclass(frozen=True)
class Utterance:
    """One paragraph to speak, with the speaker and the silence before it."""

    speaker: str
    text: str
    pause_before_ms: int


def plan_utterances(content: str, default_speaker: str = "") -> list[Utterance]:
    """Turn chapter Markdown into the paragraphs to speak, in order.

    Speaker tags switch *speaker* from the next paragraph on. Paragraphs with
    no speakable text are dropped. Redundant speaker attributions are stripped
    when a speaker is set, so a character does not say their own name.
    """
    utterances: list[Utterance] = []
    speaker = default_speaker
    prev_speaker: str | None = None
    prev_heading = False
    scene_before = False
    for block in parse_blocks(content):
        if block.kind == "tag":
            speaker = block.text
            continue
        if block.kind == "scene":
            scene_before = True
            continue
        text = normalize_unicode(block.text)
        if speaker:
            text = strip_redundant_speaker_prefix(text, speaker)
        if not is_speakable(text):
            continue
        if prev_speaker is None:
            pause = 0
        else:
            pause = pause_before_ms(
                block.blanks,
                heading_before=prev_heading,
                scene_before=scene_before,
                speaker_changed=speaker != prev_speaker,
            )
        utterances.append(Utterance(speaker, text, pause))
        prev_speaker = speaker
        prev_heading = block.heading
        scene_before = False
    return utterances


async def _build_audio(
    content: str,
    voice: str,
    pronunciations: dict[str, str],
    speaker_voices: dict[str, str] | None,
    default_speaker: str,
    synth: Synth,
    heteronyms: bool,
) -> AudioSegment | None:
    """Synthesize a chapter paragraph by paragraph, with the pauses between.

    Each paragraph is its own request, so the pauses are exact silences rather
    than whatever the engine does with newlines. With *speaker_voices*, each
    paragraph gets its speaker's voice, falling back to *voice*.
    """
    utterances = plan_utterances(content, default_speaker)
    if not utterances:
        return None

    audio = AudioSegment.empty()
    for utt in utterances:
        if len(audio) > 0:
            audio += AudioSegment.silent(duration=utt.pause_before_ms)
        seg_voice = voice
        if speaker_voices is not None:
            seg_voice = speaker_voices.get(utt.speaker, voice)
        audio += await synth(_prepare(utt.text, pronunciations, heteronyms), seg_voice)
    return audio if len(audio) > 0 else None


async def build_all(
    chapters: list[Path],
    out_dir: Path,
    voice: str,
    pronunciations: dict[str, str] | None = None,
    speaker_voices: dict[str, str] | None = None,
    default_speaker: str = "",
    cover_image: Path | None = None,
    force: bool = False,
    selector: str | None = None,
    album: str | None = None,
    artist: str | None = None,
    engine: Engine | None = None,
    heteronyms: bool = False,
) -> None:
    """Build all (or selected) chapters, collecting failures for reporting.

    *album* / *artist* are written to every chapter's ID3 tags; track
    numbers are assigned from each chapter's position in *chapters* (before
    any *selector* filter), as ``n/total``. *engine* and *heteronyms* are
    passed to every chapter (see ``build_chapter``).
    """
    track_by_stem = {p.stem: i + 1 for i, p in enumerate(chapters)}
    track_total = len(chapters)

    if selector is not None:
        matches = select_chapter(chapters, selector)
        if not matches:
            print(f"No chapter matching {selector!r} found", file=sys.stderr)
            sys.exit(1)
        chapters = matches

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Engine: {engine.name if engine is not None else 'edge'}")
    print(f"Voice: {voice}")
    print(f"Output: {out_dir}")
    print(f"Chapters: {len(chapters)}")
    print()

    failed: list[str] = []
    for path in chapters:
        try:
            await build_chapter(
                path,
                out_dir,
                voice,
                pronunciations=pronunciations,
                speaker_voices=speaker_voices,
                default_speaker=default_speaker,
                cover_image=cover_image,
                force=force,
                album=album,
                artist=artist,
                track=track_by_stem.get(path.stem),
                track_total=track_total,
                engine=engine,
                heteronyms=heteronyms,
            )
        except Exception as exc:  # noqa: BLE001 - reported and re-run per chapter
            failed.append(path.stem)
            print(f"  FAILED {path.stem}: {type(exc).__name__}: {exc}", file=sys.stderr)

    if failed:
        print(f"\n{len(failed)} chapter(s) failed:", file=sys.stderr)
        for stem in failed:
            print(f"  --selector {stem}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")
