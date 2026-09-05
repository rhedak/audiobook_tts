"""High-level audiobook chapter builder.

Supports two modes:

- **Single-voice** (Valley of Mist): each paragraph is synthesized with one
  voice.  Pass no *speaker_voices* and set *default_speaker* to ``""``.
- **Multi-voice** (Panzer Island): ``[[Name]]`` tags switch the voice
  mid-chapter.  Pass a *speaker_voices* mapping and set *default_speaker*
  to the narrator's name.

Both modes use the streaming synthesis with onset-clip fix and retry from
``synthesis.py``.
"""

import sys
from pathlib import Path

from pydub import AudioSegment

from audiobook_tts.chapters import select_chapter
from audiobook_tts.cover import embed_cover
from audiobook_tts.metadata import chapter_title, chapter_track, write_tags
from audiobook_tts.speakers import split_speaker_segments
from audiobook_tts.synthesis import synthesize
from audiobook_tts.text import (
    SCENE_BREAK,
    apply_pronunciations,
    is_speakable,
    normalize_unicode,
    parse_segments,
)

# Silence durations inserted between synthesized paragraph clips.
PARAGRAPH_PAUSE_MS = 450
SCENE_BREAK_PAUSE_MS = 900

# Pause inserted between consecutive segments spoken by different speakers.
SPEAKER_CHANGE_PAUSE_MS = 400

# Silence duration substituted for segments with no speakable content.
SILENT_SEGMENT_MS = 600


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

    if speaker_voices is not None:
        audio = await _build_multi_voice(
            content, voice, pronunciations, speaker_voices, default_speaker
        )
    else:
        audio = await _build_single_voice(content, voice, pronunciations)

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


async def _build_single_voice(
    content: str,
    voice: str,
    pronunciations: dict[str, str],
) -> AudioSegment | None:
    """Synthesize all paragraphs with a single voice."""
    segments = parse_segments(content)
    if not any(is_speakable(seg) for seg in segments if seg != SCENE_BREAK):
        return None

    audio = AudioSegment.empty()
    pending_pause_ms = 0

    for seg in segments:
        if seg == SCENE_BREAK:
            pending_pause_ms = SCENE_BREAK_PAUSE_MS
            continue

        text = apply_pronunciations(normalize_unicode(seg), pronunciations)
        if not is_speakable(text):
            continue

        if len(audio) > 0:
            audio += AudioSegment.silent(duration=pending_pause_ms or PARAGRAPH_PAUSE_MS)
        pending_pause_ms = 0

        audio += await synthesize(text, voice)

    return audio


async def _build_multi_voice(
    content: str,
    voice: str,
    pronunciations: dict[str, str],
    speaker_voices: dict[str, str],
    default_speaker: str,
) -> AudioSegment | None:
    """Synthesize with per-speaker voice switching."""
    segments = split_speaker_segments(
        content, default_speaker=default_speaker, pronunciations=pronunciations
    )
    if not segments:
        return None

    audio = AudioSegment.empty()
    prev_speaker = None

    for speaker, text in segments:
        seg_voice = speaker_voices.get(speaker, voice)
        if speaker and speaker != default_speaker and speaker not in speaker_voices:
            print(f"  note  unmapped speaker '{speaker}', using {seg_voice}")
        if prev_speaker is not None and prev_speaker != speaker:
            audio += AudioSegment.silent(duration=SPEAKER_CHANGE_PAUSE_MS)
        if is_speakable(text):
            audio += await synthesize(text, seg_voice)
        else:
            audio += AudioSegment.silent(duration=SILENT_SEGMENT_MS)
        prev_speaker = speaker

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
) -> None:
    """Build all (or selected) chapters, collecting failures for reporting.

    *album* / *artist* are written to every chapter's ID3 tags; track
    numbers are assigned from each chapter's position in *chapters* (before
    any *selector* filter), as ``n/total``.
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
