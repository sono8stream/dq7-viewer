DQ7I18N.extend({
  ja: {
    'keifa.title': 'キーファ転職アニメ調査 - ライブメモリプローブ',
    'keifa.hint1': 'Azahar(RPCサーバー、config.ini <code>enable_rpc_server=true</code>、UDP:45987)経由で、'
      + '実機のCharacterObject::getMotionIndex内 <code>[CharacterObject+0x98]</code>'
      + '(job×character×motionType探索の「characterキー」)を、ロジックを変更せず'
      + 'コードケイブ経由で観測するプローブです。詳細は'
      + '<code>docs/keifa_job_animation_investigation.md</code> と'
      + '<code>webapp/dq7_rpc_probe.py</code> を参照。',
    'keifa.hint2': 'アドレスはビルド(実験パッチの有無など)ごとにズレるため、「パッチを適用」を押すたびに'
      + 'ライブメモリを直接スキャンして対象命令列を再特定してから当てます'
      + '(既に同じ位置にパッチ済みなら何もしません)。',
    'keifa.refreshStatus': '状態を確認',
    'keifa.applyPatch': 'パッチを適用',
    'keifa.rescan': '強制的に再スキャンして適用',
    'keifa.autoPoll': '自動更新(1秒毎)',
    'keifa.unconfirmed': '未確認',
    'keifa.thisCol': 'this (CharacterObject)',
    'keifa.charKeyCol': '[this+0x98] characterキー',
    'keifa.logEmpty': 'まだ記録がありません。パッチ適用後、実機でキャラを歩かせてください(walk/run/dashの度に1件記録されます。直近16件のリングバッファ)。',
    'keifa.notConnected': '未接続: AzaharのRPCサーバーに繋がりません(起動中/前面表示か確認してください)',
    'keifa.connectedOk': '接続: OK',
    'keifa.patchStatus': 'パッチ適用状況: ',
    'keifa.patched': '適用済み',
    'keifa.notPatched': '未適用',
    'keifa.injectAddr': '注入位置: ',
    'keifa.codecaveAddr': 'コードケイブ: ',
    'keifa.applying': 'パッチ適用中...(ライブメモリをスキャンしています)',
    'keifa.alreadyPatched': '既にパッチ適用済みでした',
    'keifa.appliedOk': 'パッチを適用しました',
    'keifa.applyFailed': 'パッチ適用に失敗: ',
    'keifa.unknownError': '不明なエラー',
    'keifa.commError': '通信エラー: ',
  },
  en: {
    'keifa.title': 'Kiefer Job-Change Animation Investigation - Live Memory Probe',
    'keifa.hint1': 'A probe, via Azahar (RPC server, config.ini <code>enable_rpc_server=true</code>, UDP:45987), '
      + 'that observes <code>[CharacterObject+0x98]</code> inside the real hardware\'s CharacterObject::getMotionIndex '
      + '(the "character key" of the job x character x motionType search) through a code cave, without changing '
      + 'the logic. See <code>docs/keifa_job_animation_investigation.md</code> and '
      + '<code>webapp/dq7_rpc_probe.py</code> for details.',
    'keifa.hint2': 'Addresses shift per build (depending on experimental patches etc.), so every time you press '
      + '"Apply Patch" it directly scans live memory to re-locate the target instruction sequence before patching '
      + '(does nothing if already patched at the same location).',
    'keifa.refreshStatus': 'Check Status',
    'keifa.applyPatch': 'Apply Patch',
    'keifa.rescan': 'Force Rescan & Apply',
    'keifa.autoPoll': 'Auto-refresh (every 1s)',
    'keifa.unconfirmed': 'Not checked',
    'keifa.thisCol': 'this (CharacterObject)',
    'keifa.charKeyCol': '[this+0x98] character key',
    'keifa.logEmpty': 'No records yet. After applying the patch, walk a character on real hardware '
      + '(one entry is recorded per walk/run/dash; a ring buffer of the last 16).',
    'keifa.notConnected': 'Not connected: cannot reach Azahar\'s RPC server (check it is running/foregrounded)',
    'keifa.connectedOk': 'Connected: OK',
    'keifa.patchStatus': 'Patch status: ',
    'keifa.patched': 'applied',
    'keifa.notPatched': 'not applied',
    'keifa.injectAddr': 'Inject address: ',
    'keifa.codecaveAddr': 'Code cave: ',
    'keifa.applying': 'Applying patch...(scanning live memory)',
    'keifa.alreadyPatched': 'Already patched',
    'keifa.appliedOk': 'Patch applied',
    'keifa.applyFailed': 'Patch failed: ',
    'keifa.unknownError': 'Unknown error',
    'keifa.commError': 'Communication error: ',
  },
});

const statusBox = document.getElementById('statusBox');
const refreshStatusBtn = document.getElementById('refreshStatusBtn');
const applyBtn = document.getElementById('applyBtn');
const rescanBtn = document.getElementById('rescanBtn');
const autoPollChk = document.getElementById('autoPollChk');
const logBody = document.getElementById('logBody');
const logEmptyMsg = document.getElementById('logEmptyMsg');

let lastSeenSeq = -1;
let pollTimer = null;

function KT(key) { return DQ7I18N.t('keifa.' + key); }

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
      setStatusBox(KT('notConnected'), 'error');
      return;
    }
    if (data.error) {
      setStatusBox(DQ7I18N.t('common.error') + ': ' + data.error, 'error');
      return;
    }
    const lines = [
      KT('connectedOk'),
      KT('patchStatus') + (data.patched ? KT('patched') : KT('notPatched')),
    ];
    if (data.inject_addr) lines.push(KT('injectAddr') + data.inject_addr);
    if (data.codecave_addr) lines.push(KT('codecaveAddr') + data.codecave_addr);
    if (data.message) lines.push(data.message);
    setStatusBox(lines.join('\n'), data.patched ? 'ok' : null);
  } catch (e) {
    setStatusBox(KT('commError') + e, 'error');
  }
}

async function applyPatch(forceRescan) {
  applyBtn.disabled = true;
  rescanBtn.disabled = true;
  setStatusBox(KT('applying'));
  try {
    const res = await fetch('/api/keifa_probe/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force_rescan: !!forceRescan }),
    });
    const data = await res.json();
    if (data.ok) {
      const msg = data.already_patched ? KT('alreadyPatched') : KT('appliedOk');
      setStatusBox(msg + '\n' + KT('injectAddr') + data.inject_addr + '\n' + KT('codecaveAddr') + data.codecave_addr, 'ok');
    } else {
      setStatusBox(KT('applyFailed') + (data.error || KT('unknownError')), 'error');
    }
  } catch (e) {
    setStatusBox(KT('commError') + e, 'error');
  } finally {
    applyBtn.disabled = false;
    rescanBtn.disabled = false;
  }
}

window.addEventListener('dq7lang:change', refreshStatus);

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
