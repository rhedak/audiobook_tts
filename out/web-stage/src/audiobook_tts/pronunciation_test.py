"""Build a pronunciation-test MP3.

Speaks every entry in a pronunciation dict, one per paragraph, so a
phonetic-spelling change can be checked by listening to one short file
instead of rebuilding a whole chapter.

Reads the dict directly rather than a hand-maintained test chapter, so it
never drifts out of sync as entries are added.  Output is
``_pronunciation_test.mp3`` (leading underscore keeps it out of chapter
discovery globs).
"""

from pathlib import Path

from pydub import AudioSegment

from audiobook_tts.cover import embed_cover
from audiobook_tts.synthesis import synthesize
from audiobook_tts.text import apply_pronunciations

# Silence between pronunciation entries.
_PAUSE_MS = 450


async def build_pronunciation_test(
    out_dir: Path,
    pronunciations: dict[str, str],
    voice: str,
    cover_image: Path | None = None,
) -> None:
    """Synthesize and export a pronunciation-test MP3."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "_pronunciation_test.mp3"

    print(f"Voice: {voice}")
    print(f"{len(pronunciations)} names/terms, in this order:")
    for word, phonetic in pronunciations.items():
        print(f"  {word} -> {phonetic}")
    print()

    audio = AudioSegment.empty()
    for word in pronunciations:
        text = apply_pronunciations(f"{word}.", pronunciations)
        if len(audio) > 0:
            audio += AudioSegment.silent(duration=_PAUSE_MS)
        audio += await synthesize(text, voice)

    audio.export(str(out), format="mp3")
    if cover_image is not None:
        embed_cover(out, cover_image)
    print(f"Built {out}")
