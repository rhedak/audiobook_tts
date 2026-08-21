from audiobook_tts.speakers import split_speaker_segments, strip_redundant_speaker_prefix


def test_name_colon_attribution_prefix_stripped_for_own_speaker():
    content = '[[Nadeshiko]]\n\nNadeshiko: "And the further we go."'
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Nadeshiko", '"And the further we go."')]


def test_pov_header_stripped_for_own_speaker():
    content = "[[Nadeshiko]]\n\n*Nadeshiko*\n\nThe aerial contacts broke formation."
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Nadeshiko", "The aerial contacts broke formation.")]


def test_name_comma_descriptor_colon_prefix_stripped():
    content = '[[Katyusha]]\n\nKatyusha, from the console: "The network is holding."'
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Katyusha", '"The network is holding."')]


def test_trailing_bare_name_attribution_stripped():
    content = '[[Nadeshiko]]\n\n"Why?" Nadeshiko.'
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Nadeshiko", '"Why?"')]


def test_name_possessive_voice_descriptor_colon_prefix_stripped():
    content = (
        "[[Katyusha]]\n\n"
        'Katyusha\'s voice, reading the layout: "She is not retreating."'
    )
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Katyusha", '"She is not retreating."')]


def test_trailing_name_descriptor_attribution_stripped():
    content = '[[Nadeshiko]]\n\n"She\'s there." Nadeshiko, from the side door.'
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Nadeshiko", '"She\'s there."')]


def test_mid_sentence_name_descriptor_attribution_stripped():
    content = (
        '[[Nadeshiko]]\n\n'
        '"Building north." Nadeshiko, from above. "Drones spread wide."'
    )
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [("Nadeshiko", '"Building north." "Drones spread wide."')]


def test_name_colon_prefix_for_other_speaker_not_stripped():
    content = '[[Erika]]\n\nKatyusha: "The nearest islands are forty kilometers offshore."'
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert segments == [
        ("Erika", 'Katyusha: "The nearest islands are forty kilometers offshore."')
    ]


def test_consecutive_same_speaker_merged():
    content = "[[Erika]]\n\nFirst line.\n\n[[Erika]]\n\nSecond line."
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert len(segments) == 1
    assert segments[0][0] == "Erika"
    assert "First line." in segments[0][1]
    assert "Second line." in segments[0][1]


def test_different_speakers_not_merged():
    content = "[[Erika]]\n\nErika speaks.\n\n[[Katyusha]]\n\nKatyusha replies."
    segments = split_speaker_segments(content, default_speaker="Erika")
    assert len(segments) == 2
    assert segments[0][0] == "Erika"
    assert segments[1][0] == "Katyusha"


def test_default_speaker_used_before_first_tag():
    content = "Narration here.\n\n[[Erika]]\n\nErika speaks."
    segments = split_speaker_segments(content, default_speaker="Narrator")
    assert segments[0][0] == "Narrator"
    assert segments[1][0] == "Erika"


def test_pronunciations_applied():
    content = '[[Erika]]\n\nKatyusha moved.'
    segments = split_speaker_segments(
        content,
        default_speaker="Erika",
        pronunciations={"katyusha": "Kaht-u-sha"},
    )
    assert segments == [("Erika", "Kaht-u-sha moved.")]


def test_strip_prefix_colon():
    result = strip_redundant_speaker_prefix('Nadeshiko: "Hello."', "Nadeshiko")
    assert result == '"Hello."'


def test_strip_prefix_trailing_name():
    result = strip_redundant_speaker_prefix('"Why?" Nadeshiko.', "Nadeshiko")
    assert result == '"Why?"'


def test_empty_speaker_strips_nothing():
    # The web UI passes default_speaker=""; with an empty name every
    # stripping pattern degenerates and eats ordinary prose (e.g. any
    # trailing ", ... ." clause read as a "Name, descriptor." attribution).
    text = (
        "The old lighthouse stood at the edge of the world, "
        "its beam cutting through the fog like a golden sword."
    )
    assert strip_redundant_speaker_prefix(text, "") == text


def test_empty_default_speaker_keeps_trailing_comma_clause():
    content = "The lighthouse stood at the edge of the world, its beam cutting through the fog."
    segments = split_speaker_segments(content, default_speaker="")
    assert segments == [("", content)]
