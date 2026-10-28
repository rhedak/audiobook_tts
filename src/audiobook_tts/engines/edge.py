"""Microsoft Neural voices via edge-tts (the library's original engine).

Uses the unofficial Read Aloud endpoint. Check its terms before publishing.
"""

from __future__ import annotations

from pydub import AudioSegment

from audiobook_tts.engines.base import Engine
from audiobook_tts.synthesis import synthesize


class EdgeEngine(Engine):
    name = "edge"
    default_voice = "en-US-AndrewNeural"

    async def synthesize(self, text: str, voice: str) -> AudioSegment:
        return await synthesize(text, voice)
