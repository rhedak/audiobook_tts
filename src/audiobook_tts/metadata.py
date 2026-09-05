"""ID3 text metadata for audiobook MP3s.

Cover art is handled separately (``cover.py``); this module writes the
title / album / artist / track-number frames so a chapter file shows up
in a player as a named track of a named book rather than an untitled
blob.  Deriving the title and track number from the chapter filename and
its first Markdown heading keeps the common case zero-config: a caller
that only knows the book title and author still gets fully tagged tracks.
"""

from pathlib import Path

from mutagen.id3 import ID3, TALB, TIT2, TPE1, TRCK
from mutagen.id3 import error as ID3Error

from audiobook_tts.chapters import sort_key

# "Chapter 12:", "Chapter XII -", "Chapter 3." and so on, at the start of a
# heading, stripped so the tag carries just the chapter's own name. The
# separator may be a colon, period, dash or en/em dash, with optional
# surrounding space.
_CHAPTER_PREFIX = "chapter "
_PREFIX_SEPARATORS = (":", ".", "-", "–", "—")


def _strip_chapter_prefix(heading: str) -> str:
    lowered = heading.lower()
    if not lowered.startswith(_CHAPTER_PREFIX):
        return heading
    rest = heading[len(_CHAPTER_PREFIX) :].lstrip()
    # Drop the numeral (arabic or roman) that follows "Chapter ".
    i = 0
    while i < len(rest) and (rest[i].isalnum()):
        i += 1
    numeral, tail = rest[:i], rest[i:].lstrip()
    if not numeral:
        return heading
    for sep in _PREFIX_SEPARATORS:
        if tail.startswith(sep):
            return tail[len(sep) :].strip()
    # "Chapter Twelve" with no separator and nothing after: nothing usable.
    return tail.strip() or heading


def chapter_title(content: str, stem: str) -> str:
    """A human title for a chapter.

    The first Markdown ``# `` heading with any ``Chapter N`` prefix
    removed, falling back to the filename slug (``ch03_behind_the_water``
    -> ``Behind The Water``) when the file has no heading.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return _strip_chapter_prefix(heading)
            break
        if stripped:
            break
    slug = stem
    if slug.startswith("ch"):
        parts = slug.split("_", 1)
        if len(parts) == 2:
            slug = parts[1]
    return slug.replace("_", " ").replace("-", " ").strip().title() or stem


def chapter_track(stem: str) -> int | None:
    """Track number from a ``chNN_`` / ``chNN-2_`` filename stem, or ``None``."""
    number, _suffix, _name = sort_key(stem + ".md")
    return number or None


def write_tags(
    mp3_path: Path,
    *,
    title: str | None = None,
    album: str | None = None,
    artist: str | None = None,
    track: int | None = None,
    track_total: int | None = None,
) -> None:
    """Write ID3 text frames to *mp3_path*, leaving any existing APIC
    (cover) frame untouched.  A ``None`` field is simply not written.
    """
    if not any(v is not None for v in (title, album, artist, track)):
        return

    try:
        tags = ID3(str(mp3_path))
    except ID3Error:
        tags = ID3()

    if title is not None:
        tags.setall("TIT2", [TIT2(encoding=3, text=title)])
    if album is not None:
        tags.setall("TALB", [TALB(encoding=3, text=album)])
    if artist is not None:
        tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
    if track is not None:
        text = f"{track}/{track_total}" if track_total else str(track)
        tags.setall("TRCK", [TRCK(encoding=3, text=text)])

    tags.save(str(mp3_path))
