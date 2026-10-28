"""Qwen3-TTS CustomVoice models via the ``qwen-tts`` package (local).

Voices are preset speaker names (``ryan``, ``aiden``, ...). Run
``QwenEngine().voices()`` to list them for the installed model.
"""

from __future__ import annotations

from pydub import AudioSegment

from audiobook_tts.engines.base import LocalEngine, pcm_to_segment


class QwenEngine(LocalEngine):
    name = "qwen"
    default_voice = "ryan"

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        device: str = "mps",
        language: str = "English",
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.language = language
        self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from qwen_tts import Qwen3TTSModel

            # float32 is the precision the local comparison was run at on MPS.
            self._model = Qwen3TTSModel.from_pretrained(
                self.model_id, device_map=self.device, dtype=torch.float32
            )
        return self._model

    def voices(self) -> list[str]:
        return list(self._load().get_supported_speakers() or [])

    def _generate(self, text: str, voice: str) -> AudioSegment:
        wavs, sample_rate = self._load().generate_custom_voice(
            text=text, speaker=voice, language=self.language
        )
        return pcm_to_segment(wavs[0], sample_rate)
