from pathlib import Path

from audiobook_tts.chapters import chapter_files, resolve, select_chapter, sort_key


def test_sort_key_basic():
    assert sort_key("ch01_intro.md") == (1, 0, "ch01_intro.md")


def test_sort_key_split():
    assert sort_key("ch07-2_second.md") == (7, 2, "ch07-2_second.md")


def test_sort_key_non_chapter():
    assert sort_key("_pronunciation_test.mp3") == (0, 0, "_pronunciation_test.mp3")


def test_sort_key_ordering():
    names = ["ch02_b.md", "ch01_a.md", "ch01-2_a2.md"]
    result = sorted(names, key=sort_key)
    assert result == ["ch01_a.md", "ch01-2_a2.md", "ch02_b.md"]


def test_chapter_files_basic(tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch01_intro.md").write_text("Intro")
    (chapters / "ch02_body.md").write_text("Body")
    (chapters / "ch01_intro_notes.md").write_text("Notes")

    result = chapter_files(chapters)
    assert [f.name for f in result] == ["ch01_intro.md", "ch02_body.md"]


def test_chapter_files_with_notes_excluded(tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch01_intro.md").write_text("Intro")
    (chapters / "ch01_intro_notes.md").write_text("Notes")

    result = chapter_files(chapters)
    assert len(result) == 1
    assert result[0].name == "ch01_intro.md"


def test_chapter_files_with_fork(tmp_path):
    base = tmp_path / "base"
    base_chapters = base / "chapters"
    base_chapters.mkdir(parents=True)
    (base_chapters / "ch01_intro.md").write_text("Base intro")
    (base_chapters / "ch02_body.md").write_text("Base body")

    fork = tmp_path / "fork"
    fork_chapters = fork / "chapters"
    fork_chapters.mkdir(parents=True)
    (fork_chapters / "ch02_body.md").write_text("Fork body")
    (fork_chapters / "ch03_extra.md").write_text("Fork extra")

    result = chapter_files(base_chapters, fork_dir=fork)
    names = [f.name for f in result]
    assert names == ["ch01_intro.md", "ch02_body.md", "ch03_extra.md"]
    # ch02_body should be the fork version
    assert result[1].read_text() == "Fork body"
    # ch01_intro should be the base version
    assert result[0].read_text() == "Base intro"


def test_resolve_fork_first(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "style-anchors" / "cover.png").mkdir(parents=True)
    (base / "style-anchors" / "cover.png" / "file.png").write_bytes(b"base")

    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "style-anchors" / "cover.png").mkdir(parents=True)
    (fork / "style-anchors" / "cover.png" / "file.png").write_bytes(b"fork")

    # When fork has the asset, return fork's copy
    result = resolve("style-anchors/cover.png/file.png", base, fork)
    assert result.parent == fork / "style-anchors" / "cover.png"


def test_resolve_falls_back_to_base(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "img.png").write_bytes(b"base")

    fork = tmp_path / "fork"
    fork.mkdir()

    result = resolve("img.png", base, fork)
    assert result == base / "img.png"


def test_resolve_no_fork(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "img.png").write_bytes(b"base")

    result = resolve("img.png", base)
    assert result == base / "img.png"


def test_select_chapter_bare_number(tmp_path):
    chapters = [
        tmp_path / "ch01_intro.md",
        tmp_path / "ch13_big.md",
        tmp_path / "ch14_end.md",
    ]
    result = select_chapter(chapters, "13")
    assert len(result) == 1
    assert result[0].name == "ch13_big.md"


def test_select_chapter_stem(tmp_path):
    chapters = [
        tmp_path / "ch01_intro.md",
        tmp_path / "ch13_big.md",
    ]
    result = select_chapter(chapters, "ch13")
    assert len(result) == 1
    assert result[0].name == "ch13_big.md"


def test_select_chapter_full_stem_prefix_matches(tmp_path):
    chapters = [
        tmp_path / "ch13_big.md",
        tmp_path / "ch13_big_part2.md",
    ]
    result = select_chapter(chapters, "ch13_big")
    assert len(result) == 2


def test_select_chapter_no_match(tmp_path):
    chapters = [tmp_path / "ch01_intro.md"]
    result = select_chapter(chapters, "99")
    assert result == []
