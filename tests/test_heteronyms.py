"""Context-aware heteronym respelling. Needs the ``heteronyms`` extra (spaCy)."""

import pytest

from audiobook_tts import heteronyms

pytestmark = pytest.mark.skipif(
    not heteronyms.spacy_available(), reason="spaCy model not installed"
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("I read the book yesterday.", "I red the book yesterday."),
        ("I will read it tomorrow.", "I will reed it tomorrow."),
        ("Read it aloud.", "Reed it aloud."),
        ("She has read the letter.", "She has red the letter."),
        ("The lead pipe was heavy.", "The led pipe was heavy."),
        ("She would lead the team.", "She would leed the team."),
        ("He wound the clock.", "He wownd the clock."),
        ("Close the door.", "Kloze the door."),
        ("Stand close to me.", "Stand klohs to me."),
        ("The dove flew past.", "The duhv flew past."),
        ("She dove into the lake.", "She dohv into the lake."),
        ("The band would live here.", "The band would liv here."),
        ("It was live music.", "It was lyve music."),
    ],
)
def test_heteronym_respelling_by_context(text, expected):
    assert heteronyms.apply_heteronyms(text) == expected


def test_text_without_heteronyms_is_unchanged():
    text = "The quick brown fox jumps over the lazy dog."
    assert heteronyms.apply_heteronyms(text) == text


def test_noun_tear_is_left_alone():
    # The noun "tear" (crying) is not in the rules; engine default is kept.
    text = "A tear ran down her cheek."
    assert heteronyms.apply_heteronyms(text) == text


def test_missing_spacy_returns_text_unchanged(monkeypatch):
    monkeypatch.setattr(heteronyms, "_nlp", lambda: None)
    text = "I read the book yesterday."
    assert heteronyms.apply_heteronyms(text) == text
