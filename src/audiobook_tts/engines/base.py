"""Engine interface: one paragraph of text in, one ``AudioSegment`` out.

Every engine returns audio the same way, so the chapter builder can splice
clips from any engine without caring which one produced them.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import numpy as np
from pydub import AudioSegment

# Matches the splice smoothing in ``synthesis.py``: prevents clicks where
# clips join.
_SPLICE_FADE_MS = 15


def pcm_to_segment(samples: np.ndarray, sample_rate: int) -> AudioSegment:
    """Convert mono float samples in [-1, 1] to a 16-bit ``AudioSegment``."""
    flat = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = (np.clip(flat, -1.0, 1.0) * 32767).astype("<i2")
    segment = AudioSegment(
        data=pcm.tobytes(), sample_width=2, frame_rate=sample_rate, channels=1
    )
    return segment.fade_in(_SPLICE_FADE_MS).fade_out(_SPLICE_FADE_MS)


class Engine(ABC):
    """A text-to-speech backend.

    ``voice`` is engine-specific: an edge-tts voice name, a Kokoro preset, a
    Qwen speaker name, or a reference-audio path for Chatterbox cloning.
    """

    #: Registry key, also written to the build log.
    name: str
    #: Voice used when the caller does not pick one.
    default_voice: str

    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> AudioSegment:
        """Speak one paragraph and return it as audio."""


class LocalEngine(Engine):
    """Base for engines that run a model in-process.

    Model inference is blocking, so subclasses implement ``_generate`` and it
    runs in a worker thread, keeping the event loop free.
    """

    @abstractmethod
    def _generate(self, text: str, voice: str) -> AudioSegment:
        """Blocking synthesis of one paragraph."""

    async def synthesize(self, text: str, voice: str) -> AudioSegment:
        return await asyncio.to_thread(self._generate, text, voice)
