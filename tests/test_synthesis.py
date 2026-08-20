from pydub import AudioSegment, generators

from audiobook_tts.synthesis import _locate_real_onset


def _make_silence_then_tone(silence_ms: int, tone_ms: int = 500) -> AudioSegment:
    """Create audio with silence followed by a tone (simulates filler + real text)."""
    silence = AudioSegment.silent(duration=silence_ms)
    tone = generators.Sine(440).to_audio_segment(duration=tone_ms)
    return silence + tone


def test_locate_real_onset_after_silence():
    # 100ms silence then tone — onset should be near 100ms
    audio = _make_silence_then_tone(100)
    result = _locate_real_onset(audio, estimate_ms=80.0)
    assert 50 < result < 150


def test_locate_real_onset_overshoot():
    # Tone starts at 0ms but estimate overshoots to 50ms (into real speech)
    audio = _make_silence_then_tone(0)
    result = _locate_real_onset(audio, estimate_ms=50.0)
    # Should walk back toward the start
    assert result < 50


def test_locate_real_onset_pure_silence():
    # All silence — should return the estimate unchanged
    audio = AudioSegment.silent(duration=3000)
    result = _locate_real_onset(audio, estimate_ms=100.0)
    assert result == 100.0


def test_locate_real_onset_no_regression():
    # Basic case: silence then content, estimate before onset
    audio = _make_silence_then_tone(200)
    result = _locate_real_onset(audio, estimate_ms=150.0)
    assert 100 < result < 250
