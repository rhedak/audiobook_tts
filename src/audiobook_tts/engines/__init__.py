"""Pluggable text-to-speech engines.

Each engine imports its own heavy dependencies lazily, so importing this
package never loads a model or requires an optional extra.
"""

from audiobook_tts.engines.base import Engine, LocalEngine, pcm_to_segment

__all__ = ["Engine", "LocalEngine", "get_engine", "pcm_to_segment", "ENGINE_NAMES"]

ENGINE_NAMES = ("edge", "kokoro", "qwen", "chatterbox")


def get_engine(name: str, **options) -> Engine:
    """Return a new engine instance by registry name.

    *options* are passed to the engine constructor (e.g. ``speed`` for Kokoro,
    ``device`` for the local models).
    """
    if name == "edge":
        from audiobook_tts.engines.edge import EdgeEngine

        return EdgeEngine(**options)
    if name == "kokoro":
        from audiobook_tts.engines.kokoro import KokoroEngine

        return KokoroEngine(**options)
    if name == "qwen":
        from audiobook_tts.engines.qwen import QwenEngine

        return QwenEngine(**options)
    if name == "chatterbox":
        from audiobook_tts.engines.chatterbox import ChatterboxEngine

        return ChatterboxEngine(**options)
    raise ValueError(f"unknown engine {name!r}; expected one of {', '.join(ENGINE_NAMES)}")
