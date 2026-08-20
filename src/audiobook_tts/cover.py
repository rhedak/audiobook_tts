"""Cover art embedding for MP3 files.

Embeds an image into the ID3 APIC tag of an MP3 file.  Used by both the
chapter builder and the pronunciation test builder.
"""

from pathlib import Path

from mutagen.id3 import APIC, ID3, error as ID3Error
from mutagen.mp3 import MP3

_COVER_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def embed_cover(mp3_path: Path, cover_image: Path) -> None:
    """Embed *cover_image* into the ID3 tags of *mp3_path*.

    Does nothing if *cover_image* does not exist.
    """
    if not cover_image.exists():
        return

    mime = _COVER_MIME_BY_SUFFIX.get(cover_image.suffix.lower(), "image/png")

    audio = MP3(str(mp3_path), ID3=ID3)
    try:
        audio.add_tags()
    except ID3Error:
        pass
    audio.tags.add(
        APIC(
            encoding=3,
            mime=mime,
            type=3,
            desc="Cover",
            data=cover_image.read_bytes(),
        )
    )
    audio.save()
