"""audiobook-tts: Shared audiobook TTS library built on edge-tts."""

__version__ = "0.1.0"

from audiobook_tts.build import build_all, build_chapter
from audiobook_tts.chapters import chapter_files, resolve, select_chapter
from audiobook_tts.cover import embed_cover
from audiobook_tts.pronunciation_test import build_pronunciation_test
from audiobook_tts.speakers import split_speaker_segments
from audiobook_tts.synthesis import synthesize
from audiobook_tts.text import (
    SCENE_BREAK,
    apply_pronunciations,
    is_speakable,
    md_to_tts_text,
    normalize_unicode,
    parse_segments,
)

__all__ = [
    "SCENE_BREAK",
    "apply_pronunciations",
    "build_all",
    "build_chapter",
    "build_pronunciation_test",
    "chapter_files",
    "embed_cover",
    "is_speakable",
    "md_to_tts_text",
    "normalize_unicode",
    "parse_segments",
    "resolve",
    "select_chapter",
    "split_speaker_segments",
    "synthesize",
]
