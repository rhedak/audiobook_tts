"""OmniVoice engine: voice-mode routing, using a fake model (no weights needed)."""

import numpy as np

from audiobook_tts.engines import get_engine
from audiobook_tts.engines.omnivoice import OMNIVOICE_SAMPLE_RATE, OmniVoiceEngine


class _FakeModel:
    def __init__(self):
        self.calls = []

    def generate(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return [np.zeros(OMNIVOICE_SAMPLE_RATE // 2, dtype=np.float32)]


def _engine_with_fake_model(**options):
    engine = OmniVoiceEngine(**options)
    engine._model = _FakeModel()
    return engine


def test_get_engine_returns_omnivoice_without_loading_model():
    engine = get_engine("omnivoice")
    assert engine.name == "omnivoice"
    assert engine._model is None


def test_empty_voice_uses_automatic_voice():
    engine = _engine_with_fake_model()
    seg = engine._generate("Hello there.", "")
    text, kwargs = engine._model.calls[0]
    assert text == "Hello there."
    assert kwargs == {}
    assert abs(len(seg) - 500) <= 2
    assert seg.frame_rate == OMNIVOICE_SAMPLE_RATE


def test_instruct_text_selects_voice_design():
    engine = _engine_with_fake_model()
    engine._generate("Hi.", "male, middle-aged, british accent")
    _, kwargs = engine._model.calls[0]
    assert kwargs == {"instruct": "male, middle-aged, british accent"}


def test_pt_path_selects_saved_clone_prompt(monkeypatch):
    engine = _engine_with_fake_model()
    sentinel = object()
    seen = {}

    def fake_clone_prompt(path):
        seen["path"] = path
        return sentinel

    monkeypatch.setattr(engine, "_clone_prompt", fake_clone_prompt)
    engine._generate("Hi.", "voices/mara.pt")
    _, kwargs = engine._model.calls[0]
    assert seen["path"] == "voices/mara.pt"
    assert kwargs == {"voice_clone_prompt": sentinel}


def test_num_step_is_passed_only_when_set():
    engine = _engine_with_fake_model(num_step=16)
    engine._generate("Hi.", "")
    _, kwargs = engine._model.calls[0]
    assert kwargs == {"num_step": 16}
