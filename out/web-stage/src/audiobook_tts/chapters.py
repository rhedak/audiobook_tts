"""Chapter-file discovery for audiobook builds.

Discovers ``ch*.md`` chapter files in publication order, with support for:
- Split chapters (``ch{NN}-2_{slug}.md``)
- Delta forks via a fork directory override (a fork chapter sharing a
  filename with a base chapter takes precedence)

All paths are caller-supplied rather than hardcoded, so this module works
from any project root.
"""

import re
from pathlib import Path

# Chapter filenames are ch{NN}_{slug}.md, or ch{NN}-2_{slug}.md for a
# chapter split's second half. Plain lexical sort puts "-2" ahead of "_"
# (ASCII '-' 0x2D < '_' 0x5F), so ch07-2_... would sort *before* ch07_...
# instead of after it. Sort by (chapter number, split suffix) instead so a
# split's second half always follows its first half and still precedes the
# next chapter number.
_SORT_KEY_RE = re.compile(r"^ch(\d+)(?:-(\d+))?")


def sort_key(name: str) -> tuple[int, int, str]:
    """Sort key for chapter filenames, handling split chapters correctly."""
    match = _SORT_KEY_RE.match(name)
    if not match:
        return (0, 0, name)
    number = int(match.group(1))
    suffix = int(match.group(2)) if match.group(2) else 0
    return (number, suffix, name)


def chapter_files(chapters_dir: Path, fork_dir: Path | None = None) -> list[Path]:
    """Draft chapter files in publication order, notes files excluded.

    When *fork_dir* is provided its chapters are merged with the base
    *chapters_dir*: a fork chapter sharing a base filename takes precedence,
    and chapters that only exist on one side are kept from that side.
    """
    files = sorted(
        (f for f in chapters_dir.glob("ch*.md") if "_notes" not in f.name),
        key=lambda f: sort_key(f.name),
    )
    if fork_dir is None:
        return files
    by_name = {f.name: f for f in files}
    for f in (fork_dir / "chapters").glob("ch*.md"):
        if "_notes" not in f.name:
            by_name[f.name] = f
    # Sort by filename, not by the Path objects themselves: a fork chapter's
    # full path lives under a different directory root than a base chapter's
    # (.../tragic_hero/chapters/... vs .../chapters/...), and Path ordering
    # compares path parts, so sorting the Paths directly would group all
    # base-rooted chapters before all fork-rooted ones instead of
    # interleaving them by chapter number.
    return [by_name[name] for name in sorted(by_name, key=sort_key)]


def resolve(relative: str, base_root: Path, fork_root: Path | None = None) -> Path:
    """The fork's copy of *relative* if it exists there, else the base's."""
    if fork_root is not None:
        candidate = fork_root / relative
        if candidate.exists():
            return candidate
    return base_root / relative


def select_chapter(chapters: list[Path], selector: str) -> list[Path]:
    """Filter chapter files down to the one matching *selector*.

    Accepts a bare number ("13"), a chapter stem ("ch13"), or a full stem
    ("ch13_rubble_that_argues"). Matching is prefix-based against the
    zero-padded "chNN" form so a bare number is enough in the common case.
    """
    normalized = selector.strip().lower()
    if normalized.isdigit():
        normalized = f"ch{int(normalized):02d}"
    elif not normalized.startswith("ch"):
        normalized = f"ch{normalized}"

    return [
        p
        for p in chapters
        if p.stem == normalized or p.stem.startswith(f"{normalized}_")
    ]
