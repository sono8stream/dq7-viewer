const statusBox = document.getElementById('statusBox');
const refreshStatusBtn = document.getElementById('refreshStatusBtn');
const applyBtn = document.getElementById('applyBtn');
const rescanBtn = document.getElementById('rescanBtn');
const autoPollChk = document.getElementById('autoPollChk');
const logBody = document.getElementById('logBody');
const logEmptyMsg = document.getElementById('logEmptyMsg');

let lastSeenSeq = -1;
let pollTimer = null;

function setStatusBox(text, cls) {
  statusBox.textContent = text;
  statusBox.classList.remove('ok', 'error');
  if (cls) statusBox.classList.add(cls);
}

async function refreshStatus() {
  try {
    const res = await fetch('/api/keifa_probe/status');
    const data = await res.json();
    if (!data.connected) {
      setStatusBox('未接続: AzaharのRPCサーバーに繋がりません(起動中/前面表示か確認してください)', 'error');
      return;
    }
    if (data.error) {
      setStatusBox('エラー: ' + data.error, 'error');
      return;
    }
    const lines = [
      '接続: OK',
      'パッチ適用状況: ' + (data.patched ? '適用済み' : '未適用'),
    ];
    if (data.inject_addr) lines.push('注入位置: ' + data.inject_addr);
    if (data.codecave_addr) lines.push('コードケイブ: ' + data.codecave_addr);
    if (data.message) lines.push(data.message);
    setStatusBox(lines.join('\n'), data.patched ? 'ok' : null);
  } catch (e) {
    setStatusBox('通信エラー: ' + e, 'error');
  }
}

async function applyPatch(forceRescan) {
  applyBtn.disabled = true;
  rescanBtn.disabled = true;
  setStatusBox('パッチ適用中...(ライブメモリをスキャンしています)');
  try {
    const res = await fetch('/api/keifa_probe/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force_rescan: !!forceRescan }),
    });
    const data = await res.json();
    if (data.ok) {
      const msg = data.already_patched ? '既にパッチ適用済みでした' : 'パッチを適用しました';
      setStatusBox(msg + '\n注入位置: ' + data.inject_addr + '\nコードケイブ: ' + data.codecave_addr, 'ok');
    } else {
      setStatusBox('パッチ適用に失敗: ' + (data.error || '不明なエラー'), 'error');
    }
  } catch (e) {
    setStatusBox('通信エラー: ' + e, 'error');
  } finally {
    applyBtn.disabled = false;
    rescanBtn.disabled = false;
  }
}

function renderLog(entries) {
  if (!entries.length) {
    logEmptyMsg.style.display = '';
    logBody.innerHTML = '';
    return;
  }
  logEmptyMsg.style.display = 'none';
  logBody.innerHTML = '';
  // 新しい順(seq降順)に表示
  const sorted = [...entries].sort((a, b) => b.seq - a.seq);
  for (const e of sorted) {
    const tr = document.createElement('tr');
    if (e.seq > lastSeenSeq) tr.classList.add('probe-row-new');
    tr.innerHTML = `<td>${e.seq}</td><td>0x${e.this.toString(16)}</td><td>0x${e.char_key.toString(16)} (${e.char_key})</td>`;
    logBody.appendChild(tr);
  }
  const maxSeq = Math.max(...entries.map((e) => e.seq));
  if (maxSeq > lastSeenSeq) lastSeenSeq = maxSeq;
}

async function pollLog() {
  try {
    const res = await fetch('/api/keifa_probe/log');
    const data = await res.json();
    if (data.ok) {
      renderLog(data.entries);
    }
  } catch (e) {
    // 自動更新中の一時的な通信エラーは無視(画面ロック等でよく起きる)
  }
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(() => {
    if (autoPollChk.checked) pollLog();
  }, 1000);
}

refreshStatusBtn.addEventListener('click', refreshStatus);
applyBtn.addEventListener('click', () => applyPatch(false));
rescanBtn.addEventListener('click', () => applyPatch(true));

refreshStatus();
pollLog();
startPolling();
