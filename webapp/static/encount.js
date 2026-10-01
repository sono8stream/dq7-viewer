// エンカウントデータビューア - LEVELDATA/dq7_encount_data.dat (304 x 56byte) を
// 全レコード解読して表示する。バックエンドは /api/encount_data。
// レコード構造の根拠は docs/camera_encount_investigation.md
// 「dq7_encount_data.dat レコード構造の解読」/「レア(メタル系)モンスターの出にくさ」。

const listInner = document.getElementById('encListInner');
const searchBox = document.getElementById('encSearch');
const subEl = document.getElementById('encSub');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');

let allRecs = [];
let selectedIdx = null;

const METAL_RE = /(メタル|はぐれ|プラチナ|ゴールデン|ドラゴメタル)/;

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

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

async function loadList() {
  listInner.innerHTML = '<div class="empty">読み込み中...</div>';
  let data;
  try {
    data = await (await fetch('/api/encount_data')).json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">読み込み失敗: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">エラー: ${esc(data.error)}</div>`;
    return;
  }
  allRecs = data.records || [];
  subEl.textContent =
    `${data.source} — ${data.record_count} レコード x ${data.record_size}byte。` +
    `zone = index//2 / region = index%2。行クリックで詳細。`;
  statusEl.textContent = `${allRecs.length} records`;
  renderList();
}

function monSummary(rec) {
  const names = rec.arrayA.filter(m => m.id).map(m => m.name);
  if (!names.length && rec.is_special) return '(特殊コード枠)';
  if (!names.length) return rec.arrayB.filter(m => m.id).map(m => m.name).join(' ') || '(空)';
  return names.join(' ');
}

function renderList() {
  const q = searchBox.value.trim().toLowerCase();
  const rows = allRecs.filter(r => {
    if (!q) return true;
    if (String(r.index) === q || String(r.index).includes(q)) return true;
    if (('zone ' + r.zone).includes(q) || String(r.zone) === q) return true;
    if (r.maps.some(m => m.toLowerCase().includes(q))) return true;
    const all = [...r.arrayA, ...r.arrayB, r.extra_rare];
    return all.some(m => m.name && m.name.toLowerCase().includes(q));
  });
  listInner.innerHTML = rows.map(r => {
    const badges =
      (r.is_special ? '<span class="badge sp">特殊</span>' : '') +
      (r.is_empty && !r.is_special ? '<span class="badge em">A空</span>' : '');
    return `<div class="enc-row${r.index === selectedIdx ? ' selected' : ''}" data-idx="${r.index}">
      <span class="eid">#${r.index}</span>
      <span class="ezone">z${r.zone}/r${r.region}</span>
      <span class="emons">${esc(monSummary(r))}</span>
      ${badges}
    </div>`;
  }).join('') || '<div class="empty">該当なし</div>';
  listInner.querySelectorAll('.enc-row').forEach(el => {
    el.addEventListener('click', () => selectRec(parseInt(el.dataset.idx, 10)));
  });
}
searchBox.addEventListener('input', renderList);

function wtTable(rows, label) {
  const trs = rows.map(w => {
    const cls = w.name && METAL_RE.test(w.name) ? ' class="metal"' : '';
    return `<tr${cls}><td>${esc(w.slot)}</td><td>${w.id || ''}</td>` +
      `<td>${esc(w.name || '—')}</td><td class="w">${w.w}</td></tr>`;
  }).join('');
  return `<div class="sec">${esc(label)}</div>` +
    `<table class="wt"><tr><th>slot</th><th>id</th><th>モンスター</th><th>重み</th></tr>${trs}</table>`;
}

function selectRec(idx) {
  selectedIdx = idx;
  renderList();
  if (window.matchMedia('(max-width: 760px)').matches) showPane('detail');
  const r = allRecs.find(x => x.index === idx);
  if (!r) return;

  const A = r.arrayA.map(m => m.id ? `${m.id}:${m.name}` : '—').join(' , ');
  const B = r.arrayB.map(m => m.id ? `${m.id}:${m.name}` : '—').join(' , ');
  const midv = r.mid.join(', ');

  let h = '';
  h += `<div class="sec">レコード #${r.index}  (zone ${r.zone} / region ${r.region})</div>`;
  h += `<div>このゾーンを使う部屋コード: ${r.maps.length ? esc(r.maps.join(', ')) : '(encount_tile に該当なし)'}</div>`;
  if (r.is_special) h += `<div style="color:#a5642b">※ arrayA に 991–999 の特殊コード。石版/すれちがい/モンスターパーク等の差し込み枠</div>`;

  h += `<div class="sec">arrayA (+0x06) = ロスター</div><div class="mono">${esc(A)}</div>`;
  h += `<div class="sec">arrayB (+0x10) = フォーメーション</div><div class="mono">${esc(B)}</div>`;
  h += `<div class="sec">+0x1c = レア客枠 (低確率で1体加わる)</div>`;
  h += `<div class="mono">${r.extra_rare.id ? esc(r.extra_rare.id + ':' + r.extra_rare.name) : '(なし)'}</div>`;

  h += `<div class="sec">+0x1e 逃走レベル閾値 = ${r.flee_level}` +
       `<span style="color:var(--muted)"> (熟練度加算しきい値も兼ねる仮説あり)</span></div>`;
  h += `<div>+0x1f = ${r.x1f} (実データは常に16)</div>`;

  h += `<div class="sec">+0x20–0x27 mid = フォーメーション(体数/隊列)抽選表</div>`;
  h += `<div class="mono">[${esc(midv)}]  … roll=rand(1..mid[7]); 最初に roll<=mid[i] の i がテンプレ。i0=敵1体。小さいほど小編成</div>`;

  h += wtTable(r.weights1, 'ブロック1 (+0x2d–0x31) = スロット別「出現重み」表 [A0..A4,B0..B3,+1c] / 下位ニブル先。緑=メタル系');
  h += wtTable(r.weights2, 'ブロック2 (+0x33–0x37) = 同スロット並びの別軸重み (意味未確定)');

  h += `<div class="sec">その他バイト</div>`;
  h += `<div class="mono">+0x28=${r.x28} (ゾーン調整値/用途未確定)  +0x29=${r.x29}  ` +
       `+0x2a=${r.x2a} (通常96固定)  +0x2b=${r.x2b}  +0x2c=${r.x2c}  +0x32=${r.x32} (区切り)</div>`;

  h += `<div class="sec">raw (56 byte)</div><div class="mono">${r.raw_hex.replace(/(..)/g, '$1 ').trim()}</div>`;
  h += `<div class="sec" style="color:var(--muted);font-weight:normal">根拠: docs/camera_encount_investigation.md 「レコード構造の解読」/「レア(メタル系)モンスターの出にくさの実装」</div>`;

  detailEl.innerHTML = h;
}

loadList();
