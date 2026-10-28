"""Context-aware respelling of English heteronyms.

A pronunciation dict (``text.apply_pronunciations``) rewrites every
occurrence of a word the same way, so it cannot fix words whose sound depends
on context: "I *read* it yesterday" (red) and "I will *read* it" (reed).

This module tags each occurrence with spaCy's part-of-speech tagger and
swaps in a respelling chosen by that tag. Only the cases in ``HETERONYMS``
are touched; a word whose tag is not listed is left alone, so the engine's
default reading is kept when the rules are unsure.

spaCy and its English model are optional (the ``heteronyms`` extra). Without
them ``apply_heteronyms`` returns the text unchanged.
"""

from __future__ import annotations

import re
from functools import lru_cache

# word -> {Penn Treebank tag: respelling}. Each respelling is a starting point
# chosen to be read as the intended sound; confirm each one by listening, since
# engines differ in how they read the same spelling.
#
# A value may also be ``(respelling, companion_words)``: the respelling applies
# only when the next word is one of *companion_words* (for "lead" the metal,
# "lead pipe"). Without a companion the word is left alone.
HETERONYMS: dict[str, dict[str, object]] = {
    "read": {"VBD": "red", "VBN": "red", "VB": "reed", "VBP": "reed", "VBZ": "reed"},
    "lead": {
        "VB": "leed",
        "VBP": "leed",
        "VBZ": "leed",
        "NN": ("led", {"pipe", "pipes", "paint", "poisoning", "acid", "weight", "weights"}),
    },
    "tear": {"VB": "tare", "VBP": "tare", "VBZ": "tare"},
    "wound": {"VBD": "wownd", "VBN": "wownd", "NN": "woond"},
    "close": {"JJ": "klohs", "RB": "klohs", "VB": "kloze", "VBP": "kloze"},
    "dove": {"VBD": "dohv", "VBP": "dohv", "NN": "duhv"},
    "live": {"JJ": "lyve", "RB": "lyve", "VB": "liv", "VBP": "liv"},
}

# A past-time word in the same sentence turns a present-tagged "read" into the
# past tense. spaCy often tags "I read the book yesterday" as present.
_PAST_TIME_WORDS = {"yesterday", "ago", "last", "earlier", "previously"}

_SPACY_MODEL = "en_core_web_sm"


@lru_cache(maxsize=1)
def _nlp():
    """Load the spaCy pipeline once, or return None if it is not installed."""
    try:
        import spacy

        nlp = spacy.load(_SPACY_MODEL, disable=["ner", "parser"])
    except (ImportError, OSError):
        return None
    # The parser is disabled for speed, so add a rule-based sentence splitter.
    nlp.add_pipe("sentencizer")
    return nlp


def spacy_available() -> bool:
    return _nlp() is not None


def _match_case(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _after_modal(token) -> bool:
    """True when a modal or infinitive marker sits just before *token*
    ("will read", "to read"), which makes the verb future or non-finite."""
    for prev in token.doc[max(0, token.i - 3) : token.i]:
        if prev.tag_ == "MD" or prev.lower_ == "to":
            return True
    return False


def _lookup(table: dict[str, object], tag: str, token) -> str | None:
    entry = table.get(tag)
    if entry is None:
        return None
    if isinstance(entry, tuple):
        respelling, companions = entry
        next_word = token.nbor(1).lower_ if token.i + 1 < len(token.doc) else ""
        return respelling if next_word in companions else None
    return entry


def apply_heteronyms(text: str) -> str:
    """Respell heteronyms in *text* according to their part-of-speech tag.

    Returns *text* unchanged when spaCy is not installed or no heteronym
    occurs in it.
    """
    lowered = text.lower()
    if not any(re.search(rf"\b{word}\b", lowered) for word in HETERONYMS):
        return text
    nlp = _nlp()
    if nlp is None:
        return text

    edits: list[tuple[int, int, str]] = []
    doc = nlp(text)
    for sent in doc.sents:
        has_past_time = any(t.lower_ in _PAST_TIME_WORDS for t in sent)
        for token in sent:
            table = HETERONYMS.get(token.lower_)
            if table is None:
                continue
            tag = token.tag_
            if (
                has_past_time
                and tag in {"VB", "VBP", "VBZ"}
                and "VBD" in table
                and not _after_modal(token)
            ):
                tag = "VBD"
            replacement = _lookup(table, tag, token)
            if replacement is None:
                continue
            edits.append(
                (token.idx, token.idx + len(token.text), _match_case(token.text, replacement))
            )

    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text
