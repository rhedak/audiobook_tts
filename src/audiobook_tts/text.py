"""Text processing utilities for TTS: unicode normalization, Markdown
stripping, pronunciation substitution, and speakability checks.

Both the Panzer Island and Valley of Mist audiobook builders share these
identical functions. They are factored out here to avoid duplication.
"""

import re

_SPEAKABLE_RE = re.compile(r"[A-Za-z0-9]")


def is_speakable(text: str) -> bool:
    """Return True if *text* contains at least one letter or digit.

    Pure-punctuation text (quotes, ellipses, em-dashes) causes edge-tts to
    raise ``NoAudioReceived``; this guard routes such segments to silence
    instead of the TTS engine.
    """
    return bool(_SPEAKABLE_RE.search(text))


_UNICODE_NORMALIZATIONS: list[tuple[str, str]] = [
    # Curly quotes -> straight quotes (TTS reads curly quotes as
    # "left/right quotation mark")
    ("\u201c", '"'),  # left double quotation mark
    ("\u201d", '"'),  # right double quotation mark
    ("\u2018", "'"),  # left single quotation mark
    ("\u2019", "'"),  # right single quotation mark / curly apostrophe
    # Typographic punctuation
    ("\u2026", "..."),  # horizontal ellipsis
    ("\u2013", ", "),  # en dash
    ("\u2014", ". "),  # em dash
    ("\u2012", ", "),  # figure dash
]


def normalize_unicode(text: str) -> str:
    """Replace curly quotes, typographic punctuation, and dashes with
    TTS-friendly ASCII equivalents."""
    for char, replacement in _UNICODE_NORMALIZATIONS:
        text = text.replace(char, replacement)
    return text


def apply_pronunciations(text: str, pronunciations: dict[str, str]) -> str:
    """Replace known words with phonetic spellings for TTS.

    ``pronunciations`` maps a word or phrase to an English phonetic
    spelling the TTS engine will read with the intended pronunciation.
    Substitution is case-insensitive; original casing is replaced by the
    value as written.

    ``\\b`` only anchors correctly against a word character on that side,
    so it is omitted on whichever end of the key is punctuation -- otherwise
    the boundary never matches and the substitution silently does nothing.
    """
    for word, phonetic in pronunciations.items():
        left = r"\b" if word[0].isalnum() else ""
        right = r"\b" if word[-1].isalnum() else ""
        text = re.sub(rf"(?i){left}{re.escape(word)}{right}", phonetic, text)
    return text


# Sentinel paragraph marking a scene-break ("---") boundary, distinct from
# an ordinary paragraph break, so audio synthesis can give it a longer pause.
SCENE_BREAK = "\x00SCENE_BREAK\x00"


def parse_segments(content: str) -> list[str]:
    """Split chapter Markdown into paragraph-level text segments, in reading
    order, for TTS.

    Source files break prose after every sentence (see `styleguide_en.md`
    section 5), so a paragraph spans several lines; those are soft line
    breaks, not paragraph breaks, and are joined back into a single line per
    paragraph here. Only a blank line ends a paragraph. A scene break (``---``)
    is kept as the ``SCENE_BREAK`` sentinel, distinct from an ordinary blank-
    line paragraph break, so a later stage can give it a longer pause.
    """
    lines = content.splitlines()
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"-{3,}", stripped):
            flush()
            paragraphs.append(SCENE_BREAK)
            continue
        if not stripped:
            flush()
            continue
        # Strip heading markers, keep the text
        line = re.sub(r"^#{1,6}\s+", "", line)
        # Strip italic/bold markers
        line = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", line)
        # Strip Markdown image syntax entirely (alt text is not useful for
        # audio)
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)[^}]*\{[^}]*\}", "", line)
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = line.strip()
        if line:
            current.append(line)
    flush()

    return paragraphs


def md_to_tts_text(content: str) -> str:
    """Convert chapter Markdown to a single plain-text blob for TTS.

    Kept for callers that want the whole chapter as one string (tests,
    inspection); ``build_chapter`` uses ``parse_segments`` directly instead,
    so it can synthesize and pause between paragraphs individually rather
    than relying on edge-tts's own newline handling for a single giant
    request.
    """
    segments = [s for s in parse_segments(content) if s != SCENE_BREAK]
    return normalize_unicode("\n\n".join(segments))
