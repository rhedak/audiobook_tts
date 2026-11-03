"""Engine registry, PCM conversion, and the LocalEngine thread bridge.

Real model engines are not loaded here (they need model weights and optional
extras); their adapters are exercised by the manual comparison in the notes.
"""

import numpy as np
import pytest
from pydub import AudioSegment

from audiobook_tts import heteronyms
from audiobook_tts.build import build_chapter
from audiobook_tts.engines import ENGINE_NAMES, LocalEngine, get_engine, pcm_to_segment
from audiobook_tts.engines.edge import EdgeEngine


def test_pcm_to_segment_length_and_format():
    rate = 24_000
    samples = np.zeros(rate, dtype=np.float32)  # one second of silence
    seg = pcm_to_segment(samples, rate)
    assert seg.frame_rate == rate
    assert seg.channels == 1
    assert seg.sample_width == 2
    assert abs(len(seg) - 1000) <= 2


def test_pcm_to_segment_clips_out_of_range_samples():
    # Long enough that the splice fades do not reach the middle samples.
    loud = np.full(8_000, 2.0, dtype=np.float32)
    samples = pcm_to_segment(loud, 8_000).get_array_of_samples()
    assert max(samples) == 32767
    assert min(samples) >= -32768


def test_get_engine_returns_named_engine():
    assert get_engine("edge").name == "edge"
    assert get_engine("kokoro", speed=1.1).speed == 1.1


def test_get_engine_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown engine"):
        get_engine("nope")


def test_engine_names_match_registry():
    for name in ENGINE_NAMES:
        assert get_engine(name).name == name


class _FakeLocal(LocalEngine):
    name = "fake"
    default_voice = "v"

    def __init__(self):
        self.calls = []

    def _generate(self, text, voice):
        self.calls.append((text, voice))
        return AudioSegment.silent(duration=50)


async def test_local_engine_runs_generate_and_returns_segment():
    engine = _FakeLocal()
    seg = await engine.synthesize("hello", "v")
    assert engine.calls == [("hello", "v")]
    assert len(seg) == 50


async def test_edge_engine_delegates_to_synthesis(monkeypatch):
    seen = {}

    async def fake(text, voice):
        seen["args"] = (text, voice)
        return AudioSegment.silent(duration=10)

    monkeypatch.setattr("audiobook_tts.engines.edge.synthesize", fake)
    seg = await EdgeEngine().synthesize("hi", "en-GB-RyanNeural")
    assert seen["args"] == ("hi", "en-GB-RyanNeural")
    assert len(seg) == 10


@pytest.mark.skipif(
    not heteronyms.spacy_available(), reason="spaCy model not installed"
)
async def test_build_chapter_uses_given_engine_and_heteronyms(tmp_path):
    chapter = tmp_path / "ch01_test.md"
    chapter.write_text("# Chapter 1: Test\n\nI read the book yesterday.\n", encoding="utf-8")
    engine = _FakeLocal()
    out_dir = tmp_path / "out"

    await build_chapter(
        chapter, out_dir, "v", engine=engine, heteronyms=True, force=True
    )

    spoken = [text for text, _ in engine.calls]
    assert any("I red the book" in text for text in spoken), spoken
    assert (out_dir / "ch01_test.mp3").exists()
