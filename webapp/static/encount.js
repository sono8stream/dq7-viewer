// エンカウントデータビューア - LEVELDATA/dq7_encount_data.dat (304 x 56byte) を
// 全レコード解読して表示する。バックエンドは /api/encount_data。
// レコード構造の根拠は docs/camera_encount_investigation.md
// 「dq7_encount_data.dat レコード構造の解読」/「レア(メタル系)モンスターの出にくさ」。

DQ7I18N.extend({
  ja: {
    'encount.tabList': 'レコード一覧',
    'encount.searchPlaceholder': '番号 / モンスター名 / マップコード / zone で絞り込み...',
    'encount.selectPrompt': 'レコードを選択すると 56byte の全フィールドが表示されます',
    'encount.loadFailed': '読み込み失敗',
    'encount.noMatch': '該当なし',
    'encount.specialSlot': '(特殊コード枠)',
    'encount.empty': '(空)',
    'encount.badgeSpecial': '特殊',
    'encount.badgeAEmpty': 'A空',
    'encount.colMonster': 'モンスター',
    'encount.colWeight': '重み',
    'encount.recordLabel': 'レコード',
    'encount.zoneUsers': 'このゾーンを使う部屋コード',
    'encount.noMatchingTile': '(encount_tile に該当なし)',
    'encount.specialNote': '※ arrayA に 991–999 の特殊コード。石版/すれちがい/モンスターパーク等の差し込み枠',
    'encount.arrayARoster': 'arrayA (+0x02) = ロスター',
    'encount.arrayBFormation': 'arrayB (+0x0c) = フォーメーション',
    'encount.rareSlot': '+0x18 = レア客枠 (低確率で1体加わる)',
    'encount.noneParen': '(なし)',
    'encount.fleeThreshold': '+0x1a 逃走レベル閾値',
    'encount.fleeThresholdNote': '(熟練度加算しきい値も兼ねる仮説あり)',
    'encount.battleBgm': '+0x1b 戦闘BGM番号',
    'encount.battleBgmNote': '(16=通常戦闘 M17_FIGHT, 17=ボス M18_STRONGERS, 30=M35_ORUGODEMIRA)',
    'encount.midTable': '+0x1c–0x23 mid = フォーメーション(体数/隊列)抽選表',
    'encount.midTableNote': '… roll=rand(1..mid[7]); 最初に roll<=mid[i] の i がテンプレ。i0=敵1体。小さいほど小編成',
    'encount.weights1Label': 'ブロック1 (+0x29–0x2e) = スロット別「出現重み」表 [A0..A4,B0..B3,+18,+14,+16] / 下位ニブル先。緑=メタル系',
    'encount.weights2Label': 'ブロック2 (+0x2f–0x34) = 同スロット並びの表 (btl::getAppearCountに通す数)',
    'encount.otherBytes': 'その他バイト',
    'encount.zoneAdjustNote': '(ゾーン調整値/用途未確定)',
    'encount.alwaysConst96': '(通常96固定)',
    'encount.specialId': '(特殊エンカウント番号)',
    'encount.rawBytes': 'raw (56 byte)',
    'encount.sourceNote': '根拠: docs/formats/leveldata/camera_and_encounter_data.ja.md (オフセットは EncountData::setupData が読むもの)',
  },
  en: {
    'encount.tabList': 'Records',
    'encount.searchPlaceholder': 'Filter by number / monster name / map code / zone...',
    'encount.selectPrompt': 'Select a record to see all 56 bytes of fields',
    'encount.loadFailed': 'Load failed',
    'encount.noMatch': 'No matches',
    'encount.specialSlot': '(special-code slot)',
    'encount.empty': '(empty)',
    'encount.badgeSpecial': 'special',
    'encount.badgeAEmpty': 'A empty',
    'encount.colMonster': 'monster',
    'encount.colWeight': 'weight',
    'encount.recordLabel': 'Record',
    'encount.zoneUsers': 'Room codes using this zone',
    'encount.noMatchingTile': '(no match in encount_tile)',
    'encount.specialNote': '* arrayA contains special codes 991-999: slots for tablets/StreetPass/Monster Park etc.',
    'encount.arrayARoster': 'arrayA (+0x02) = roster',
    'encount.arrayBFormation': 'arrayB (+0x0c) = formation',
    'encount.rareSlot': '+0x18 = rare-guest slot (low chance of joining)',
    'encount.noneParen': '(none)',
    'encount.fleeThreshold': '+0x1a flee level threshold',
    'encount.fleeThresholdNote': '(hypothesized to also double as a level-scaling threshold)',
    'encount.battleBgm': '+0x1b battle BGM number',
    'encount.battleBgmNote': '(16=normal battle M17_FIGHT, 17=boss M18_STRONGERS, 30=M35_ORUGODEMIRA)',
    'encount.midTable': '+0x1c-0x23 mid = formation (count/lineup) roll table',
    'encount.midTableNote': '... roll=rand(1..mid[7]); first i where roll<=mid[i] is the template. i0=1 enemy. Smaller = smaller group',
    'encount.weights1Label': 'Block 1 (+0x29-0x2e) = per-slot "appearance weight" table [A0..A4,B0..B3,+18,+14,+16] / low nibble first. Green=metal-type',
    'encount.weights2Label': 'Block 2 (+0x2f-0x34) = a table in the same slot order (counts, passed through btl::getAppearCount)',
    'encount.otherBytes': 'Other bytes',
    'encount.zoneAdjustNote': '(zone adjustment value / purpose unconfirmed)',
    'encount.alwaysConst96': '(normally fixed at 96)',
    'encount.specialId': '(special encounter id)',
    'encount.rawBytes': 'raw (56 bytes)',
    'encount.sourceNote': 'Source: docs/formats/leveldata/camera_and_encounter_data.md (offsets as read by EncountData::setupData)',
  },
});

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
  listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.loading')}</div>`;
  let data;
  try {
    data = await (await fetch('/api/encount_data')).json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('encount.loadFailed')}: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.error')}: ${esc(data.error)}</div>`;
    return;
  }
  allRecs = data.records || [];
  renderSub(data);
  statusEl.textContent = `${allRecs.length} records`;
  renderList();
}

let lastListData = null;
function renderSub(data) {
  lastListData = data;
  if (DQ7I18N.getLang() === 'en') {
    subEl.textContent =
      `${data.source} — ${data.record_count} records x ${data.record_size} bytes. ` +
      `zone = index//2 / region = index%2. Click a row for details.`;
  } else {
    subEl.textContent =
      `${data.source} — ${data.record_count} レコード x ${data.record_size}byte。` +
      `zone = index//2 / region = index%2。行クリックで詳細。`;
  }
}

function monSummary(rec) {
  const names = rec.arrayA.filter(m => m.id).map(m => m.name);
  if (!names.length && rec.is_special) return DQ7I18N.t('encount.specialSlot');
  if (!names.length) return rec.arrayB.filter(m => m.id).map(m => m.name).join(' ') || DQ7I18N.t('encount.empty');
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
      (r.is_special ? `<span class="badge sp">${esc(DQ7I18N.t('encount.badgeSpecial'))}</span>` : '') +
      (r.is_empty && !r.is_special ? `<span class="badge em">${esc(DQ7I18N.t('encount.badgeAEmpty'))}</span>` : '');
    return `<div class="enc-row${r.index === selectedIdx ? ' selected' : ''}" data-idx="${r.index}">
      <span class="eid">#${r.index}</span>
      <span class="ezone">z${r.zone}/r${r.region}</span>
      <span class="emons">${esc(monSummary(r))}</span>
      ${badges}
    </div>`;
  }).join('') || `<div class="empty">${DQ7I18N.t('encount.noMatch')}</div>`;
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
    `<table class="wt"><tr><th>slot</th><th>id</th><th>${esc(DQ7I18N.t('encount.colMonster'))}</th><th>${esc(DQ7I18N.t('encount.colWeight'))}</th></tr>${trs}</table>`;
}

function selectRec(idx) {
  selectedIdx = idx;
  renderList();
  if (window.matchMedia('(max-width: 760px)').matches) showPane('detail');
  renderDetail(idx);
}

function renderDetail(idx) {
  const t = DQ7I18N.t;
  const r = allRecs.find(x => x.index === idx);
  if (!r) return;

  const A = r.arrayA.map(m => m.id ? `${m.id}:${m.name}` : '—').join(' , ');
  const B = r.arrayB.map(m => m.id ? `${m.id}:${m.name}` : '—').join(' , ');
  const midv = r.mid.join(', ');

  let h = '';
  h += `<div class="sec">${t('encount.recordLabel')} #${r.index}  (zone ${r.zone} / region ${r.region})</div>`;
  h += `<div>${t('encount.zoneUsers')}: ${r.maps.length ? esc(r.maps.join(', ')) : t('encount.noMatchingTile')}</div>`;
  if (r.is_special) h += `<div style="color:#a5642b">${t('encount.specialNote')}</div>`;

  h += `<div class="sec">${t('encount.arrayARoster')}</div><div class="mono">${esc(A)}</div>`;
  h += `<div class="sec">${t('encount.arrayBFormation')}</div><div class="mono">${esc(B)}</div>`;
  h += `<div class="sec">${t('encount.rareSlot')}</div>`;
  h += `<div class="mono">${r.extra_rare.id ? esc(r.extra_rare.id + ':' + r.extra_rare.name) : t('encount.noneParen')}</div>`;

  h += `<div class="sec">${t('encount.fleeThreshold')} = ${r.flee_level}` +
       `<span style="color:var(--muted)"> ${t('encount.fleeThresholdNote')}</span></div>`;
  h += `<div class="sec">${t('encount.battleBgm')} = ${r.bgm}` +
       `<span style="color:var(--muted)"> ${t('encount.battleBgmNote')}</span></div>`;

  h += `<div class="sec">${t('encount.midTable')}</div>`;
  h += `<div class="mono">[${esc(midv)}]  ${t('encount.midTableNote')}</div>`;

  h += wtTable(r.weights1, t('encount.weights1Label'));
  h += wtTable(r.weights2, t('encount.weights2Label'));

  h += `<div class="sec">${t('encount.otherBytes')}</div>`;
  h += `<div class="mono">+0x24=${r.x24} ${t('encount.zoneAdjustNote')}  +0x25=${r.special} ${t('encount.specialId')}  ` +
       `+0x26=${r.x26} ${t('encount.alwaysConst96')}  +0x27=${r.x27}  +0x28=${r.x28}</div>`;

  h += `<div class="sec">${t('encount.rawBytes')}</div><div class="mono">${r.raw_hex.replace(/(..)/g, '$1 ').trim()}</div>`;
  h += `<div class="sec" style="color:var(--muted);font-weight:normal">${t('encount.sourceNote')}</div>`;

  detailEl.innerHTML = h;
}

window.addEventListener('dq7lang:change', () => {
  if (lastListData) renderSub(lastListData);
  renderList();
  if (selectedIdx !== null) renderDetail(selectedIdx);
});

loadList();
