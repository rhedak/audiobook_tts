"""Multi-voice speaker tag system.

Panzer Island uses ``[[Name]]`` tags on their own line to switch the
narrating voice for everything until the next tag (or end of file).  This
module handles:

- Detecting speaker tags (``SPEAKER_TAG_RE``)
- Splitting chapter content into ``(speaker, tts_text)`` segments
- Stripping redundant speaker attributions so the character does not
  audibly say their own name

Tags are a TTS-only convention and must be stripped from prose before
publication.
"""

import re

from audiobook_tts.text import apply_pronunciations, md_to_tts_text, normalize_unicode

# Speaker tags mark a voice switch: a line containing only ``[[Name]]``.
SPEAKER_TAG_RE = re.compile(r"^\[\[([^\[\]]+)\]\]$")


def split_speaker_segments(
    content: str,
    default_speaker: str = "",
    pronunciations: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Split chapter content into ``(speaker, tts_text)`` segments at
    ``[[SPEAKER]]`` tags.

    Text before the first tag is attributed to *default_speaker*.  Consecutive
    segments spoken by the same speaker are merged.  If *pronunciations* is
    given, pronunciation substitution is applied to each segment's text.
    """
    raw_segments: list[tuple[str, list[str]]] = []
    current_speaker = default_speaker
    current_lines: list[str] = []
    for line in content.splitlines():
        match = SPEAKER_TAG_RE.match(line.strip())
        if match:
            if current_lines:
                raw_segments.append((current_speaker, current_lines))
            current_speaker = match.group(1).strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        raw_segments.append((current_speaker, current_lines))

    segments: list[tuple[str, str]] = []
    for speaker, seg_lines in raw_segments:
        text = md_to_tts_text("\n".join(seg_lines))
        text = strip_redundant_speaker_prefix(text, speaker)
        if pronunciations:
            text = apply_pronunciations(text, pronunciations)
        if text:
            segments.append((speaker, text))

    merged: list[tuple[str, str]] = []
    for speaker, text in segments:
        if merged and merged[-1][0] == speaker:
            prev_speaker, prev_text = merged[-1]
            merged[-1] = (prev_speaker, prev_text + "\n\n" + text)
        else:
            merged.append((speaker, text))
    return merged


def strip_redundant_speaker_prefix(text: str, speaker: str) -> str:
    """Drop attribution text that names the speaker already voicing the
    segment, so the character does not audibly say their own name:

    - A "Name: " attribution prefix (e.g. ``Nadeshiko: "..."``)
    - A "Name, descriptor: " attribution prefix (e.g. ``Katyusha, from the
      console: "..."``)
    - A "Name's voice, descriptor: " attribution prefix
    - A bare POV-switch header line (``*Name*`` -> "Name" after
      italic-stripping) at the start of the segment
    - A bare trailing "Name." attribution
    - A trailing "Name, descriptor." attribution
    - A mid-sentence "Name, descriptor." attribution between two quoted
      fragments

    An empty *speaker* disables stripping entirely: every pattern would
    otherwise degenerate (e.g. the trailing-attribution rule would eat any
    ", ... ." clause off the end of the text).
    """
    if not speaker:
        return text
    text = re.sub(
        rf"(^|\n)\s*{re.escape(speaker)}('s [^,:\n]*)?(,[^:\n]*)?:\s*", r"\1", text
    )
    text = re.sub(rf"^{re.escape(speaker)}\n+", "", text)
    text = re.sub(rf'"\s*{re.escape(speaker)}(,[^.\n]*)?\.\s*"', '" "', text)
    text = re.sub(rf"\s*{re.escape(speaker)}(,[^.\n]*)?\.?\s*$", "", text)
    return text
