"""Kokoro-82M via the ``kokoro`` package (Apache-2.0 weights, local).

Voices are preset names; the first letter is the language code, e.g.
``am_michael`` (American English) or ``bm_george`` (British English).
"""

from __future__ import annotations

import numpy as np
from pydub import AudioSegment

from audiobook_tts.engines.base import LocalEngine, pcm_to_segment

KOKORO_SAMPLE_RATE = 24_000


class KokoroEngine(LocalEngine):
    name = "kokoro"
    default_voice = "am_michael"

    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed
        self._pipelines: dict[str, object] = {}

    def _pipeline(self, voice: str):
        lang = voice[0]
        if lang not in self._pipelines:
            from kokoro import KPipeline  # heavy import, kept lazy

            self._pipelines[lang] = KPipeline(lang_code=lang)
        return self._pipelines[lang]

    def _generate(self, text: str, voice: str) -> AudioSegment:
        chunks = [
            audio
            for _, _, audio in self._pipeline(voice)(text, voice=voice, speed=self.speed)
        ]
        if not chunks:
            return AudioSegment.silent(duration=0)
        return pcm_to_segment(np.concatenate(chunks), KOKORO_SAMPLE_RATE)
