"""Attribution ("he said") inside a speaker's paragraph is read by the Narrator."""

from audiobook_tts.build import (
    ATTRIBUTION_PAUSE_MS,
    NARRATOR_SPEAKER,
    plan_utterances,
    split_attribution,
)


def test_attribution_after_quote_goes_to_narrator():
    pieces = split_attribution('"Fair question," said Gero.', "Gero")
    assert pieces == [("Gero", '"Fair question,"'), (NARRATOR_SPEAKER, " said Gero.")]


def test_attribution_between_two_quotes_is_split_both_ways():
    pieces = split_attribution('"Yes," she said, "no."', "Linnea")
    assert pieces == [
        ("Linnea", '"Yes,"'),
        (NARRATOR_SPEAKER, " she said, "),
        ("Linnea", '"no."'),
    ]


def test_paragraph_without_quotes_stays_with_speaker():
    assert split_attribution("A reply with no quotes.", "Gero") == [
        ("Gero", "A reply with no quotes.")
    ]


def test_unbalanced_quotes_stay_whole():
    assert split_attribution('"Unfinished said Gero.', "Gero") == [
        ("Gero", '"Unfinished said Gero.')
    ]


def test_plan_utterances_splits_speaker_paragraph_with_short_pause():
    content = "[[Gero]]\n\n\"Fair question,\" said Gero, who had read it.\n"
    utts = plan_utterances(content, default_speaker=NARRATOR_SPEAKER)
    assert [(u.speaker, u.text) for u in utts] == [
        ("Gero", '"Fair question,"'),
        (NARRATOR_SPEAKER, " said Gero, who had read it."),
    ]
    assert utts[1].pause_before_ms == ATTRIBUTION_PAUSE_MS


def test_narrator_paragraphs_are_not_split():
    content = "The room was quiet, and he said nothing.\n"
    utts = plan_utterances(content, default_speaker=NARRATOR_SPEAKER)
    assert [(u.speaker, u.text) for u in utts] == [
        (NARRATOR_SPEAKER, "The room was quiet, and he said nothing.")
    ]
