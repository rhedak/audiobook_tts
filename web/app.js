/**
 * app.js — Main UI logic for the Audiobook TTS Builder.
 *
 * Loads Pyodide for text processing, uses edge-tts.js for synthesis,
 * and manages the full upload-configure-build-download pipeline.
 */

const PACKAGE_FILES = [
  "src/audiobook_tts/__init__.py",
  "src/audiobook_tts/text.py",
  "src/audiobook_tts/chapters.py",
  "src/audiobook_tts/speakers.py",
];

// Stub __init__.py for Pyodide: avoids importing build/synthesis/cover
// which need edge-tts, mutagen, pydub — unavailable in the browser.
const PYODIDE_INIT_PY = `"""audiobook-tts (browser stub — text processing only)."""
__version__ = "0.1.0"
`;

// --- State ---
const state = {
  chapters: [],         // [{name, content, result: null}]
  pronunciations: {},   // {word: phonetic}
  speakerVoices: {},    // {speaker: voiceName}
  selectedVoice: "en-US-EmmaMultilingualNeural",
  multiVoice: true,
  building: false,
  audioResults: {},     // {chapterName: Blob}
  voices: [],           // fetched voice list
};

let bridge = null;

// --- DOM refs ---
const statusEl = document.getElementById("status");
const uploadSection = document.getElementById("upload-section");
const editorSection = document.getElementById("editor-section");
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const pasteTitle = document.getElementById("paste-title");
const pasteText = document.getElementById("paste-text");
const addPasteBtn = document.getElementById("add-paste-btn");
const chapterItems = document.getElementById("chapter-items");
const chapterList = document.getElementById("chapter-list");
const uploadActions = document.getElementById("upload-actions");
const toConfigBtn = document.getElementById("to-config-btn");
const voiceSelect = document.getElementById("voice-select");
const multiVoiceCheck = document.getElementById("multi-voice-check");
const speakerFieldset = document.getElementById("speaker-fieldset");
const speakerVoiceList = document.getElementById("speaker-voice-list");
const addSpeakerBtn = document.getElementById("add-speaker-btn");
const pronunciationList = document.getElementById("pronunciation-list");
const addPronunciationBtn = document.getElementById("add-pronunciation-btn");
const buildBtn = document.getElementById("build-btn");
const downloadAllBtn = document.getElementById("download-all-btn");
const exportConfigBtn = document.getElementById("export-config-btn");
const importConfigBtn = document.getElementById("import-config-btn");
const configFileInput = document.getElementById("config-file-input");
const buildProgress = document.getElementById("build-progress");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const chapterStatus = document.getElementById("chapter-status");
const previewChapterSelect = document.getElementById("preview-chapter-select");
const previewContent = document.getElementById("preview-content");
const backToUpload = document.getElementById("back-to-upload");

// --- Status helpers ---

function showStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.className = isError ? "visible error" : "visible";
}

function hideStatus() {
  statusEl.className = "";
}

// --- Pyodide loading ---

async function initPyodide() {
  showStatus("Loading Python runtime...");
  try {
    if (typeof loadPyodide === "undefined") {
      throw new Error("Pyodide failed to load from CDN. Check your internet connection and reload the page.");
    }
    const pyodide = await loadPyodide();
    console.log("Pyodide loaded");

    // Fetch and install package files (skip __init__.py — we write a stub)
    for (const path of PACKAGE_FILES) {
      if (path.endsWith("__init__.py")) continue;
      console.log("Fetching", path);
      const resp = await fetch(path);
      if (!resp.ok) throw new Error(`Failed to fetch ${path}: ${resp.status}`);
      const code = await resp.text();
      console.log("Fetched", path, "(", code.length, "bytes)");

      // Write into Pyodide's default filesystem location
      const fsPath = "/home/pyodide/" + path;
      const dir = fsPath.substring(0, fsPath.lastIndexOf("/"));
      pyodide.FS.mkdirTree(dir);
      pyodide.FS.writeFile(fsPath, code);
    }

    // Write stub __init__.py (skips heavy imports unavailable in browser)
    const initPath = "/home/pyodide/src/audiobook_tts/__init__.py";
    pyodide.FS.writeFile(initPath, PYODIDE_INIT_PY);
    console.log("All package files written");

    // Fetch and execute bridge
    const bridgeResp = await fetch("bridge.py");
    if (!bridgeResp.ok) throw new Error("Failed to fetch bridge.py");
    const bridgeCode = await bridgeResp.text();
    console.log("Running bridge.py (", bridgeCode.length, "bytes)");
    pyodide.runPython(bridgeCode);
    console.log("bridge.py executed");

    // Verify it works
    pyodide.runPython("from audiobook_tts.text import parse_segments");
    console.log("Import verified");

    // Store bridge functions
    bridge = {
      parseChapter: pyodide.globals.get("bridge_parse_chapter"),
      applyPronunciations: pyodide.globals.get("bridge_apply_pronunciations"),
      parseMultiVoice: pyodide.globals.get("bridge_parse_multi_voice"),
      previewText: pyodide.globals.get("bridge_preview_text"),
      defaultPronunciations: pyodide.globals.get("bridge_default_pronunciations"),
      defaultSpeakerVoices: pyodide.globals.get("bridge_default_speaker_voices"),
    };

    // Load defaults
    state.pronunciations = JSON.parse(bridge.defaultPronunciations());
    state.speakerVoices = JSON.parse(bridge.defaultSpeakerVoices());

    hideStatus();
    return true;
  } catch (err) {
    console.error("Pyodide init error:", err);
    showStatus(`Failed to load Python: ${err.message || err}`, true);
    return false;
  }
}

// --- Voice list ---

async function loadVoices() {
  try {
    state.voices = await EdgeTTS.fetchVoices();
    // Sort: English voices first, then alphabetical
    state.voices.sort((a, b) => {
      const aEn = a.Locale.startsWith("en-");
      const bEn = b.Locale.startsWith("en-");
      if (aEn !== bEn) return bEn - aEn;
      return a.ShortName.localeCompare(b.ShortName);
    });

    voiceSelect.innerHTML = "";
    for (const v of state.voices) {
      const opt = document.createElement("option");
      opt.value = v.ShortName;
      opt.textContent = `${v.FriendlyName} (${v.ShortName})`;
      if (v.ShortName === state.selectedVoice) opt.selected = true;
      voiceSelect.appendChild(opt);
    }
  } catch (err) {
    voiceSelect.innerHTML = '<option value="en-US-EmmaMultilingualNeural">en-US-EmmaMultilingualNeural (default)</option>';
    showStatus(`Could not load voice list: ${err.message}. Using default.`, true);
  }
}

// --- Chapter management ---

function addChapter(name, content) {
  state.chapters.push({ name, content, result: null });
  renderChapterList();
}

function removeChapter(idx) {
  state.chapters.splice(idx, 1);
  // Also remove audio result
  const ch = state.chapters[idx];
  if (ch) delete state.audioResults[ch.name];
  renderChapterList();
}

function renderChapterList() {
  if (state.chapters.length === 0) {
    chapterList.style.display = "none";
    uploadActions.style.display = "none";
    return;
  }

  chapterList.style.display = "";
  uploadActions.style.display = "";
  chapterItems.innerHTML = "";

  for (let i = 0; i < state.chapters.length; i++) {
    const ch = state.chapters[i];
    const li = document.createElement("li");
    const lines = ch.content.split("\n").length;
    li.innerHTML = `
      <span class="ch-name">${escHtml(ch.name)}</span>
      <span class="ch-info">${lines} lines</span>
      <button class="ch-remove" data-idx="${i}" title="Remove">&times;</button>
    `;
    chapterItems.appendChild(li);
  }

  chapterItems.querySelectorAll(".ch-remove").forEach(btn => {
    btn.addEventListener("click", () => removeChapter(parseInt(btn.dataset.idx)));
  });

  renderPreviewSelect();
}

// --- File upload ---

function handleFiles(files) {
  for (const file of files) {
    if (!file.name.match(/\.(md|txt|markdown)$/i)) continue;
    const reader = new FileReader();
    reader.onload = () => {
      const name = file.name.replace(/\.(md|txt|markdown)$/i, "");
      addChapter(name, reader.result);
    };
    reader.readAsText(file);
  }
}

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => handleFiles(fileInput.files));

// --- Paste / write ---

addPasteBtn.addEventListener("click", () => {
  const title = pasteTitle.value.trim() || `chapter_${state.chapters.length + 1}`;
  const content = pasteText.value.trim();
  if (!content) {
    showStatus("Paste some text first.", true);
    return;
  }
  addChapter(title, content);
  pasteTitle.value = "";
  pasteText.value = "";
});

// --- Editor navigation ---

toConfigBtn.addEventListener("click", () => {
  uploadSection.style.display = "none";
  editorSection.style.display = "";
  renderPronunciations();
  renderSpeakerVoices();
  renderPreviewSelect();
});

backToUpload.addEventListener("click", () => {
  editorSection.style.display = "none";
  uploadSection.style.display = "";
});

// --- Preview ---

function renderPreviewSelect() {
  previewChapterSelect.innerHTML = "";
  for (let i = 0; i < state.chapters.length; i++) {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = state.chapters[i].name;
    previewChapterSelect.appendChild(opt);
  }
  if (state.chapters.length > 0) updatePreview();
}

previewChapterSelect.addEventListener("change", updatePreview);

function updatePreview() {
  const idx = parseInt(previewChapterSelect.value);
  const ch = state.chapters[idx];
  if (!ch || !bridge) return;

  try {
    const result = JSON.parse(bridge.previewText(ch.content, JSON.stringify(state.pronunciations)));
    ch.result = result;
    renderPreviewContent(result);
  } catch (err) {
    previewContent.innerHTML = `<p style="color:red">Preview error: ${escHtml(err.message)}</p>`;
  }
}

function renderPreviewContent(result) {
  let html = "";
  for (const para of result.paragraphs) {
    if (para.is_scene_break) {
      html += `<div class="para scene-break">--- scene break ---</div>`;
    } else {
      const ttsDiff = para.tts_text !== para.original ? `<div class="tts-text">TTS: ${escHtml(para.tts_text)}</div>` : "";
      html += `<div class="para"><div>${escHtml(para.original)}</div>${ttsDiff}</div>`;
    }
  }
  if (result.speakers.length > 0) {
    html = `<p class="speaker-tag">Speakers: ${result.speakers.map(escHtml).join(", ")}</p>` + html;
  }
  previewContent.innerHTML = html || "<p style='color:#999'>Empty chapter</p>";
}

// --- Pronunciations ---

function renderPronunciations() {
  pronunciationList.innerHTML = "";
  for (const [word, phonetic] of Object.entries(state.pronunciations)) {
    addPronunciationRow(word, phonetic);
  }
}

function addPronunciationRow(word = "", phonetic = "") {
  const row = document.createElement("div");
  row.className = "pronunciation-row";
  row.innerHTML = `
    <input type="text" placeholder="word" value="${escAttr(word)}" class="pron-word">
    <input type="text" placeholder="phonetic spelling" value="${escAttr(phonetic)}" class="pron-phonetic">
    <button class="remove-btn" title="Remove">&times;</button>
  `;
  pronunciationList.appendChild(row);

  row.querySelector(".remove-btn").addEventListener("click", () => {
    const w = row.querySelector(".pron-word").value.trim();
    delete state.pronunciations[w];
    row.remove();
  });

  // Update state on change
  const updatePron = () => {
    const oldWord = row._currentWord;
    const newWord = row.querySelector(".pron-word").value.trim();
    const newPhonetic = row.querySelector(".pron-phonetic").value.trim();
    if (oldWord && oldWord !== newWord) delete state.pronunciations[oldWord];
    if (newWord && newPhonetic) state.pronunciations[newWord] = newPhonetic;
    row._currentWord = newWord;
  };
  row._currentWord = word;
  row.querySelector(".pron-word").addEventListener("input", updatePron);
  row.querySelector(".pron-phonetic").addEventListener("input", updatePron);
}

addPronunciationBtn.addEventListener("click", () => addPronunciationRow());

// --- Speaker voices ---

function renderSpeakerVoices() {
  speakerVoiceList.innerHTML = "";
  for (const [speaker, voice] of Object.entries(state.speakerVoices)) {
    addSpeakerRow(speaker, voice);
  }
}

function addSpeakerRow(speaker = "", voice = "en-US-EmmaMultilingualNeural") {
  const row = document.createElement("div");
  row.className = "speaker-voice-row";
  row.innerHTML = `
    <input type="text" placeholder="Tag name" value="${escAttr(speaker)}" class="spk-name">
    <select class="spk-voice"></select>
    <button class="remove-btn" title="Remove">&times;</button>
  `;

  const sel = row.querySelector(".spk-voice");
  for (const v of state.voices) {
    const opt = document.createElement("option");
    opt.value = v.ShortName;
    opt.textContent = v.ShortName;
    if (v.ShortName === voice) opt.selected = true;
    sel.appendChild(opt);
  }

  speakerVoiceList.appendChild(row);

  row.querySelector(".remove-btn").addEventListener("click", () => {
    const n = row.querySelector(".spk-name").value.trim();
    delete state.speakerVoices[n];
    row.remove();
  });

  const updateSpk = () => {
    const oldName = row._currentName;
    const newName = row.querySelector(".spk-name").value.trim();
    const newVoice = row.querySelector(".spk-voice").value;
    if (oldName && oldName !== newName) delete state.speakerVoices[oldName];
    if (newName) state.speakerVoices[newName] = newVoice;
    row._currentName = newName;
  };
  row._currentName = speaker;
  row.querySelector(".spk-name").addEventListener("input", updateSpk);
  row.querySelector(".spk-voice").addEventListener("change", updateSpk);
}

addSpeakerBtn.addEventListener("click", () => addSpeakerRow());

// --- Multi-voice toggle ---

multiVoiceCheck.addEventListener("change", () => {
  state.multiVoice = multiVoiceCheck.checked;
  speakerFieldset.style.display = state.multiVoice ? "" : "none";
});

// --- Voice selection ---

voiceSelect.addEventListener("change", () => {
  state.selectedVoice = voiceSelect.value;
});

// --- Config export / import ---

const CONFIG_VERSION = 1;

function isStringMap(value) {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((v) => typeof v === "string")
  );
}

exportConfigBtn.addEventListener("click", () => {
  const config = {
    version: CONFIG_VERSION,
    selectedVoice: state.selectedVoice,
    multiVoice: state.multiVoice,
    speakerVoices: state.speakerVoices,
    pronunciations: state.pronunciations,
  };
  const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "audiobook-tts-config.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
});

importConfigBtn.addEventListener("click", () => configFileInput.click());

configFileInput.addEventListener("change", async () => {
  const file = configFileInput.files[0];
  configFileInput.value = ""; // allow re-loading the same file
  if (!file) return;
  try {
    applyConfig(JSON.parse(await file.text()));
    showStatus(`Config loaded from ${file.name}.`);
  } catch (err) {
    showStatus(`Could not load config: ${err.message}`, true);
  }
});

// --- Speech relay ---

const relayUrlInput = document.getElementById("relay-url-input");
const relaySaveBtn = document.getElementById("relay-save-btn");
const relayClearBtn = document.getElementById("relay-clear-btn");
const relayStatus = document.getElementById("relay-status");

function describeRelay() {
  const custom = localStorage.getItem("tts-relay-url");
  if (custom) {
    relayUrlInput.value = custom;
    relayStatus.textContent = "Using your relay. Check it is running before building.";
  } else {
    relayStatus.textContent = "Using the hosted relay.";
  }
}

function checkRelayHealth(url) {
  // ws(s)://host:port/tts-ws -> http(s)://host:port/health
  try {
    const u = new URL(url);
    const health = `${u.protocol === "wss:" ? "https" : "http"}://${u.host}/health`;
    fetch(health, { mode: "cors" })
      .then((r) => {
        if (r.ok) {
          relayStatus.textContent = "Relay reachable.";
        } else {
          relayStatus.textContent = `Relay answered with HTTP ${r.status}.`;
        }
      })
      .catch(() => {
        relayStatus.textContent = "Could not reach the relay. Is it running?";
      });
  } catch {
    relayStatus.textContent = "That does not look like a WebSocket URL.";
  }
}

relaySaveBtn.addEventListener("click", () => {
  const url = relayUrlInput.value.trim();
  if (!url) {
    relayStatus.textContent = "Enter a relay URL first, e.g. ws://localhost:8765/tts-ws";
    return;
  }
  localStorage.setItem("tts-relay-url", url);
  describeRelay();
  checkRelayHealth(url);
  try {
    const path = new URL(url).pathname.replace(/\/+$/, "");
    if (path && path !== "/tts-ws") {
      relayStatus.textContent += ` Note: relays usually listen on /tts-ws (you entered ${path}).`;
    }
  } catch {
    // checkRelayHealth already reports malformed URLs.
  }
});

relayClearBtn.addEventListener("click", () => {
  localStorage.removeItem("tts-relay-url");
  relayUrlInput.value = "";
  describeRelay();
});

describeRelay();

function applyConfig(config) {
  if (typeof config !== "object" || config === null || Array.isArray(config)) {
    throw new Error("expected a JSON object");
  }
  if (config.selectedVoice !== undefined) {
    if (typeof config.selectedVoice !== "string" || !config.selectedVoice) {
      throw new Error("selectedVoice must be a non-empty string");
    }
    state.selectedVoice = config.selectedVoice;
    voiceSelect.value = config.selectedVoice;
    if (voiceSelect.value !== config.selectedVoice) {
      // Voice list not loaded (or voice unknown): keep the UI honest.
      const opt = document.createElement("option");
      opt.value = config.selectedVoice;
      opt.textContent = `${config.selectedVoice} (from config)`;
      voiceSelect.appendChild(opt);
      voiceSelect.value = config.selectedVoice;
    }
  }
  if (config.multiVoice !== undefined) {
    if (typeof config.multiVoice !== "boolean") {
      throw new Error("multiVoice must be true or false");
    }
    state.multiVoice = config.multiVoice;
    multiVoiceCheck.checked = config.multiVoice;
    speakerFieldset.style.display = config.multiVoice ? "" : "none";
  }
  if (config.speakerVoices !== undefined) {
    if (!isStringMap(config.speakerVoices)) {
      throw new Error("speakerVoices must map names to voice names");
    }
    state.speakerVoices = config.speakerVoices;
    renderSpeakerVoices();
  }
  if (config.pronunciations !== undefined) {
    if (!isStringMap(config.pronunciations)) {
      throw new Error("pronunciations must map words to phonetic spellings");
    }
    state.pronunciations = config.pronunciations;
    renderPronunciations();
  }
}

// --- Build ---

buildBtn.addEventListener("click", async () => {
  if (state.building) return;
  if (state.chapters.length === 0) {
    showStatus("No chapters to build.", true);
    return;
  }

  state.building = true;
  state.audioResults = {};
  buildBtn.disabled = true;
  buildProgress.style.display = "";
  chapterStatus.innerHTML = "";

  // Plan every chapter up front so the progress denominator counts the same
  // units the build loop completes: speaker segments in multi-voice mode,
  // paragraphs otherwise. (Counting paragraphs while completing segments
  // left the bar stuck short, e.g. "4 / 7" on a finished build.)
  const plans = [];
  let totalSegments = 0;
  for (const ch of state.chapters) {
    let segments = [];
    try {
      if (state.multiVoice) {
        const mvResult = JSON.parse(bridge.parseMultiVoice(
          ch.content,
          "",
          JSON.stringify(state.pronunciations)
        ));
        segments = mvResult.segments.filter(s => s.text.trim());
      } else {
        const result = JSON.parse(bridge.previewText(ch.content, JSON.stringify(state.pronunciations)));
        segments = result.paragraphs
          .filter(p => !p.is_scene_break && p.tts_text.trim())
          .map(p => ({ speaker: "", text: p.tts_text }));
      }
    } catch (err) {
      console.error(`Failed to plan ${ch.name}:`, err);
    }
    plans.push({ ch, segments });
    totalSegments += Math.max(segments.length, 1);
  }

  let completed = 0;
  let failed = 0;

  for (const { ch, segments } of plans) {
    addChapterStatus(ch.name, "building");

    try {
      // Synthesize each segment
      const audioParts = [];
      for (const seg of segments) {
        if (!seg.text.trim()) continue;

        const voice = state.multiVoice && seg.speaker
          ? (state.speakerVoices[seg.speaker] || state.selectedVoice)
          : state.selectedVoice;

        const audio = await EdgeTTS.synthesize(seg.text, {
          voice,
          onProgress: (bytes) => {
            // Could update per-segment progress here
          },
        });
        audioParts.push(audio);
        completed++;
        progressFill.style.width = `${(completed / totalSegments) * 100}%`;
        progressText.textContent = `${completed} / ${totalSegments} segments`;
      }

      // Concatenate all parts into one blob
      const chapterBlob = new Blob(audioParts, { type: "audio/mpeg" });
      state.audioResults[ch.name] = chapterBlob;
      updateChapterStatus(ch.name, "done");
    } catch (err) {
      console.error(`Failed to build ${ch.name}:`, err);
      updateChapterStatus(ch.name, "error", err.message);
      failed++;
    }
  }

  state.building = false;
  buildBtn.disabled = false;
  downloadAllBtn.disabled = Object.keys(state.audioResults).length === 0;

  const builtCount = Object.keys(state.audioResults).length;
  showStatus(`Build complete: ${builtCount} chapter(s) built, ${failed} failed.`);
});

// --- Chapter status UI ---

function addChapterStatus(name, status) {
  const div = document.createElement("div");
  div.className = "chapter-status-item";
  div.id = `status-${name}`;
  div.innerHTML = `
    <span class="status-icon building">&#9203;</span>
    <span>${escHtml(name)}</span>
    <span class="status-msg"></span>
  `;
  chapterStatus.appendChild(div);
}

function updateChapterStatus(name, status, msg = "") {
  const div = document.getElementById(`status-${name}`);
  if (!div) return;

  const icon = div.querySelector(".status-icon");
  const msgEl = div.querySelector(".status-msg");
  icon.className = `status-icon ${status}`;

  if (status === "done") {
    icon.innerHTML = "&#10003;";
    // Add download link
    const link = document.createElement("a");
    link.className = "download-link";
    link.href = URL.createObjectURL(state.audioResults[name]);
    link.download = `${name}.mp3`;
    link.textContent = "download";
    link.addEventListener("click", () => {
      // Keep the object URL alive for re-downloads
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    });
    div.appendChild(link);
  } else if (status === "error") {
    icon.innerHTML = "&#10007;";
    msgEl.textContent = msg;
  }
}

// --- Download all as zip ---

downloadAllBtn.addEventListener("click", async () => {
  const names = Object.keys(state.audioResults);
  if (names.length === 0) return;

  // Use a minimal ZIP implementation
  showStatus("Creating zip file...");
  try {
    const zip = await createZip(state.audioResults);
    const url = URL.createObjectURL(zip);
    const a = document.createElement("a");
    a.href = url;
    a.download = "audiobook.zip";
    a.click();
    URL.revokeObjectURL(url);
    hideStatus();
  } catch (err) {
    showStatus(`Zip creation failed: ${err.message}. Download chapters individually.`, true);
  }
});

// --- Minimal ZIP file creator ---

async function createZip(files) {
  // files: {name: Blob}
  const parts = [];
  const centralDir = [];

  let offset = 0;
  for (const [name, blob] of Object.entries(files)) {
    const data = new Uint8Array(await blob.arrayBuffer());
    const nameBytes = new TextEncoder().encode(`${name}.mp3`);

    // Local file header
    const header = new Uint8Array(30 + nameBytes.length);
    const headerView = new DataView(header.buffer);
    headerView.setUint32(0, 0x04034b50, true); // signature
    headerView.setUint16(4, 20, true); // version needed
    headerView.setUint16(6, 0, true); // flags
    headerView.setUint16(8, 0, true); // compression: store
    headerView.setUint16(10, 0, true); // mod time
    headerView.setUint16(12, 0, true); // mod date
    headerView.setUint32(14, crc32(data), true); // crc32
    headerView.setUint32(18, data.byteLength, true); // compressed size
    headerView.setUint32(22, data.byteLength, true); // uncompressed size
    headerView.setUint16(26, nameBytes.length, true); // name length
    headerView.setUint16(28, 0, true); // extra length
    header.set(nameBytes, 30);

    centralDir.push({ name: nameBytes, offset, crc: crc32(data), size: data.byteLength });
    parts.push(header, data);
    offset += header.byteLength + data.byteLength;
  }

  // Central directory
  const cdOffset = offset;
  for (const entry of centralDir) {
    const cd = new Uint8Array(46 + entry.name.length);
    const cdView = new DataView(cd.buffer);
    cdView.setUint32(0, 0x02014b50, true); // signature
    cdView.setUint16(4, 20, true); // version made by
    cdView.setUint16(6, 20, true); // version needed
    cdView.setUint16(8, 0, true); // flags
    cdView.setUint16(10, 0, true); // compression
    cdView.setUint16(12, 0, true); // mod time
    cdView.setUint16(14, 0, true); // mod date
    cdView.setUint32(16, entry.crc, true); // crc32
    cdView.setUint32(20, entry.size, true); // compressed
    cdView.setUint32(24, entry.size, true); // uncompressed
    cdView.setUint16(28, entry.name.length, true); // name length
    cdView.setUint16(30, 0, true); // extra length
    cdView.setUint16(32, 0, true); // comment length
    cdView.setUint16(34, 0, true); // disk start
    cdView.setUint16(36, 0, true); // internal attrs
    cdView.setUint32(38, 0, true); // external attrs
    cdView.setUint32(42, entry.offset, true); // local header offset
    cd.set(entry.name, 46);
    parts.push(cd);
  }

  const cdLength = offset - cdOffset;

  // End of central directory
  const eocd = new Uint8Array(22);
  const eocdView = new DataView(eocd.buffer);
  eocdView.setUint32(0, 0x06054b50, true); // signature
  eocdView.setUint16(4, 0, true); // disk number
  eocdView.setUint16(6, 0, true); // cd disk number
  eocdView.setUint16(8, centralDir.length, true); // entries on disk
  eocdView.setUint16(10, centralDir.length, true); // total entries
  eocdView.setUint32(12, cdLength, true); // cd size
  eocdView.setUint32(16, cdOffset, true); // cd offset
  eocdView.setUint16(20, 0, true); // comment length
  parts.push(eocd);

  return new Blob(parts, { type: "application/zip" });
}

function crc32(data) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xEDB88320 : 0);
    }
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

// --- Utility ---

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  return s.replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// --- Boot ---

(async function boot() {
  const pyodideReady = initPyodide();
  const voicesReady = loadVoices();
  await Promise.all([pyodideReady, voicesReady]);
})();
