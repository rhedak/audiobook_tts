"""Chatterbox (Resemble AI, MIT code) via the ``chatterbox-tts`` package.

``voice`` is either empty (the bundled default voice) or a path to a short
reference recording to clone. Only clone a voice you have the right to use.
Output carries an imperceptible Perth watermark added by the library.

Needs its own environment: it pins transformers versions that conflict with
``qwen-tts``.
"""

from __future__ import annotations

from pydub import AudioSegment

from audiobook_tts.engines.base import LocalEngine, pcm_to_segment


class ChatterboxEngine(LocalEngine):
    name = "chatterbox"
    default_voice = ""

    def __init__(self, device: str = "mps") -> None:
        self.device = device
        self._model = None

    def _load(self):
        if self._model is None:
            from chatterbox.tts import ChatterboxTTS

            self._model = ChatterboxTTS.from_pretrained(device=self.device)
        return self._model

    def _generate(self, text: str, voice: str) -> AudioSegment:
        model = self._load()
        wav = model.generate(text, audio_prompt_path=voice or None)
        return pcm_to_segment(wav.squeeze(0).cpu().numpy(), model.sr)
