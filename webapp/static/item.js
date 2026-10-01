// アイテムデータビューア - LEVELDATA/dq7_item_list.dat (670 x 52byte) を
// 全レコード解読して表示する。バックエンドは /api/item_list。
// 構造の根拠は docs/camera_encount_investigation.md
// 「アイテムでエンカウント抑止(ゴスペルリング/せいすい/トヘロス)からの手がかり調査」。

const listInner = document.getElementById('itemListInner');
const searchBox = document.getElementById('itemSearch');
const subEl = document.getElementById('itemSub');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');

let allItems = [];
let selectedIdx = null;

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
    data = await (await fetch('/api/item_list')).json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">読み込み失敗: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">エラー: ${esc(data.error)}</div>`;
    return;
  }
  allItems = data.records || [];
  window._itemNote = data.note || '';
  subEl.textContent =
    `${data.source} — ${data.record_count} レコード x ${data.record_size}byte。行クリックで詳細。`;
  statusEl.textContent = `${allItems.length} items`;
  renderList();
}

function renderList() {
  const q = searchBox.value.trim().toLowerCase();
  const rows = allItems.filter(it => {
    if (!q) return true;
    if (String(it.index).includes(q)) return true;
    if (it.name && it.name.toLowerCase().includes(q)) return true;
    if (it.param_kind_label && it.param_kind_label.toLowerCase().includes(q)) return true;
    if (it.slot_label && it.slot_label.toLowerCase().includes(q)) return true;
    if (('effect ' + it.effect_id).includes(q)) return true;
    return false;
  });
  listInner.innerHTML = rows.map(it => `
    <div class="it-row${it.index === selectedIdx ? ' selected' : ''}" data-idx="${it.index}">
      <span class="iid">#${it.index}</span>
      <span class="icat">${esc(it.param_kind_label)}</span>
      <span class="inm${it.name ? '' : ' noname'}">${esc(it.name || '(名前なし)')}</span>
    </div>`).join('') || '<div class="empty">該当なし</div>';
  listInner.querySelectorAll('.it-row').forEach(el => {
    el.addEventListener('click', () => selectItem(parseInt(el.dataset.idx, 10)));
  });
}
searchBox.addEventListener('input', renderList);

function bits(v) {
  const set = [];
  for (let b = 7; b >= 0; b--) if (v & (1 << b)) set.push('bit' + b);
  return `0x${v.toString(16).padStart(2, '0')} (${v})` + (set.length ? '  [' + set.join(' ') + ']' : '');
}

function selectItem(idx) {
  selectedIdx = idx;
  renderList();
  if (window.matchMedia('(max-width: 760px)').matches) showPane('detail');
  const it = allItems.find(x => x.index === idx);
  if (!it) return;

  const row = (off, label, val, hint) =>
    `<tr><th>${off}</th><th>${esc(label)}</th><td class="v">${esc(val)}</td>` +
    `<td class="hint">${hint ? esc(hint) : ''}</td></tr>`;

  let h = '';
  h += `<div class="sec">#${it.index}  ${esc(it.name || '(名前なし)')}</div>`;
  h += `<table class="kv2"><tr><th>offset</th><th>フィールド</th><th>値</th><th></th></tr>`;
  h += row('+0x00', 'type_flags', it.type_flags, 'タイプ/フラグ');
  h += row('+0x08', 'name_id', it.name_id, '名前文字列ID (0x0c〜セグメント)');
  h += row('+0x0c', 'ptr0c', '0x' + it.ptr0c.toString(16), '0x0c〜セグメントへのポインタ (消耗品は3種を共用)');
  h += row('+0x10', 'buy', it.buy, '買値 (0 = 非売品)');
  h += row('+0x14', 'sell', it.sell, '売値 (多くは買値/2)');
  h += row('+0x16', 'desc_id', it.desc_id, '説明文テキストID');
  h += row('+0x1a', 'effect_id', it.effect_id,
           '効果 / カタログID。0 = 特殊効果なし。ExeFS のディスパッチキー');
  h += row('+0x1c', 'effect_param', it.effect_param, '効果パラメータ');
  h += row('+0x20', 'item_id', it.item_id, '= レコード番号');
  h += row('+0x22', 'param_value', it.param_value,
           `+0x2c(${it.param_kind_label}) への加算値`);
  h += row('+0x24', 'stat_mod', it.stat_mod, '補正値 (剣は負値=命中/両手ペナ?)');
  h += row('+0x28', 'stat_x28', it.stat_x28, '追加ステータス (耐性 等)');
  h += row('+0x2c', 'param_kind', `${it.param_kind} = ${it.param_kind_label}`,
           '効果対象パラメータ種別 (1=攻撃 2=守備 3=素早 4=賢さ 5=運/特殊 6+=非装備)');
  h += row('+0x2d', 'slot', `${it.slot} = ${it.slot_label}`, '装備スロット/小分類');
  h += row('+0x33', 'shop_flags', bits(it.shop_flags),
           'ショップ系ビット (買/売/捨。一点物は 0x40)');
  h += `</table>`;

  h += `<div class="sec">raw (52 byte)</div><div class="mono">${it.raw_hex.replace(/(..)/g, '$1 ').trim()}</div>`;
  h += `<div class="sec hint" style="font-weight:normal">${esc(window._itemNote || '')}</div>`;
  h += `<div class="hint">根拠: docs/camera_encount_investigation.md 「アイテムでエンカウント抑止 … からの手がかり調査」</div>`;

  detailEl.innerHTML = h;
}

loadList();
