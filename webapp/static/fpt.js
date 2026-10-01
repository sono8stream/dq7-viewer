const fileListInner = document.getElementById('fileListInner');
const fileSearch = document.getElementById('fileSearch');
const treeEl = document.getElementById('tree');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');

let allFiles = [];
let currentParsed = null;

const isMobile = () => window.matchMedia('(max-width: 760px)').matches;

function showPane(name) {
  document.querySelectorAll('.pane').forEach(p => p.classList.remove('mobile-active'));
  document.getElementById(name).classList.add('mobile-active');
  mobileTabs.querySelectorAll('button').forEach(b => {
    b.classList.toggle('active', b.dataset.pane === name);
  });
}

mobileTabs.querySelectorAll('button').forEach(b => {
  b.addEventListener('click', () => showPane(b.dataset.pane));
});

async function loadFiles() {
  const res = await fetch('/api/fpt_files');
  allFiles = await res.json();
  renderFileList();
}

function renderFileList() {
  const q = fileSearch.value.trim().toLowerCase();
  fileListInner.innerHTML = '';
  const filtered = q ? allFiles.filter(f => f.name.toLowerCase().includes(q)) : allFiles;
  statusEl.textContent = `${filtered.length} / ${allFiles.length} files`;
  for (const f of filtered) {
    const div = document.createElement('div');
    div.className = 'file-item';
    div.textContent = f.name;
    const meta = document.createElement('span');
    meta.className = 'file-meta';
    meta.textContent = `${(f.size / 1024).toFixed(1)}KB`;
    div.appendChild(meta);
    div.onclick = () => selectFile(f.name, div);
    fileListInner.appendChild(div);
  }
}

fileSearch.addEventListener('input', renderFileList);

async function selectFile(name, el) {
  document.querySelectorAll('.file-item.active').forEach(x => x.classList.remove('active'));
  if (el) el.classList.add('active');
  treeEl.innerHTML = '<div class="empty">読み込み中...</div>';
  detailEl.innerHTML = '<div class="empty">エントリを選択すると詳細が表示されます</div>';
  const res = await fetch(`/api/fpt_parse?file=${encodeURIComponent(name)}`);
  const parsed = await res.json();
  if (parsed.error) {
    treeEl.innerHTML = `<div class="empty">エラー: ${parsed.error}</div>`;
    return;
  }
  currentParsed = parsed;
  renderEntries(parsed);
  if (isMobile()) showPane('tree');
}

function renderEntries(parsed) {
  treeEl.innerHTML = '';
  const header = document.createElement('div');
  header.className = 'file-meta';
  header.style.marginBottom = '6px';
  header.textContent = `${parsed.file} (${parsed.file_size} bytes, ${parsed.entries.length} entries, ` +
    `file_count=${parsed.header.file_count}, temp_count=${parsed.header.temp_count})`;
  treeEl.appendChild(header);

  parsed.entries.forEach((e, i) => {
    const div = document.createElement('div');
    div.className = 'entry-item' + (i > 0 && !e.contiguous_with_prev ? ' gap' : '');
    const label = e.text ? previewLabel(e.text) : '(no text)';
    div.textContent = `${e.filename} ${label}`;
    div.title = e.filename;
    div.onclick = () => {
      document.querySelectorAll('.entry-item.selected').forEach(x => x.classList.remove('selected'));
      div.classList.add('selected');
      showEntryDetail(e, i);
      if (isMobile()) showPane('detail');
    };
    treeEl.appendChild(div);
  });
}

function showEntryDetail(e, i) {
  const lines = [];
  lines.push(`entry #${i}: ${e.filename}`);
  lines.push(`addr_info: ${e.addr_info} (0x${e.addr_info.toString(16)})`);
  lines.push(`msg_offset (raw, relative to data_start): ${e.msg_offset} (0x${e.msg_offset.toString(16)})`);
  lines.push(`data_start: ${currentParsed.header.data_start}`);
  lines.push(`true_offset (data_start + msg_offset): ${e.true_offset} (0x${e.true_offset.toString(16)})`);
  lines.push(`msg_count (bytes): ${e.msg_count}`);
  lines.push(`true_offset + msg_count: ${e.true_offset + e.msg_count}`);
  lines.push(`contiguous with previous entry: ${e.contiguous_with_prev}` +
    (i > 0 && !e.contiguous_with_prev ? '  <- ストリームの区切り目/ギャップ' : ''));

  detailEl.innerHTML = '';
  const pre = document.createElement('div');
  pre.textContent = lines.join('\n');
  detailEl.appendChild(pre);

  const box = document.createElement('div');
  box.className = 'msgtext';
  box.textContent = e.text || '(empty)';
  detailEl.appendChild(box);
}

// Same heuristic as script/app.js's previewLabel: MESS entries are chunks
// of one continuous text stream (not per-sentence), so raw text often
// starts mid-word; skip past the first inline "#NNNN"/"TALKER=NNNN"
// speaker-marker to find this entry's own actual line.
function previewLabel(text) {
  const rawLines = text.split('\r\n');
  let firstMarker = rawLines.findIndex(
    l => /^#\d+$/.test(l.trim()) || /^TALKER=\d+$/.test(l.trim())
  );

  const clean = (line) => {
    line = line.replace(/^�+/, '');
    const rubyTail = line.match(/^[^{]{0,6}\}/);
    if (rubyTail) line = line.slice(rubyTail[0].length);
    return line.trim();
  };

  if (firstMarker >= 0) {
    for (let i = firstMarker + 1; i < rawLines.length; i++) {
      const line = clean(rawLines[i]);
      if (line) return line.slice(0, 40);
    }
  }

  let fallback = '';
  for (const raw of rawLines) {
    const line = clean(raw);
    if (!line) continue;
    if (/^#\d+$/.test(line) || /^TALKER=\d+$/.test(line)) continue;
    if (!fallback) fallback = line;
    if (line.length >= 6) return line.slice(0, 40);
  }
  return (fallback || text.replace(/�/g, '')).slice(0, 40);
}

loadFiles();
