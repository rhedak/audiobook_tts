import pytest

from audiobook_tts.text import (
    SCENE_BREAK,
    apply_pronunciations,
    is_speakable,
    md_to_tts_text,
    normalize_unicode,
    parse_segments,
)


# -- is_speakable --


def test_bare_ellipsis_not_speakable():
    assert is_speakable('"..."') is False


def test_normal_dialogue_is_speakable():
    assert is_speakable('"Move."') is True


def test_speakable_with_digits():
    assert is_speakable("3") is True


def test_only_dashes_not_speakable():
    assert is_speakable('"--"') is False


# -- normalize_unicode --


def test_curly_double_quotes_normalized():
    assert normalize_unicode("\u201cHello.\u201d") == '"Hello."'


def test_curly_single_quotes_normalized():
    assert normalize_unicode("it\u2019s") == "it's"


def test_ellipsis_normalized():
    assert normalize_unicode("wait\u2026") == "wait..."


def test_en_dash_normalized():
    assert normalize_unicode("A\u2013B") == "A, B"


def test_em_dash_normalized():
    assert normalize_unicode("A\u2014B") == "A. B"


# -- apply_pronunciations --


def test_doc_period_spelled_out():
    assert apply_pronunciations(
        '"I am on your shoulder, Doc."',
        {"Doc.": "Doc "},
    ) == '"I am on your shoulder, Doc "'


def test_dr_e_spelled_out():
    assert apply_pronunciations(
        "Signed, Dr. E.",
        {"Dr. E.": "Doctor E "},
    ) == "Signed, Doctor E "


def test_doc_without_period_untouched():
    assert apply_pronunciations("Doc, are you there?", {"Doc.": "Doc "}) == (
        "Doc, are you there?"
    )


def test_docket_not_matched_by_doc_period():
    assert apply_pronunciations("Docket number four.", {"Doc.": "Doc "}) == (
        "Docket number four."
    )


def test_case_insensitive():
    assert apply_pronunciations("the wodensreich sent", {"Wodensreich": "woh-dens-ryech"}) == (
        "the woh-dens-ryech sent"
    )


def test_no_match_untouched():
    assert apply_pronunciations("Chiyo swept the step.", {"Wodensreich": "woh-dens-ryech"}) == (
        "Chiyo swept the step."
    )


def test_multi_word_phrase():
    d = {"Kiri no Magatsu": "ki-ri-noh-mahga-tsoo"}
    assert apply_pronunciations("From Kiri no Magatsu.", d) == "From ki-ri-noh-mahga-tsoo."


# -- md_to_tts_text --


def test_md_to_tts_strips_scene_break():
    text = md_to_tts_text("Paragraph one.\n\n---\n\nParagraph two.")
    assert "---" not in text
    assert "Paragraph one." in text
    assert "Paragraph two." in text


def test_md_to_tts_strips_heading_marker():
    text = md_to_tts_text("# Chapter 1: Kiriguchi\n\nBody text.")
    assert text.startswith("Chapter 1: Kiriguchi")


def test_md_to_tts_strips_bold():
    text = md_to_tts_text("**Important** words.")
    assert "**" not in text
    assert "Important" in text


def test_md_to_tts_strips_image_syntax():
    text = md_to_tts_text("![alt text](image.png)\n\nAfter image.")
    assert "alt text" not in text
    assert "After image." in text


# -- parse_segments --


def test_parse_segments_returns_one_paragraph_per_entry():
    segments = parse_segments("Paragraph one.\n\n---\n\nParagraph two.")
    assert segments == ["Paragraph one.", SCENE_BREAK, "Paragraph two."]


def test_parse_segments_joins_hard_wrapped_lines_within_a_paragraph():
    segments = parse_segments("One line\nwrapped across\ntwo more.\n\nNext paragraph.")
    assert segments == ["One line wrapped across two more.", "Next paragraph."]


def test_parse_segments_strips_heading_markers():
    segments = parse_segments("# Title\n\nBody text.")
    assert segments == ["Title", "Body text."]


def test_parse_segments_strips_image_syntax():
    segments = parse_segments("![alt](img.png)\n\nReal text.")
    assert segments == ["Real text."]


def test_parse_segments_empty_content():
    assert parse_segments("") == []


def test_parse_segments_only空白():
    assert parse_segments("\n\n\n") == []


def test_parse_segments_multiple_scene_breaks():
    segments = parse_segments("A.\n\n---\n\nB.\n\n---\n\nC.")
    assert segments == ["A.", SCENE_BREAK, "B.", SCENE_BREAK, "C."]
