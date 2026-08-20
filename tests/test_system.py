"""System tests for the audiobook_tts package.

Exercises the full build pipeline with mock chapter files, mocking only the
edge-tts synthesis call (which requires network).  Tests both single-voice
(Valley of Mist style) and multi-voice (Panzer Island style) modes.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydub import AudioSegment

from audiobook_tts.build import build_all, build_chapter
from audiobook_tts.chapters import chapter_files
from audiobook_tts.text import apply_pronunciations

FIXTURES = Path(__file__).parent / "fixtures" / "chapters"

# --- Pronunciation dicts (project-specific) ---

VOM_PRONUNCIATIONS: dict[str, str] = {
    "Wodensreich": "woh-dens-ryech",
    "Nebelmark": "nay-bel-mark",
    "Okiri": "oh-ki-ree",
    "Satoko": "Sah-toh-koh",
    "Kiriguchi": "ki-ri-gu-chee",
}

PI_PRONUNCIATIONS: dict[str, str] = {
    "katyusha": "Kaht-u-sha",
    "Dr. E.": "Doctor E ",
    "Doc.": "Doc ",
}

PI_SPEAKER_VOICES: dict[str, str] = {
    "Erika": "en-US-JennyNeural",
    "Katyusha": "en-US-AvaNeural",
    "Nadeshiko": "en-US-AriaNeural",
    "Maria": "en-US-EmmaNeural",
    "Drona": "en-US-MichelleNeural",
}


def _fake_audio(duration_ms: int = 500) -> AudioSegment:
    """Create a silent AudioSegment as a stand-in for synthesized speech."""
    return AudioSegment.silent(duration=duration_ms)


async def _mock_synthesize(text: str, voice: str) -> AudioSegment:
    """Async stand-in for audiobook_tts.synthesis.synthesize."""
    return _fake_audio(500)


# --- Single-voice tests (Valley of Mist convention) ---


class TestSingleVoiceBuild:
    """Tests the VOM-style single-voice build pipeline."""

    @pytest.fixture()
    def out_dir(self, tmp_path):
        return tmp_path / "build" / "audiobook"

    def test_chapter_files_discovered(self):
        chs = chapter_files(FIXTURES)
        names = [c.name for c in chs]
        assert "ch01_the_briefing.md" in names
        assert "ch01_the_wound_in_the_wall.md" in names

    def test_pronunciations_applied_vom(self):
        text = "She stood in Wodensreich territory."
        result = apply_pronunciations(text, VOM_PRONUNCIATIONS)
        assert "woh-dens-ryech" in result
        assert "Wodensreich" not in result

    @pytest.mark.asyncio
    async def test_build_single_voice_chapter(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chapter = FIXTURES / "ch01_the_wound_in_the_wall.md"

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_chapter(
                chapter,
                out_dir,
                voice="en-US-AndrewNeural",
                pronunciations=VOM_PRONUNCIATIONS,
                force=True,
            )

        out_file = out_dir / "ch01_the_wound_in_the_wall.mp3"
        assert out_file.exists()
        assert out_file.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_build_skips_existing_without_force(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        out_dir.mkdir(parents=True)
        chapter = FIXTURES / "ch01_the_wound_in_the_wall.md"
        mp3 = out_dir / "ch01_the_wound_in_the_wall.mp3"
        mp3.write_bytes(b"fake-existing")

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_chapter(
                chapter,
                out_dir,
                voice="en-US-AndrewNeural",
                force=False,
            )

        # Should not have been rebuilt
        assert mp3.read_bytes() == b"fake-existing"
        mock_synth.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_respects_force_flag(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        out_dir.mkdir(parents=True)
        chapter = FIXTURES / "ch01_the_wound_in_the_wall.md"
        mp3 = out_dir / "ch01_the_wound_in_the_wall.mp3"
        mp3.write_bytes(b"fake-existing")

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_chapter(
                chapter,
                out_dir,
                voice="en-US-AndrewNeural",
                force=True,
            )

        assert mp3.read_bytes() != b"fake-existing"
        mock_synth.assert_called()

    @pytest.mark.asyncio
    async def test_build_single_voice_with_cover(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chapter = FIXTURES / "ch01_the_wound_in_the_wall.md"

        # Create a tiny valid PNG (1x1 pixel)
        cover = tmp_path / "cover.png"
        import struct
        import zlib

        def minimal_png():
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr = _chunk(b"IHDR", ihdr_data)
            raw = b"\x00\x00\x00\x00"
            idat = _chunk(b"IDAT", zlib.compress(raw))
            iend = _chunk(b"IEND", b"")
            return sig + ihdr + idat + iend

        def _chunk(chunk_type, data):
            c = chunk_type + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        cover.write_bytes(minimal_png())

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_chapter(
                chapter,
                out_dir,
                voice="en-US-AndrewNeural",
                cover_image=cover,
                force=True,
            )

        out_file = out_dir / "ch01_the_wound_in_the_wall.mp3"
        assert out_file.exists()
        # Verify ID3 tags were written (cover embedded)
        from mutagen.mp3 import MP3
        audio = MP3(str(out_file))
        assert audio.tags is not None


# --- Multi-voice tests (Panzer Island convention) ---


class TestMultiVoiceBuild:
    """Tests the Panzer Island-style multi-voice build pipeline."""

    @pytest.fixture()
    def out_dir(self, tmp_path):
        return tmp_path / "build" / "audiobook"

    def test_speaker_tags_detected(self):
        from audiobook_tts.speakers import split_speaker_segments

        chapter = FIXTURES / "ch01_the_briefing.md"
        content = chapter.read_text()
        segments = split_speaker_segments(content, default_speaker="Erika")

        speakers = [s for s, _ in segments]
        assert "Erika" in speakers
        assert "Katyusha" in speakers
        assert "Maria" in speakers
        assert "Drona" in speakers

    def test_attribution_stripping(self):
        from audiobook_tts.speakers import split_speaker_segments

        chapter = FIXTURES / "ch01_the_briefing.md"
        content = chapter.read_text()
        segments = split_speaker_segments(content, default_speaker="Erika")

        for speaker, text in segments:
            # No segment should start with its own speaker name followed by a colon
            assert not text.startswith(f"{speaker}:"), (
                f"Speaker attribution not stripped for '{speaker}': {text[:60]!r}"
            )

    def test_pronunciations_applied_pi(self):
        text = "Katyusha read the document. Dr. E. signed it."
        result = apply_pronunciations(text, PI_PRONUNCIATIONS)
        assert "Kaht-u-sha" in result
        assert "Doctor E " in result

    @pytest.mark.asyncio
    async def test_build_multi_voice_chapter(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chapter = FIXTURES / "ch01_the_briefing.md"

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_chapter(
                chapter,
                out_dir,
                voice="en-US-JennyNeural",
                pronunciations=PI_PRONUNCIATIONS,
                speaker_voices=PI_SPEAKER_VOICES,
                default_speaker="Erika",
                force=True,
            )

        out_file = out_dir / "ch01_the_briefing.mp3"
        assert out_file.exists()
        assert out_file.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_build_multi_voice_calls_different_voices(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chapter = FIXTURES / "ch01_the_briefing.md"

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_chapter(
                chapter,
                out_dir,
                voice="en-US-JennyNeural",
                pronunciations=PI_PRONUNCIATIONS,
                speaker_voices=PI_SPEAKER_VOICES,
                default_speaker="Erika",
                force=True,
            )

        # Check that multiple different voices were used
        voices_used = {call.args[1] for call in mock_synth.call_args_list}
        assert len(voices_used) > 1, "Multi-voice build should use more than one voice"
        assert "en-US-AvaNeural" in voices_used  # Katyusha's voice


# --- build_all integration tests ---


class TestBuildAll:
    """Tests the full build_all pipeline with both conventions."""

    @pytest.mark.asyncio
    async def test_build_all_single_voice(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chs = chapter_files(FIXTURES)
        # Only build the VOM chapter
        vom_chapters = [c for c in chs if "wound" in c.name]

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_all(
                vom_chapters,
                out_dir,
                voice="en-US-AndrewNeural",
                pronunciations=VOM_PRONUNCIATIONS,
                force=True,
            )

        assert (out_dir / "ch01_the_wound_in_the_wall.mp3").exists()

    @pytest.mark.asyncio
    async def test_build_all_multi_voice(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chs = chapter_files(FIXTURES)
        pi_chapters = [c for c in chs if "briefing" in c.name]

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_all(
                pi_chapters,
                out_dir,
                voice="en-US-JennyNeural",
                pronunciations=PI_PRONUNCIATIONS,
                speaker_voices=PI_SPEAKER_VOICES,
                default_speaker="Erika",
                force=True,
            )

        assert (out_dir / "ch01_the_briefing.mp3").exists()

    @pytest.mark.asyncio
    async def test_build_all_with_selector(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        chs = chapter_files(FIXTURES)

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_all(
                chs,
                out_dir,
                voice="en-US-AndrewNeural",
                selector="ch01_the_wound",
                force=True,
            )

        # Only the matching chapter should be built
        mp3_files = list(out_dir.glob("*.mp3"))
        assert len(mp3_files) == 1
        assert "wound" in mp3_files[0].name

    @pytest.mark.asyncio
    async def test_build_all_empty_chapter_skipped(self, tmp_path):
        out_dir = tmp_path / "audiobook"
        # Create a chapter with only punctuation (not speakable)
        empty = tmp_path / "ch99_empty.md"
        empty.write_text("---\n\n...\n\n---\n\n")

        with patch("audiobook_tts.build.synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = _mock_synthesize
            await build_all(
                [empty],
                out_dir,
                voice="en-US-AndrewNeural",
                force=True,
            )

        # Empty chapter should be skipped, no MP3 created
        mp3_files = list(out_dir.glob("*.mp3"))
        assert len(mp3_files) == 0
