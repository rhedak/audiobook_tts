# Changelog

## Unreleased

- `omnivoice` engine (OmniVoice 0.2.0): voice design from attributes, or a saved
  clone prompt per character. Optional extra `omnivoice`. Lives in its own
  environment; `uv.lock` records it as conflicting with `qwen` and `chatterbox`.

## 0.2.0

- Engine interface (`audiobook_tts.engines`): `edge` (default, unchanged
  behaviour), `kokoro`, `qwen` (Qwen3-TTS CustomVoice) and `chatterbox`.
  Select with `build_chapter(..., engine=get_engine("kokoro"))`.
- Context-aware heteronym respelling (`audiobook_tts.heteronyms`), using spaCy
  part-of-speech tags, so "I read it yesterday" and "I will read it" get
  different respellings. Opt in with `heteronyms=True`.
- `build_chapter` and `build_all` accept `engine` and `heteronyms`.
- Optional extras: `kokoro`, `qwen`, `chatterbox`, `heteronyms`.

## 0.1.0

- Initial edge-tts builder: chapters, pronunciations, multi-voice, ID3 tags,
  cover art.
