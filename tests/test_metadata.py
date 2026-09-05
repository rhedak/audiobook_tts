"""Tests for ID3 text metadata (title / album / artist / track)."""

import struct
import zlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mutagen.mp3 import MP3
from pydub import AudioSegment

from audiobook_tts.build import build_all, build_chapter
from audiobook_tts.metadata import chapter_title, chapter_track, write_tags


def _minimal_png(path: Path) -> None:
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


async def _mock_synthesize(text: str, voice: str) -> AudioSegment:
    return AudioSegment.silent(duration=400)


class TestChapterTitle:
    def test_strips_chapter_number_prefix(self):
        assert chapter_title("# Chapter 3: Behind the Water\n\nText.", "ch03_x") == "Behind the Water"

    def test_strips_roman_numeral_prefix(self):
        assert chapter_title("# Chapter IV - The Picket\n", "ch04_x") == "The Picket"

    def test_plain_heading_kept_as_is(self):
        assert chapter_title("# Light\n\nText.", "ch06_light") == "Light"

    def test_falls_back_to_slug_when_no_heading(self):
        assert chapter_title("Just prose, no heading.\n", "ch02_the_way_back") == "The Way Back"

    def test_heading_must_be_first_non_blank_line(self):
        # A '#' deeper in the file is not a title.
        assert chapter_title("Prose first.\n\n# Not A Title\n", "ch01_the_second_telling") == (
            "The Second Telling"
        )


class TestChapterTrack:
    def test_parses_number(self):
        assert chapter_track("ch07_rubble") == 7

    def test_split_chapter_shares_number(self):
        assert chapter_track("ch07-2_rubble") == 7

    def test_non_chapter_stem(self):
        assert chapter_track("prologue") is None


class TestWriteTags:
    def test_writes_requested_frames_only(self, tmp_path):
        mp3 = tmp_path / "x.mp3"
        AudioSegment.silent(duration=300).export(str(mp3), format="mp3")
        write_tags(mp3, title="Light", album="The Everglow Crystals", artist="rhedak", track=6, track_total=6)

        tags = MP3(str(mp3))
        assert str(tags["TIT2"]) == "Light"
        assert str(tags["TALB"]) == "The Everglow Crystals"
        assert str(tags["TPE1"]) == "rhedak"
        assert str(tags["TRCK"]) == "6/6"

    def test_noop_when_all_none(self, tmp_path):
        mp3 = tmp_path / "x.mp3"
        AudioSegment.silent(duration=300).export(str(mp3), format="mp3")
        write_tags(mp3)
        tags = MP3(str(mp3)).tags
        assert tags is None or not any(
            k.startswith(("TIT2", "TALB", "TPE1", "TRCK")) for k in tags.keys()
        )

    def test_preserves_existing_cover(self, tmp_path):
        from audiobook_tts.cover import embed_cover

        mp3 = tmp_path / "x.mp3"
        AudioSegment.silent(duration=300).export(str(mp3), format="mp3")
        cover = tmp_path / "cover.png"
        _minimal_png(cover)
        embed_cover(mp3, cover)
        write_tags(mp3, title="Light", album="Book")

        tags = MP3(str(mp3))
        assert any(k.startswith("APIC") for k in tags.keys())
        assert str(tags["TIT2"]) == "Light"


class TestBuildIntegration:
    @pytest.mark.asyncio
    async def test_build_chapter_derives_title_and_track(self, tmp_path):
        chapter = tmp_path / "ch05_the_edge_of_the_light.md"
        chapter.write_text("# Chapter 5: The Edge of the Light\n\nEwald was quick.\n")
        out_dir = tmp_path / "audiobook"

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as m:
            m.side_effect = _mock_synthesize
            await build_chapter(
                chapter, out_dir, voice="en-US-AndrewNeural", force=True,
                album="The Everglow Crystals", artist="rhedak",
            )

        tags = MP3(str(out_dir / "ch05_the_edge_of_the_light.mp3"))
        assert str(tags["TIT2"]) == "The Edge of the Light"
        assert str(tags["TALB"]) == "The Everglow Crystals"
        assert str(tags["TPE1"]) == "rhedak"
        assert str(tags["TRCK"]) == "5"

    @pytest.mark.asyncio
    async def test_build_all_numbers_tracks_by_position(self, tmp_path):
        for n, slug in ((1, "opening"), (2, "middle"), (3, "closing")):
            (tmp_path / f"ch0{n}_{slug}.md").write_text(f"# Chapter {n}: {slug.title()}\n\nWords here.\n")
        chapters = sorted(tmp_path.glob("ch*.md"))
        out_dir = tmp_path / "audiobook"

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as m:
            m.side_effect = _mock_synthesize
            await build_all(chapters, out_dir, voice="en-US-AndrewNeural", force=True, album="Trilogy")

        assert str(MP3(str(out_dir / "ch02_middle.mp3"))["TRCK"]) == "2/3"
