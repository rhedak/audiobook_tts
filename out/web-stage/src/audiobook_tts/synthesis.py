"""Paragraph-level TTS synthesis via edge-tts.

Implements the Valley of Mist's approach (strictly superior to Panzer
Island's simpler ``Communicate.save()``):

- **Streaming with onset-clip fix**: A disposable filler lead-in absorbs
  edge-tts's tendency to clip the first syllable of a fresh connection.
  WordBoundary metadata locates the real text's onset, verified against
  decoded audio.
- **Retry with backoff**: Transient network failures (``NoAudioReceived``,
  ``WebSocketError``, etc.) are retried up to 5 times with growing delay.
- **Splice smoothing**: 15 ms fade-in / fade-out on every clip prevents
  clicks at join points.
"""

import asyncio
import io
import re

import edge_tts
import edge_tts.exceptions
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

# --- Onset-clip fix --------------------------------------------------------
#
# edge-tts (via Azure Neural voices) reliably clips the first syllable of
# whatever it is asked to speak at the very start of a fresh synthesis
# connection.  The fix: prepend a disposable lead-in word, then cut its audio
# away before keeping the rest.

FILLER_LEAD_IN = "Test."

# FILLER_LEAD_IN ends in a voiceless stop ('t'), on purpose.  A trailing
# vowel's formants keep ringing past the WordBoundary metadata, while a stop
# closure cuts cleanly, so the gap after the filler is genuinely silent.

_FILLER_WORD_COUNT = len(FILLER_LEAD_IN.split())

# Silence-detection tuning for ``_locate_real_onset``.
ONSET_SILENCE_THRESHOLD_DBFS = -40.0
ONSET_SEARCH_WINDOW_MS = 2_000
ONSET_LEAD_PAD_MS = 30
ONSET_BACKWARD_STEP_MS = 10

# --- Splice smoothing ------------------------------------------------------

_SPLICE_FADE_MS = 15

# --- Retry -----------------------------------------------------------------
#
# The Azure endpoint behind edge-tts occasionally drops a request and closes
# the stream without ever sending audio.  It is transient: the same text
# sent again a moment later synthesizes fine.

_SYNTH_ATTEMPTS = 5
_SYNTH_RETRY_BASE_DELAY_S = 2.0

# The exceptions worth retrying (transient network / service issues).
_RETRYABLE_ERRORS = (
    edge_tts.exceptions.NoAudioReceived,
    edge_tts.exceptions.UnexpectedResponse,
    edge_tts.exceptions.UnknownResponse,
    edge_tts.exceptions.WebSocketError,
    ConnectionError,
    asyncio.TimeoutError,
)


def _locate_real_onset(audio: AudioSegment, estimate_ms: float) -> float:
    """Verify a WordBoundary-estimated cut point against the actual decoded
    audio, rather than trusting the metadata blindly.

    Two directions are possible:

    - The audio at the search start is silent: the estimate landed in (or
      before) the pause after the filler, so leading-silence detection walks
      forward to the first non-silent content and the cut is placed a pad
      before it.
    - The audio at the search start is already non-silent: the estimate
      overshot into real speech (the reported onset ran late), so the cut is
      walked backward to the start of the preceding silence instead of
      cutting into the real word.

    Falls back to the estimate, unmodified, if no onset is found within the
    search window or the backward walk finds no preceding silence.
    """
    search_start = max(0.0, estimate_ms - ONSET_LEAD_PAD_MS)
    window = audio[search_start : search_start + ONSET_SEARCH_WINDOW_MS]
    silence_ms = detect_leading_silence(
        window, silence_threshold=ONSET_SILENCE_THRESHOLD_DBFS, chunk_size=5
    )
    if silence_ms >= len(window):
        return estimate_ms
    if silence_ms > 0:
        onset_ms = search_start + silence_ms
        return max(0.0, onset_ms - ONSET_LEAD_PAD_MS)
    # Content starts at the window's first chunk: the estimate overshot into
    # real speech.  Walk backward to the start of the preceding silence.
    back_ms = search_start
    while back_ms > 0:
        back_ms = max(0.0, back_ms - ONSET_BACKWARD_STEP_MS)
        probe = audio[back_ms : back_ms + ONSET_SEARCH_WINDOW_MS]
        if detect_leading_silence(
            probe, silence_threshold=ONSET_SILENCE_THRESHOLD_DBFS, chunk_size=5
        ) > 0:
            return back_ms
    return search_start


async def _synthesize_once(text: str, voice: str) -> AudioSegment:
    """Synthesize one paragraph via edge-tts, with onset-clip risk absorbed
    by a disposable lead-in phrase.

    Requests WordBoundary metadata so the lead-in audio can be located and
    cut away.  The cut is anchored to the first real word's onset (the event
    right after the filler), not to the filler's own end, since the filler's
    acoustic length varies by voice while the real onset is a property of the
    text itself.

    The WordBoundary-based estimate is then verified against the actual
    decoded audio via ``_locate_real_onset``.

    A 15 ms fade-in / fade-out smooths splice points.
    """
    comm = edge_tts.Communicate(f"{FILLER_LEAD_IN} {text}", voice, boundary="WordBoundary")
    audio_bytes = bytearray()
    word_boundaries_seen = 0
    real_onset_ms: float | None = None

    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            word_boundaries_seen += 1
            if word_boundaries_seen == _FILLER_WORD_COUNT + 1:
                real_onset_ms = chunk["offset"] / 10_000

    audio = AudioSegment.from_file(io.BytesIO(bytes(audio_bytes)), format="mp3")
    if real_onset_ms is not None:
        estimate_ms = max(0.0, real_onset_ms - ONSET_LEAD_PAD_MS)
        cut_ms = _locate_real_onset(audio, estimate_ms)
        audio = audio[cut_ms:]
    return audio.fade_in(_SPLICE_FADE_MS).fade_out(_SPLICE_FADE_MS)


async def synthesize(text: str, voice: str) -> AudioSegment:
    """Synthesize one paragraph, retrying transient edge-tts failures.

    Only the network-ish edge-tts exceptions are retried; anything else
    (a bad voice name, a bug) is a real error and surfaces immediately.
    """
    for attempt in range(1, _SYNTH_ATTEMPTS + 1):
        try:
            return await _synthesize_once(text, voice)
        except _RETRYABLE_ERRORS as exc:
            if attempt == _SYNTH_ATTEMPTS:
                raise
            delay = _SYNTH_RETRY_BASE_DELAY_S * attempt
            print(
                f"    retry {attempt}/{_SYNTH_ATTEMPTS - 1} after {type(exc).__name__} "
                f"(waiting {delay:.0f}s): {text[:60]!r}..."
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")
