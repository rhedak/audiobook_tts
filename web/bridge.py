"""bridge.py — Python bridge for the browser-based audiobook builder.

Runs inside Pyodide. Exposes text-processing functions to JavaScript.
No external dependencies — only uses the audiobook_tts pure-Python modules.
"""

import json
import sys

# Add the src directory to Python path so audiobook_tts is importable
if "/home/pyodide/src" not in sys.path:
    sys.path.insert(0, "/home/pyodide/src")


# --- Text processing ---

def bridge_parse_chapter(content):
    """Parse a chapter's markdown into paragraph-level segments for TTS.

    Returns JSON: {segments: [...], speakers: [...]}
    - segments: list of {text, is_scene_break} objects
    - speakers: sorted unique list of [[Speaker]] tags found
    """
    from audiobook_tts.text import parse_segments, SCENE_BREAK
    from audiobook_tts.speakers import SPEAKER_TAG_RE

    raw_segments = parse_segments(content)

    segments = []
    for seg in raw_segments:
        segments.append({
            "text": seg,
            "is_scene_break": seg == SCENE_BREAK,
        })

    # Extract speaker tags
    speakers = sorted(set(
        m.group(1).strip()
        for m in SPEAKER_TAG_RE.finditer(content)
    ))

    return json.dumps({"segments": segments, "speakers": speakers})


def bridge_apply_pronunciations(text, pronunciations_json):
    """Apply pronunciation substitutions to text.

    Returns the transformed text string.
    """
    from audiobook_tts.text import apply_pronunciations

    pronunciations = json.loads(pronunciations_json)
    return apply_pronunciations(text, pronunciations)


def bridge_parse_multi_voice(content, default_speaker, pronunciations_json):
    """Parse a chapter with speaker tags into (speaker, text) segments.

    Returns JSON: {segments: [{speaker, text}]}
    """
    from audiobook_tts.speakers import split_speaker_segments

    pronunciations = json.loads(pronunciations_json) if pronunciations_json else {}
    segments = split_speaker_segments(
        content,
        default_speaker=default_speaker,
        pronunciations=pronunciations,
    )

    return json.dumps({
        "segments": [{"speaker": s, "text": t} for s, t in segments]
    })


def bridge_preview_text(content, pronunciations_json):
    """Preview how chapter text will be processed for TTS.

    Returns JSON with both the paragraph-level view and the TTS-ready text.
    """
    from audiobook_tts.text import parse_segments, SCENE_BREAK, apply_pronunciations, normalize_unicode
    from audiobook_tts.speakers import SPEAKER_TAG_RE

    pronunciations = json.loads(pronunciations_json) if pronunciations_json else {}

    raw_segments = parse_segments(content)

    paragraphs = []
    for seg in raw_segments:
        if seg == SCENE_BREAK:
            paragraphs.append({"original": "---", "tts_text": "", "is_scene_break": True})
        else:
            tts_text = apply_pronunciations(normalize_unicode(seg), pronunciations)
            paragraphs.append({
                "original": seg,
                "tts_text": tts_text,
                "is_scene_break": False,
            })

    speakers = sorted(set(
        m.group(1).strip()
        for m in SPEAKER_TAG_RE.finditer(content)
    ))

    return json.dumps({
        "paragraphs": paragraphs,
        "speakers": speakers,
    })


# --- Preset pronunciation dictionaries ---

def bridge_default_pronunciations():
    """Return a default pronunciation dictionary as JSON.

    Users can modify this in the UI.
    """
    defaults = {
        "Kapitaen": "kah-pih-TAYN",
        "Mira": "MEE-rah",
    }
    return json.dumps(defaults)


def bridge_default_speaker_voices():
    """Return a default speaker-voice mapping as JSON."""
    defaults = {
        "Kapitaen": "en-US-GuyNeural",
        "Mira": "en-US-JennyNeural",
    }
    return json.dumps(defaults)
