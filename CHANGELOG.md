# Changelog

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
