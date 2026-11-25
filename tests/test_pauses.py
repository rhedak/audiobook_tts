"""Pauses between paragraphs, from the blank lines and headings in the source."""

from audiobook_tts.build import (
    ATTRIBUTION_PAUSE_MS,
    PAUSE_BY_BLANK_LINES_MS,
    SCENE_BREAK_PAUSE_MS,
    SPEAKER_CHANGE_PAUSE_MS,
    TITLE_PAUSE_MS,
    plan_utterances,
)
from audiobook_tts.text import parse_blocks


def test_parse_blocks_counts_blank_lines_and_marks_headings():
    content = "# Chapter 1: Title\n\nFirst line.\nStill first.\n\n\nSecond.\n"
    blocks = parse_blocks(content)
    assert [(b.kind, b.text, b.blanks, b.heading) for b in blocks] == [
        ("para", "Chapter 1: Title", 0, True),
        ("para", "First line. Still first.", 1, False),
        ("para", "Second.", 2, False),
    ]


def test_parse_blocks_reports_tags_and_scene_breaks():
    content = "Intro.\n\n[[Gero]]\n\nHello.\n\n---\n\nAfter.\n"
    kinds = [(b.kind, b.text) for b in parse_blocks(content)]
    assert kinds == [
        ("para", "Intro."),
        ("tag", "Gero"),
        ("para", "Hello."),
        ("scene", ""),
        ("para", "After."),
    ]


def test_title_is_followed_by_a_long_pause():
    utts = plan_utterances("# Chapter 1: Title\n\nOpening text.\n")
    assert [u.text for u in utts] == ["Chapter 1: Title", "Opening text."]
    assert utts[1].pause_before_ms == TITLE_PAUSE_MS


def test_more_blank_lines_mean_longer_pauses():
    utts = plan_utterances("One.\n\nTwo.\n\n\nThree.\n\n\n\n\nFour.\n")
    pauses = [u.pause_before_ms for u in utts]
    assert pauses == [
        0,
        PAUSE_BY_BLANK_LINES_MS[1],
        PAUSE_BY_BLANK_LINES_MS[2],
        PAUSE_BY_BLANK_LINES_MS[3],
    ]


def test_speaker_change_uses_short_pause_and_keeps_speaker():
    # "he said." is attribution, so the Narrator reads it after the speech.
    content = "Narration.\n\n[[Gero]]\n\n\"Hello,\" he said.\n\n[[Narrator]]\n\nMore narration.\n"
    utts = plan_utterances(content, default_speaker="Narrator")
    assert [(u.speaker, u.text, u.pause_before_ms) for u in utts] == [
        ("Narrator", "Narration.", 0),
        ("Gero", '"Hello,"', SPEAKER_CHANGE_PAUSE_MS),
        ("Narrator", " he said.", ATTRIBUTION_PAUSE_MS),
        ("Narrator", "More narration.", PAUSE_BY_BLANK_LINES_MS[1]),
    ]


def test_scene_break_pause_applies_to_next_paragraph():
    utts = plan_utterances("Before.\n\n---\n\nAfter.\n")
    assert utts[1].pause_before_ms == SCENE_BREAK_PAUSE_MS


def test_unspeakable_paragraphs_are_dropped():
    utts = plan_utterances("Text.\n\n...\n\nMore.\n")
    assert [u.text for u in utts] == ["Text.", "More."]
