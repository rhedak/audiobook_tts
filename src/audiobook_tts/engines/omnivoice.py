"""OmniVoice (k2-fsa, Apache-2.0 code) via the ``omnivoice`` package (local).

``voice`` selects one of three modes, so each character can have its own:

- ``""`` (empty): the model picks a voice automatically.
- a path ending in ``.pt``: a saved clone prompt, made once with
  ``OmniVoiceEngine.save_clone_prompt`` from a short reference recording. Use
  the same file for every chapter so the voice stays consistent.
- any other text: a voice-design description such as
  ``"male, middle-aged, moderate pitch, british accent"``.

Needs its own environment: ``omnivoice`` pins transformers versions that
differ from ``qwen-tts`` and ``chatterbox-tts``.
"""

from __future__ import annotations

from pathlib import Path

from pydub import AudioSegment

from audiobook_tts.engines.base import LocalEngine, pcm_to_segment

OMNIVOICE_SAMPLE_RATE = 24_000


class OmniVoiceEngine(LocalEngine):
    name = "omnivoice"
    default_voice = ""

    def __init__(
        self,
        model_id: str = "k2-fsa/OmniVoice",
        device: str = "mps",
        num_step: int | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device
        # Diffusion steps; None keeps the model default (32). 16 is faster.
        self.num_step = num_step
        self._model = None
        self._prompts: dict[str, object] = {}

    def _load(self):
        if self._model is None:
            import torch
            from omnivoice import OmniVoice

            # float32 is the precision the local comparison was run at on MPS.
            self._model = OmniVoice.from_pretrained(
                self.model_id, device_map=self.device, dtype=torch.float32
            )
        return self._model

    def save_clone_prompt(self, ref_audio: str, ref_text: str, out_path: str) -> None:
        """Encode a reference recording once and save it for reuse.

        *ref_text* is the exact transcript of *ref_audio*. Keep the clip to 3-10 seconds.
        """
        import torch

        prompt = self._load().create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text)
        # omnivoice 0.2.0's VoiceClonePrompt is a plain dataclass with no save(),
        # so store its fields and rebuild it on load.
        torch.save(
            {
                "ref_audio_tokens": prompt.ref_audio_tokens,
                "ref_text": prompt.ref_text,
                "ref_rms": prompt.ref_rms,
            },
            out_path,
        )

    def _clone_prompt(self, path: str):
        if path not in self._prompts:
            import torch
            from omnivoice.models.omnivoice import VoiceClonePrompt

            fields = torch.load(path, map_location="cpu", weights_only=False)
            self._prompts[path] = VoiceClonePrompt(**fields)
        return self._prompts[path]

    def _generate(self, text: str, voice: str) -> AudioSegment:
        model = self._load()
        kwargs: dict[str, object] = {}
        if self.num_step is not None:
            kwargs["num_step"] = self.num_step
        if voice == "":
            pass
        elif voice.endswith(".pt"):
            kwargs["voice_clone_prompt"] = self._clone_prompt(str(Path(voice).expanduser()))
        else:
            kwargs["instruct"] = voice
        audio = model.generate(text=text, **kwargs)
        return pcm_to_segment(audio[0], OMNIVOICE_SAMPLE_RATE)
