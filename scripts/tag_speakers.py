#!/usr/bin/env python3
"""Insert ``[[Speaker]]`` tags into a chapter, at anchor text, without changing a word.

The audiobook builder (``audiobook_tts.speakers``) switches voice at a line that
holds only ``[[Name]]``. This script adds those lines to a chapter's Markdown
from a list of decisions, one per speaker change, and checks the result.

Usage:
    scripts/tag_speakers.py <chapter.md> <ops.json> <out.md>

``ops.json`` is a list of objects:
    {"at": "\\"Fair question,\\"", "speaker": "Gero"}
    {"at": "Still here.", "speaker": "Sister", "n": 2}

``at`` is exact text that starts a new speaker's segment. It must occur at
least ``n`` times in the chapter (default: the first). Ops are applied in text
order. A tag is skipped when the speaker is already talking, so repeating the
narrator is harmless.

The script fails, and writes nothing, unless:
- every anchor is found and no two anchors share a position;
- the words of the output, with tag lines removed, equal the words of the input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_SPEAKER = "Narrator"
TAG_LINE = re.compile(r"^\[\[[^\[\]]+\]\]$", re.MULTILINE)


def _find_nth(text: str, needle: str, n: int) -> int:
    start = -1
    for _ in range(n):
        start = text.find(needle, start + 1)
        if start < 0:
            return -1
    return start


def tag(source: str, ops: list[dict]) -> tuple[str, list[tuple[int, str]]]:
    positions: list[tuple[int, str]] = []
    for op in ops:
        at, speaker = op["at"], op["speaker"]
        n = int(op.get("n", 1))
        if not at or not speaker:
            raise ValueError(f"op needs 'at' and 'speaker': {op}")
        if source.count(at) < n:
            raise ValueError(f"anchor not found ({n}x needed): {at!r}")
        pos = _find_nth(source, at, n)
        positions.append((pos, speaker))

    positions.sort(key=lambda p: p[0])
    seen = set()
    for pos, _ in positions:
        if pos in seen:
            raise ValueError(f"two ops share one position: {pos}")
        seen.add(pos)

    out: list[str] = []
    cursor = 0
    current = DEFAULT_SPEAKER
    applied: list[tuple[int, str]] = []
    for pos, speaker in positions:
        if speaker == current:
            continue
        out.append(source[cursor:pos].rstrip(" \t"))
        out.append(f"\n\n[[{speaker}]]\n\n")
        cursor = pos
        current = speaker
        applied.append((pos, speaker))
    out.append(source[cursor:])

    text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text, applied


def words(text: str) -> list[str]:
    without_tags = TAG_LINE.sub("", text)
    return without_tags.split()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("chapter", type=Path)
    p.add_argument("ops", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args(argv)

    source = args.chapter.read_text(encoding="utf-8")
    ops = json.loads(args.ops.read_text(encoding="utf-8"))
    try:
        tagged, applied = tag(source, ops)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if words(tagged) != words(source):
        print("error: words changed; nothing written", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(tagged, encoding="utf-8")
    counts = Counter(speaker for _, speaker in applied)
    print(f"wrote {args.out} ({len(applied)} tags)")
    for speaker, n in counts.most_common():
        print(f"  {speaker}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
