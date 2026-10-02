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

DQ7I18N.extend({
  ja: {
    'save.openTitle': 'セーブファイルを開く',
    'save.modeUpload': '端末から選択',
    'save.modePath': 'サーバー上のパスを指定',
    'save.uploadHint': 'ファイル閲覧アプリ（Files等）から直接セーブファイルを選択します。'
      + '編集後は「ダウンロード」ボタンで編集済みファイルを端末に保存し、ファイルマネージャで元のファイルに上書きしてください'
      + '（ブラウザからは元の場所への直接書き込みができないため）。',
    'save.pathHint': 'このWebサーバーが動いている端末上のセーブファイルへの絶対パスを指定してください。'
      + '書き込み前に自動で <code>&lt;セーブと同じフォルダ&gt;/dq7_save_backup/</code> にバックアップを作成します。',
    'save.browse': 'フォルダを参照...',
    'save.open': '開く',
    'save.browserUp': '↑ 上へ',
    'save.browserClose': '閉じる',
    'save.write': '保存',
    'save.scalarsTitle': '所持金など',
    'save.partyTitle': 'Party（隊列, 0x0510+i*4 - 現在の並び順に入っているキャラID）',
    'save.charactorsTitle': 'Charactors（キャラ別ステータス固定枠, 0x0C80+i*STRIDE）',
    'save.rawTitle': '生バイト/フラグ（実験的 - 地点名・イベントフラグの対応は未解明）',
    'save.rawHint': '0x0020〜0x0510の生バイト領域。ルーラ解禁地点(Place.Visit、id/8バイト目のid%8ビット)を含む'
      + '何らかのフラグ配列と推定されるが、地点ID→名前の対応表は入手できていない。ビット/バイト単位で'
      + '直接編集し、実機で挙動を確認する探索用ツール。オフセットは16進数で入力してください（<code>0x</code>省略可）。',
    'save.placeIdPlaceholder': 'Place ID (例: 5)',
    'save.placeIdToggle': 'トグルを予約',
    'save.rawBitOffsetPlaceholder': 'offset (hex, 例: 20)',
    'save.rawBitToggle': 'ビットをトグル予約',
    'save.rawByteHexPlaceholder': '新しいバイト列(hex) 例: deadbeef',
    'save.rawByteWrite': 'バイト書き込みを予約',
    'save.hexDumpLabel': 'flags_region の現在のhexダンプ（予約中の変更を反映済み、offsetは絶対値）:',
    'save.gold': '所持金', 'save.bank': '銀行', 'save.casino': 'カジノコイン',
    'save.medal_bank': 'メダル預り', 'save.small_medal': 'しょうメダル',
    'save.max_damage': '最大ダメージ記録', 'save.all_gold': '稼いだ総額',
    'save.playTime': '冒険した時間',
    'save.hours': '時間', 'save.minutes': '分',
    'save.lv': 'Lv', 'save.hp': 'HP', 'save.max_hp': 'maxHP', 'save.mp': 'MP', 'save.max_mp': 'maxMP',
    'save.power': '力', 'save.defense': '守備力', 'save.speed': '素早さ', 'save.intelligence': '賢さ',
    'save.cool': 'かっこよさ', 'save.exp': '経験値', 'save.job': '職業ID',
    'save.name': '名前',
    'save.slot': 'スロット',
    'save.current': '現在',
    'save.empty': '(空き / 0)',
    'save.notInCatalog': '(カタログ外)',
    'save.checksumOk': 'checksum OK',
    'save.checksumBad': 'checksum不一致 (stored={stored}, computed={computed}) - 別デバイス種別かも',
    'save.outOfRange': '(範囲外)',
    'save.cancel': '取消',
    'save.emptyFolder': '(空のフォルダ)',
    'save.loading': '読み込み中...',
    'save.uploading': 'をアップロード中...',
    'save.timeout': 'タイムアウトしました（30秒）。ファイルが大きすぎるか、サーバーに接続できていません。',
    'save.writing': '書き込み中...',
    'save.wrote': '保存しました (backup: {backup})',
    'save.downloaded': 'ダウンロードしました ({name}) - ファイルマネージャで元のファイルに上書きしてください',
    'save.bitBadRange': 'bitは0-7で指定してください',
    'save.outOfFlagsRange': 'flags_region の範囲外のoffsetです',
    'save.hexInputHint': '16進数のバイト列を入力してください（例: deadbeef）',
    'save.baseOffsetHint': 'base offset = 0x{offset}  |  この枠は「隊列内の並び順」ではなく、キャラ固有の固定ステータス枠（推定: id={id}想定、未検証）です。',
  },
  en: {
    'save.openTitle': 'Open a Save File',
    'save.modeUpload': 'Choose from device',
    'save.modePath': 'Specify a server-side path',
    'save.uploadHint': 'Pick a save file directly from a file browser app (Files, etc). '
      + 'After editing, use the "Download" button to save the edited file to your device, '
      + 'then overwrite the original with it using a file manager '
      + '(the browser cannot write directly back to the original location).',
    'save.pathHint': 'Enter the absolute path to the save file on the device running this web server. '
      + 'A backup is automatically created at <code>&lt;save folder&gt;/dq7_save_backup/</code> before writing.',
    'save.browse': 'Browse folder...',
    'save.open': 'Open',
    'save.browserUp': '↑ Up',
    'save.browserClose': 'Close',
    'save.write': 'Save',
    'save.scalarsTitle': 'Gold, etc.',
    'save.partyTitle': 'Party (formation, 0x0510+i*4 - character ID currently in this slot)',
    'save.charactorsTitle': 'Charactors (per-character fixed status slots, 0x0C80+i*STRIDE)',
    'save.rawTitle': 'Raw bytes/flags (experimental - place name / event flag mapping unresolved)',
    'save.rawHint': 'The raw byte region 0x0020-0x0510. Presumed to be some kind of flag array including '
      + 'the Zoom-unlocked places (Place.Visit, bit id%8 of byte id/8), but no place-ID-to-name table has '
      + 'been obtained. An exploratory tool for editing bits/bytes directly and checking the effect on '
      + 'real hardware. Enter offsets in hex (the <code>0x</code> prefix is optional).',
    'save.placeIdPlaceholder': 'Place ID (e.g. 5)',
    'save.placeIdToggle': 'Queue toggle',
    'save.rawBitOffsetPlaceholder': 'offset (hex, e.g. 20)',
    'save.rawBitToggle': 'Queue bit toggle',
    'save.rawByteHexPlaceholder': 'New byte sequence (hex), e.g. deadbeef',
    'save.rawByteWrite': 'Queue byte write',
    'save.hexDumpLabel': 'Current hex dump of flags_region (reflects queued edits, offsets are absolute):',
    'save.gold': 'Gold', 'save.bank': 'Bank', 'save.casino': 'Casino Coins',
    'save.medal_bank': 'Medal Deposit', 'save.small_medal': 'Small Medals',
    'save.max_damage': 'Max Damage Record', 'save.all_gold': 'Total Gold Earned',
    'save.playTime': 'Play Time',
    'save.hours': 'h', 'save.minutes': 'm',
    'save.lv': 'Lv', 'save.hp': 'HP', 'save.max_hp': 'maxHP', 'save.mp': 'MP', 'save.max_mp': 'maxMP',
    'save.power': 'Attack', 'save.defense': 'Defense', 'save.speed': 'Agility', 'save.intelligence': 'Wisdom',
    'save.cool': 'Style', 'save.exp': 'EXP', 'save.job': 'Job ID',
    'save.name': 'Name',
    'save.slot': 'Slot',
    'save.current': 'current',
    'save.empty': '(empty / 0)',
    'save.notInCatalog': '(not in catalog)',
    'save.checksumOk': 'checksum OK',
    'save.checksumBad': 'checksum mismatch (stored={stored}, computed={computed}) - possibly a different device type',
    'save.outOfRange': '(out of range)',
    'save.cancel': 'Remove',
    'save.emptyFolder': '(empty folder)',
    'save.loading': 'Loading...',
    'save.uploading': ': uploading...',
    'save.timeout': 'Timed out (30s). The file may be too large, or the server is unreachable.',
    'save.writing': 'Writing...',
    'save.wrote': 'Saved (backup: {backup})',
    'save.downloaded': 'Downloaded ({name}) - please overwrite the original file with this using a file manager',
    'save.bitBadRange': 'Please specify a bit between 0 and 7',
    'save.outOfFlagsRange': 'This offset is outside the flags_region range',
    'save.hexInputHint': 'Please enter a hex byte sequence (e.g. deadbeef)',
    'save.baseOffsetHint': 'base offset = 0x{offset}  |  This slot is not "position within the formation" but a '
      + 'character-specific fixed status slot (presumed id={id}, unverified).',
  },
});

function SL(name) { return DQ7I18N.t('save.' + name); }

// 言語切替のたびに再評価されるよう、固定オブジェクトではなく関数にする。
function scalarLabels() {
  return {
    gold: SL('gold'), bank: SL('bank'), casino: SL('casino'), medal_bank: SL('medal_bank'),
    small_medal: SL('small_medal'), max_damage: SL('max_damage'), all_gold: SL('all_gold'),
  };
}

// +0x3250, 30fpsのフレームカウンタ。save_editor.py PLAY_TIME_OFFSET参照。
const PLAY_TIME_OFFSET = 0x3250;
const PLAY_TIME_FPS = 30;

function charFieldLabels() {
  return {
    lv: 'Lv', hp: 'HP', max_hp: 'maxHP', mp: 'MP', max_mp: 'maxMP',
    power: SL('power'), defense: SL('defense'), speed: SL('speed'), intelligence: SL('intelligence'),
    cool: SL('cool'), exp: SL('exp'), job: SL('job'),
  };
}

window.addEventListener('dq7lang:change', () => { if (current) renderAll(); });

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
  uploadMsg.textContent = `${file.name} (${(file.size / 1024).toFixed(1)}KB) ${SL('loading')}`;
  try {
    const buf = await file.arrayBuffer();
    uploadedDataB64 = arrayBufferToBase64(buf);
    uploadMsg.textContent = `${file.name}${SL('uploading')}`;

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
      uploadMsg.textContent = `${DQ7I18N.t('common.error')}: ${data.error}`;
      editPanel.style.display = 'none';
      return;
    }
    current = data;
    uploadMsg.textContent = '';
    renderAll();
  } catch (e) {
    console.error('loadFromUpload failed:', e);
    uploadMsg.textContent = e.name === 'AbortError'
      ? SL('timeout')
      : `${DQ7I18N.t('common.error')}: ${e.message || e}`;
    editPanel.style.display = 'none';
  }
}

let browserCurrentPath = null;

async function openBrowser(path) {
  browserPanel.style.display = '';
  browserList.innerHTML = `<div class="file-meta">${SL('loading')}</div>`;
  const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : '/api/browse';
  const res = await fetch(url);
  const data = await res.json();
  if (data.error) {
    browserList.innerHTML = `<div class="file-meta">${DQ7I18N.t('common.error')}: ${escapeHtml(data.error)}</div>`;
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
    browserList.innerHTML = `<div class="file-meta">${SL('emptyFolder')}</div>`;
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
  loadMsg.textContent = SL('loading');
  try {
    const res = await fetch(`/api/save/load?path=${encodeURIComponent(path)}&device=${deviceTypeEl.value}`);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`);
    }
    const data = await res.json();
    if (data.error) {
      loadMsg.textContent = `${DQ7I18N.t('common.error')}: ${data.error}`;
      editPanel.style.display = 'none';
      return;
    }
    current = data;
    loadMsg.textContent = '';
    renderAll();
  } catch (e) {
    console.error('loadSave failed:', e);
    loadMsg.textContent = `${DQ7I18N.t('common.error')}: ${e.message || e}`;
    editPanel.style.display = 'none';
  }
}

function renderAll() {
  editPanel.style.display = '';
  const ck = current.checksum_ok
    ? `<span class="checksum-ok">${SL('checksumOk')}</span>`
    : `<span class="checksum-bad">${SL('checksumBad')
        .replace('{stored}', current.checksum_stored).replace('{computed}', current.checksum_computed)}</span>`;
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
  if (Number.isNaN(v)) throw new Error(`invalid offset: ${raw}`);
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
    ? SL('outOfRange')
    : `offset=0x${offset.toString(16)} bit=${bit} ${SL('current')}: ${state ? 'ON' : 'OFF'}`;
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
    alert(SL('bitBadRange'));
    return;
  }
  const cur = effectiveBitAt(offset, bit);
  if (cur === null) {
    alert(SL('outOfFlagsRange'));
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
    alert(SL('hexInputHint'));
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
    btn.textContent = SL('cancel');
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
  const scalarLabels_ = scalarLabels();
  for (const [name, addr, size] of [
    ['gold', 0x0528], ['bank', 0x052C], ['casino', 0x0530],
    ['medal_bank', 0x0534], ['small_medal', 0x0538],
    ['max_damage', 0x053C], ['all_gold', 0x0540],
  ]) {
    const field = document.createElement('div');
    field.className = 'save-field';
    const label = document.createElement('label');
    label.textContent = `${scalarLabels_[name] || name} (+0x${addr.toString(16)})`;
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
  timeLabel.textContent = `${SL('playTime')} (+0x${PLAY_TIME_OFFSET.toString(16)})`;
  const timeWrap = document.createElement('div');
  timeWrap.className = 'play-time-wrap';
  const hoursInput = document.createElement('input');
  hoursInput.type = 'number';
  hoursInput.min = 0;
  hoursInput.max = 999;
  hoursInput.id = 'playTimeHours';
  hoursInput.value = current.scalars.play_time_hours;
  const hoursSuffix = document.createElement('span');
  hoursSuffix.textContent = SL('hours');
  const minutesInput = document.createElement('input');
  minutesInput.type = 'number';
  minutesInput.min = 0;
  minutesInput.max = 59;
  minutesInput.id = 'playTimeMinutes';
  minutesInput.value = current.scalars.play_time_minutes;
  const minutesSuffix = document.createElement('span');
  minutesSuffix.textContent = SL('minutes');
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
    label.textContent = `${SL('slot')}${i} (${SL('current')}: ${escapeHtml(slot.character_name)})`;
    const select = document.createElement('select');
    select.dataset.partySlot = String(i);
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '0';
    emptyOpt.textContent = SL('empty');
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
      opt.textContent = `#${slot.character_id} ${SL('notInCatalog')}`;
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
  hint.textContent = SL('baseOffsetHint')
    .replace('{offset}', c.base_offset.toString(16)).replace('{id}', c.presumed_character_id);
  charDetail.appendChild(hint);

  const grid = document.createElement('div');
  grid.className = 'save-grid';

  const nameField = document.createElement('div');
  nameField.className = 'save-field';
  const nameLabel = document.createElement('label');
  nameLabel.textContent = SL('name');
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.maxLength = 6;
  nameInput.dataset.charField = 'name';
  nameInput.value = c.name;
  nameField.appendChild(nameLabel);
  nameField.appendChild(nameInput);
  grid.appendChild(nameField);

  for (const [key, label] of Object.entries(charFieldLabels())) {
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
    writeMsg.textContent = `${DQ7I18N.t('common.error')}: ${e.message || e}`;
  }
}

async function writeSaveInner() {
  const patch = collectPatch();
  writeMsg.textContent = SL('writing');

  if (mode === 'path') {
    const res = await fetch('/api/save/write', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: current.path, ...patch }),
    });
    const data = await res.json();
    if (data.error) {
      writeMsg.textContent = `${DQ7I18N.t('common.error')}: ${data.error}`;
      return;
    }
    writeMsg.textContent = SL('wrote').replace('{backup}', data.backup_path);
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
    writeMsg.textContent = `${DQ7I18N.t('common.error')}: ${data.error || res.status}`;
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
  writeMsg.textContent = SL('downloaded').replace('{name}', uploadedFileName);
  renderAll();
}

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}
