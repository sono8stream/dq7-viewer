const savePathEl = document.getElementById('savePath');
const deviceTypeEl = document.getElementById('deviceType');
const loadBtn = document.getElementById('loadBtn');
const loadMsg = document.getElementById('loadMsg');
const browseBtn = document.getElementById('browseBtn');
const browserPanel = document.getElementById('browserPanel');
const browserPath = document.getElementById('browserPath');
const browserList = document.getElementById('browserList');
const browserUpBtn = document.getElementById('browserUpBtn');
const browserCloseBtn = document.getElementById('browserCloseBtn');
const modeUploadBtn = document.getElementById('modeUploadBtn');
const modePathBtn = document.getElementById('modePathBtn');
const modeUploadDiv = document.getElementById('modeUpload');
const modePathDiv = document.getElementById('modePath');
const saveFileInput = document.getElementById('saveFileInput');
const uploadMsg = document.getElementById('uploadMsg');
const editPanel = document.getElementById('editPanel');
const fileInfo = document.getElementById('fileInfo');
const writeBtn = document.getElementById('writeBtn');
const writeMsg = document.getElementById('writeMsg');
const scalarGrid = document.getElementById('scalarGrid');
const partyGrid = document.getElementById('partyGrid');
const charTabs = document.getElementById('charTabs');
const charDetail = document.getElementById('charDetail');
const placeIdInput = document.getElementById('placeIdInput');
const placeIdState = document.getElementById('placeIdState');
const placeIdToggleBtn = document.getElementById('placeIdToggleBtn');
const rawBitOffset = document.getElementById('rawBitOffset');
const rawBitNum = document.getElementById('rawBitNum');
const rawBitToggleBtn = document.getElementById('rawBitToggleBtn');
const rawByteOffset = document.getElementById('rawByteOffset');
const rawByteHex = document.getElementById('rawByteHex');
const rawByteWriteBtn = document.getElementById('rawByteWriteBtn');
const pendingRawEditsEl = document.getElementById('pendingRawEdits');
const flagsHexDumpEl = document.getElementById('flagsHexDump');

const SCALAR_LABELS = {
  gold: '所持金', bank: '銀行', casino: 'カジノコイン', medal_bank: 'メダル預り',
  small_medal: 'しょうメダル', max_damage: '最大ダメージ記録', all_gold: '稼いだ総額',
};

// +0x3250, 30fpsのフレームカウンタ。save_editor.py PLAY_TIME_OFFSET参照。
const PLAY_TIME_OFFSET = 0x3250;
const PLAY_TIME_FPS = 30;

const CHAR_FIELD_LABELS = {
  lv: 'Lv', hp: 'HP', max_hp: 'maxHP', mp: 'MP', max_mp: 'maxMP',
  power: '力', defense: '守備力', speed: '素早さ', intelligence: '賢さ',
  cool: 'かっこよさ', exp: '経験値', job: '職業ID',
};

const LOAD_PATH_KEY = 'dq7saveeditor.lastPath';
const LOAD_DEVICE_KEY = 'dq7saveeditor.lastDevice';

let current = null; // last loaded save fields (from /api/save/load or /api/save/parse_upload)
let activeCharIndex = 0;
let mode = 'upload'; // 'upload' (browser file picker, edits round-trip via download) | 'path' (server-side path)
let uploadedDataB64 = null; // base64 of the most recently loaded/edited upload bytes
let uploadedFileName = 'save.bin';

// pending edits to the raw flags/bits region (see save_editor.py
// FLAGS_REGION_BASE) - queued client-side, sent as raw_bits/raw_bytes on
// the next 保存, then cleared once the write round-trips successfully.
let pendingRawBits = []; // [{offset, bit, value}]
let pendingRawBytes = []; // [{offset, hex}]

savePathEl.value = localStorage.getItem(LOAD_PATH_KEY) || '';
deviceTypeEl.value = localStorage.getItem(LOAD_DEVICE_KEY) || '0';

loadBtn.addEventListener('click', loadSave);
writeBtn.addEventListener('click', writeSave);
placeIdToggleBtn.addEventListener('click', queuePlaceIdToggle);
rawBitToggleBtn.addEventListener('click', queueRawBitToggle);
rawByteWriteBtn.addEventListener('click', queueRawByteWrite);
placeIdInput.addEventListener('input', updatePlaceIdState);
browseBtn.addEventListener('click', () => {
  const startDir = savePathEl.value.trim();
  openBrowser(startDir || null);
});
browserCloseBtn.addEventListener('click', () => { browserPanel.style.display = 'none'; });

modeUploadBtn.addEventListener('click', () => setMode('upload'));
modePathBtn.addEventListener('click', () => setMode('path'));
setMode('upload');
saveFileInput.addEventListener('change', () => {
  if (saveFileInput.files.length) loadFromUpload(saveFileInput.files[0]);
});

function setMode(next) {
  mode = next;
  modeUploadBtn.classList.toggle('active', mode === 'upload');
  modePathBtn.classList.toggle('active', mode === 'path');
  modeUploadDiv.style.display = mode === 'upload' ? '' : 'none';
  modePathDiv.style.display = mode === 'path' ? '' : 'none';
}

function arrayBufferToBase64(buf) {
  let binary = '';
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64ToBlob(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: 'application/octet-stream' });
}

async function loadFromUpload(file) {
  uploadedFileName = file.name;
  uploadMsg.textContent = `${file.name} (${(file.size / 1024).toFixed(1)}KB) を読み込み中...`;
  try {
    const buf = await file.arrayBuffer();
    uploadedDataB64 = arrayBufferToBase64(buf);
    uploadMsg.textContent = `${file.name} をアップロード中...`;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    let res;
    try {
      res = await fetch('/api/save/parse_upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data_b64: uploadedDataB64, device_type: Number(deviceTypeEl.value) }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`);
    }
    const data = await res.json();
    if (data.error) {
      uploadMsg.textContent = `エラー: ${data.error}`;
      editPanel.style.display = 'none';
      return;
    }
    current = data;
    uploadMsg.textContent = '';
    renderAll();
  } catch (e) {
    console.error('loadFromUpload failed:', e);
    uploadMsg.textContent = e.name === 'AbortError'
      ? 'タイムアウトしました（30秒）。ファイルが大きすぎるか、サーバーに接続できていません。'
      : `エラー: ${e.message || e}`;
    editPanel.style.display = 'none';
  }
}

let browserCurrentPath = null;

async function openBrowser(path) {
  browserPanel.style.display = '';
  browserList.innerHTML = '<div class="file-meta">読み込み中...</div>';
  const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : '/api/browse';
  const res = await fetch(url);
  const data = await res.json();
  if (data.error) {
    browserList.innerHTML = `<div class="file-meta">エラー: ${escapeHtml(data.error)}</div>`;
    return;
  }
  browserCurrentPath = data.path;
  browserPath.textContent = data.path;
  browserUpBtn.disabled = !data.parent;
  browserUpBtn.onclick = () => { if (data.parent) openBrowser(data.parent); };
  renderBrowserList(data.entries);
}

function renderBrowserList(entries) {
  browserList.innerHTML = '';
  if (entries.length === 0) {
    browserList.innerHTML = '<div class="file-meta">(空のフォルダ)</div>';
    return;
  }
  for (const e of entries) {
    const div = document.createElement('div');
    div.className = 'browse-item' + (e.is_dir ? '' : ' is-file');
    const icon = document.createElement('span');
    icon.className = 'browse-icon';
    icon.textContent = e.is_dir ? '📁' : '📄';
    const name = document.createElement('span');
    name.style.flex = '1';
    name.textContent = e.name;
    div.appendChild(icon);
    div.appendChild(name);
    if (!e.is_dir) {
      const size = document.createElement('span');
      size.className = 'browse-size';
      size.textContent = `${(e.size / 1024).toFixed(1)}KB`;
      div.appendChild(size);
    }
    div.onclick = () => {
      const fullPath = browserCurrentPath.replace(/\/$/, '') + '/' + e.name;
      if (e.is_dir) {
        openBrowser(fullPath);
      } else {
        savePathEl.value = fullPath;
        browserPanel.style.display = 'none';
      }
    };
    browserList.appendChild(div);
  }
}

async function loadSave() {
  const path = savePathEl.value.trim();
  if (!path) return;
  localStorage.setItem(LOAD_PATH_KEY, path);
  localStorage.setItem(LOAD_DEVICE_KEY, deviceTypeEl.value);
  loadMsg.textContent = '読み込み中...';
  try {
    const res = await fetch(`/api/save/load?path=${encodeURIComponent(path)}&device=${deviceTypeEl.value}`);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`);
    }
    const data = await res.json();
    if (data.error) {
      loadMsg.textContent = `エラー: ${data.error}`;
      editPanel.style.display = 'none';
      return;
    }
    current = data;
    loadMsg.textContent = '';
    renderAll();
  } catch (e) {
    console.error('loadSave failed:', e);
    loadMsg.textContent = `エラー: ${e.message || e}`;
    editPanel.style.display = 'none';
  }
}

function renderAll() {
  editPanel.style.display = '';
  const ck = current.checksum_ok
    ? '<span class="checksum-ok">checksum OK</span>'
    : `<span class="checksum-bad">checksum不一致 (stored=${current.checksum_stored}, computed=${current.checksum_computed}) - 別デバイス種別かも</span>`;
  const label = mode === 'upload' ? uploadedFileName : current.path;
  fileInfo.innerHTML = `${escapeHtml(label)} (${current.file_size} bytes) - ${ck}`;
  // current.flags_region is now the fresh baseline (either a new file, or
  // the result of a write we just applied) - any edits queued against the
  // previous baseline no longer make sense to keep pending.
  pendingRawBits = [];
  pendingRawBytes = [];
  renderScalars();
  renderParty();
  renderCharTabs();
  renderCharDetail();
  updatePlaceIdState();
  renderPendingRawEdits();
  renderFlagsHexDump();
}

// --- raw flags/bits region (see save_editor.py FLAGS_REGION_BASE) ---

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}

function parseOffsetInput(raw) {
  const s = raw.trim().replace(/^0x/i, '');
  const v = parseInt(s, 16);
  if (Number.isNaN(v)) throw new Error(`不正なoffset: ${raw}`);
  return v;
}

// applies pendingRawBits/pendingRawBytes on top of current.flags_region.hex
// so the hex dump and place/bit state readouts reflect not-yet-saved edits.
function effectiveFlagsBytes() {
  const bytes = hexToBytes(current.flags_region.hex);
  const base = current.flags_region.offset;
  for (const e of pendingRawBytes) {
    const rel = e.offset - base;
    const data = hexToBytes(e.hex);
    for (let i = 0; i < data.length; i++) {
      if (rel + i >= 0 && rel + i < bytes.length) bytes[rel + i] = data[i];
    }
  }
  for (const e of pendingRawBits) {
    const rel = e.offset - base;
    if (rel < 0 || rel >= bytes.length) continue;
    if (e.value) bytes[rel] |= (1 << e.bit);
    else bytes[rel] &= ~(1 << e.bit) & 0xFF;
  }
  return bytes;
}

function effectiveBitAt(absOffset, bit) {
  const bytes = effectiveFlagsBytes();
  const rel = absOffset - current.flags_region.offset;
  if (rel < 0 || rel >= bytes.length) return null;
  return !!(bytes[rel] & (1 << bit));
}

function updatePlaceIdState() {
  if (!current) return;
  const id = Number(placeIdInput.value);
  if (!Number.isFinite(id) || id < 0 || placeIdInput.value === '') {
    placeIdState.textContent = '';
    return;
  }
  const offset = current.flags_region.offset + Math.floor(id / 8);
  const bit = id % 8;
  const state = effectiveBitAt(offset, bit);
  placeIdState.textContent = state === null
    ? '(範囲外)'
    : `offset=0x${offset.toString(16)} bit=${bit} 現在: ${state ? 'ON' : 'OFF'}`;
}

function queuePlaceIdToggle() {
  const id = Number(placeIdInput.value);
  if (!Number.isFinite(id) || id < 0) return;
  const offset = current.flags_region.offset + Math.floor(id / 8);
  const bit = id % 8;
  const cur = effectiveBitAt(offset, bit);
  if (cur === null) return;
  queueRawBit(offset, bit, !cur, `Place ID ${id}`);
}

function queueRawBitToggle() {
  let offset;
  try {
    offset = parseOffsetInput(rawBitOffset.value);
  } catch (e) {
    alert(e.message);
    return;
  }
  const bit = Number(rawBitNum.value);
  if (!Number.isFinite(bit) || bit < 0 || bit > 7) {
    alert('bitは0-7で指定してください');
    return;
  }
  const cur = effectiveBitAt(offset, bit);
  if (cur === null) {
    alert('flags_region の範囲外のoffsetです');
    return;
  }
  queueRawBit(offset, bit, !cur, null);
}

function queueRawBit(offset, bit, value, note) {
  pendingRawBits = pendingRawBits.filter(e => !(e.offset === offset && e.bit === bit));
  pendingRawBits.push({ offset, bit, value, note });
  renderPendingRawEdits();
  renderFlagsHexDump();
  updatePlaceIdState();
}

function queueRawByteWrite() {
  let offset;
  try {
    offset = parseOffsetInput(rawByteOffset.value);
  } catch (e) {
    alert(e.message);
    return;
  }
  const hex = rawByteHex.value.trim().replace(/\s+/g, '');
  if (!/^[0-9a-fA-F]+$/.test(hex) || hex.length % 2 !== 0) {
    alert('16進数のバイト列を入力してください（例: deadbeef）');
    return;
  }
  pendingRawBytes = pendingRawBytes.filter(e => e.offset !== offset);
  pendingRawBytes.push({ offset, hex: hex.toLowerCase() });
  rawByteHex.value = '';
  renderPendingRawEdits();
  renderFlagsHexDump();
  updatePlaceIdState();
}

function renderPendingRawEdits() {
  pendingRawEditsEl.innerHTML = '';
  const all = [
    ...pendingRawBits.map(e => ({
      text: `bit  offset=0x${e.offset.toString(16)} bit=${e.bit} -> ${e.value ? 'ON' : 'OFF'}${e.note ? ` (${e.note})` : ''}`,
      remove: () => { pendingRawBits = pendingRawBits.filter(x => x !== e); },
    })),
    ...pendingRawBytes.map(e => ({
      text: `byte offset=0x${e.offset.toString(16)} -> ${e.hex}`,
      remove: () => { pendingRawBytes = pendingRawBytes.filter(x => x !== e); },
    })),
  ];
  if (all.length === 0) return;
  for (const item of all) {
    const div = document.createElement('div');
    div.className = 'pending-edit';
    const span = document.createElement('span');
    span.textContent = item.text;
    const btn = document.createElement('button');
    btn.textContent = '取消';
    btn.onclick = () => {
      item.remove();
      renderPendingRawEdits();
      renderFlagsHexDump();
      updatePlaceIdState();
    };
    div.appendChild(span);
    div.appendChild(btn);
    pendingRawEditsEl.appendChild(div);
  }
}

function renderFlagsHexDump() {
  if (!current || !current.flags_region) {
    flagsHexDumpEl.textContent = '';
    return;
  }
  const bytes = effectiveFlagsBytes();
  const base = current.flags_region.offset;
  const changedOffsets = new Set();
  for (const e of pendingRawBits) changedOffsets.add(e.offset - base);
  for (const e of pendingRawBytes) {
    const data = hexToBytes(e.hex);
    for (let i = 0; i < data.length; i++) changedOffsets.add(e.offset - base + i);
  }

  const lines = [];
  for (let row = 0; row < bytes.length; row += 16) {
    const abs = base + row;
    let line = `0x${abs.toString(16).padStart(4, '0')}: `;
    const spans = [];
    for (let i = 0; i < 16 && row + i < bytes.length; i++) {
      const b = bytes[row + i].toString(16).padStart(2, '0');
      const changed = changedOffsets.has(row + i);
      spans.push(changed ? `<span class="byte-changed">${b}</span>` : b);
    }
    lines.push(line + spans.join(' '));
  }
  flagsHexDumpEl.innerHTML = lines.join('\n');
}

function renderScalars() {
  scalarGrid.innerHTML = '';
  for (const [name, addr, size] of [
    ['gold', 0x0528], ['bank', 0x052C], ['casino', 0x0530],
    ['medal_bank', 0x0534], ['small_medal', 0x0538],
    ['max_damage', 0x053C], ['all_gold', 0x0540],
  ]) {
    const field = document.createElement('div');
    field.className = 'save-field';
    const label = document.createElement('label');
    label.textContent = `${SCALAR_LABELS[name] || name} (+0x${addr.toString(16)})`;
    const input = document.createElement('input');
    input.type = 'number';
    input.min = 0;
    input.dataset.scalar = name;
    input.value = current.scalars[name];
    field.appendChild(label);
    field.appendChild(input);
    scalarGrid.appendChild(field);
  }

  // 冒険した時間 (+0x3250, 30fpsのフレームカウンタ) - 時/分のペアで
  // 編集し、送信時にframesへ合成する。生フレーム数はdata-scalar経由では
  // 扱わず、専用hidden inputに保持する。
  const timeField = document.createElement('div');
  timeField.className = 'save-field';
  const timeLabel = document.createElement('label');
  timeLabel.textContent = `冒険した時間 (+0x${PLAY_TIME_OFFSET.toString(16)})`;
  const timeWrap = document.createElement('div');
  timeWrap.className = 'play-time-wrap';
  const hoursInput = document.createElement('input');
  hoursInput.type = 'number';
  hoursInput.min = 0;
  hoursInput.max = 999;
  hoursInput.id = 'playTimeHours';
  hoursInput.value = current.scalars.play_time_hours;
  const hoursSuffix = document.createElement('span');
  hoursSuffix.textContent = '時間';
  const minutesInput = document.createElement('input');
  minutesInput.type = 'number';
  minutesInput.min = 0;
  minutesInput.max = 59;
  minutesInput.id = 'playTimeMinutes';
  minutesInput.value = current.scalars.play_time_minutes;
  const minutesSuffix = document.createElement('span');
  minutesSuffix.textContent = '分';
  timeWrap.appendChild(hoursInput);
  timeWrap.appendChild(hoursSuffix);
  timeWrap.appendChild(minutesInput);
  timeWrap.appendChild(minutesSuffix);
  timeField.appendChild(timeLabel);
  timeField.appendChild(timeWrap);
  scalarGrid.appendChild(timeField);
}

function renderParty() {
  partyGrid.innerHTML = '';
  current.party.forEach((slot, i) => {
    const field = document.createElement('div');
    field.className = 'save-field';
    const label = document.createElement('label');
    label.textContent = `スロット${i} (現在: ${escapeHtml(slot.character_name)})`;
    const select = document.createElement('select');
    select.dataset.partySlot = String(i);
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '0';
    emptyOpt.textContent = '(空き / 0)';
    select.appendChild(emptyOpt);
    for (const c of current.character_catalog) {
      const opt = document.createElement('option');
      opt.value = String(c.id);
      opt.textContent = `#${c.id} ${c.name}`;
      if (c.id === slot.character_id) opt.selected = true;
      select.appendChild(opt);
    }
    if (![...select.options].some(o => Number(o.value) === slot.character_id)) {
      const opt = document.createElement('option');
      opt.value = String(slot.character_id);
      opt.textContent = `#${slot.character_id} (カタログ外)`;
      opt.selected = true;
      select.appendChild(opt);
    }
    field.appendChild(label);
    field.appendChild(select);
    partyGrid.appendChild(field);
  });
}

function renderCharTabs() {
  charTabs.innerHTML = '';
  current.charactors.forEach((c, i) => {
    const btn = document.createElement('button');
    btn.textContent = `#${i} ${c.presumed_character_name || c.name || ''}`;
    btn.className = i === activeCharIndex ? 'active' : '';
    btn.onclick = () => { activeCharIndex = i; renderCharTabs(); renderCharDetail(); };
    charTabs.appendChild(btn);
  });
}

function renderCharDetail() {
  charDetail.innerHTML = '';
  const c = current.charactors[activeCharIndex];
  if (!c) return;

  const hint = document.createElement('div');
  hint.className = 'save-hint';
  hint.textContent = `base offset = 0x${c.base_offset.toString(16)}  |  この枠は「隊列内の並び順」ではなく、キャラ固有の固定ステータス枠（推定: id=${c.presumed_character_id}想定、未検証）です。`;
  charDetail.appendChild(hint);

  const grid = document.createElement('div');
  grid.className = 'save-grid';

  const nameField = document.createElement('div');
  nameField.className = 'save-field';
  const nameLabel = document.createElement('label');
  nameLabel.textContent = '名前';
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.maxLength = 6;
  nameInput.dataset.charField = 'name';
  nameInput.value = c.name;
  nameField.appendChild(nameLabel);
  nameField.appendChild(nameInput);
  grid.appendChild(nameField);

  for (const [key, label] of Object.entries(CHAR_FIELD_LABELS)) {
    const field = document.createElement('div');
    field.className = 'save-field';
    const l = document.createElement('label');
    l.textContent = label;
    const input = document.createElement('input');
    input.type = 'number';
    input.dataset.charField = key;
    input.value = c[key];
    field.appendChild(l);
    field.appendChild(input);
    grid.appendChild(field);
  }
  charDetail.appendChild(grid);
}

function collectPatch() {
  const scalars = {};
  scalarGrid.querySelectorAll('[data-scalar]').forEach(el => {
    scalars[el.dataset.scalar] = Number(el.value);
  });

  const hoursEl = document.getElementById('playTimeHours');
  const minutesEl = document.getElementById('playTimeMinutes');
  if (hoursEl && minutesEl) {
    const hours = Math.max(0, Number(hoursEl.value) || 0);
    const minutes = Math.max(0, Math.min(59, Number(minutesEl.value) || 0));
    scalars.play_time_frames = (hours * 3600 + minutes * 60) * PLAY_TIME_FPS;
  }

  const party = [];
  partyGrid.querySelectorAll('[data-party-slot]').forEach(el => {
    party.push({ slot: Number(el.dataset.partySlot), character_id: Number(el.value) });
  });

  // charDetail only reflects the currently active tab, so merge its edits
  // into a full snapshot of all characters (unedited tabs keep last-loaded
  // values from `current`).
  const charactors = current.charactors.map(c => ({ ...c }));
  const activeC = charactors[activeCharIndex];
  charDetail.querySelectorAll('[data-char-field]').forEach(el => {
    const key = el.dataset.charField;
    activeC[key] = key === 'name' ? el.value : Number(el.value);
  });

  const raw_bits = pendingRawBits.map(({ offset, bit, value }) => ({ offset, bit, value }));
  const raw_bytes = pendingRawBytes.map(({ offset, hex }) => ({ offset, hex }));

  return { device_type: Number(deviceTypeEl.value), scalars, party, charactors, raw_bits, raw_bytes };
}

async function writeSave() {
  try {
    await writeSaveInner();
  } catch (e) {
    console.error('writeSave failed:', e);
    writeMsg.textContent = `エラー: ${e.message || e}`;
  }
}

async function writeSaveInner() {
  const patch = collectPatch();
  writeMsg.textContent = '書き込み中...';

  if (mode === 'path') {
    const res = await fetch('/api/save/write', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: current.path, ...patch }),
    });
    const data = await res.json();
    if (data.error) {
      writeMsg.textContent = `エラー: ${data.error}`;
      return;
    }
    writeMsg.textContent = `保存しました (backup: ${data.backup_path})`;
    await loadSave();
    return;
  }

  // upload mode: server never touches disk - it returns the patched bytes,
  // which we hand to the browser as a download (the user then moves that
  // file back over the original with their file manager / the emulator's
  // import feature).
  const res = await fetch('/api/save/build_download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data_b64: uploadedDataB64, ...patch }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    writeMsg.textContent = `エラー: ${data.error || res.status}`;
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = uploadedFileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  // keep editing on top of the just-written state
  const editedBuf = await blob.arrayBuffer();
  uploadedDataB64 = arrayBufferToBase64(editedBuf);
  const parseRes = await fetch('/api/save/parse_upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data_b64: uploadedDataB64, device_type: Number(deviceTypeEl.value) }),
  });
  current = await parseRes.json();
  writeMsg.textContent = `ダウンロードしました (${uploadedFileName}) - ファイルマネージャで元のファイルに上書きしてください`;
  renderAll();
}

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}
