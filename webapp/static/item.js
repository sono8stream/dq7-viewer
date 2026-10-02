// アイテムデータビューア - LEVELDATA/dq7_item_list.dat (670 x 52byte) を
// 全レコード解読して表示する。バックエンドは /api/item_list。
// 構造の根拠は docs/camera_encount_investigation.md
// 「アイテムでエンカウント抑止(ゴスペルリング/せいすい/トヘロス)からの手がかり調査」。

DQ7I18N.extend({
  ja: {
    'item.tabList': 'アイテム一覧',
    'item.tabDetail': '詳細',
    'item.searchPlaceholder': '番号 / 名前 / 分類 / effect_id で絞り込み...',
    'item.selectHint': 'アイテムを選択すると 52byte の全フィールドが表示されます',
    'item.noMatch': '該当なし',
    'item.noName': '(名前なし)',
    'item.records': 'レコード',
    'item.clickRowHint': '行クリックで詳細。',
    'item.loadFailed': '読み込み失敗',
    'common.offset': 'offset',
    'common.field': 'フィールド',
    'common.value': '値',
    'item.fTypeFlags': 'タイプ/フラグ',
    'item.fNameId': '名前文字列ID (0x0c〜セグメント)',
    'item.fPtr0c': '0x0c〜セグメントへのポインタ (消耗品は3種を共用)',
    'item.fBuy': '買値 (0 = 非売品)',
    'item.fSell': '売値 (多くは買値/2)',
    'item.fDescId': '説明文テキストID',
    'item.fEffectId': '効果 / カタログID。0 = 特殊効果なし。ExeFS のディスパッチキー',
    'item.fEffectParam': '効果パラメータ',
    'item.fItemId': '= レコード番号',
    'item.fParamValuePrefix': 'への加算値',
    'item.fStatMod': '補正値 (剣は負値=命中/両手ペナ?)',
    'item.fStatX28': '追加ステータス (耐性 等)',
    'item.fParamKind': '効果対象パラメータ種別 (1=攻撃 2=守備 3=素早 4=賢さ 5=運/特殊 6+=非装備)',
    'item.fSlot': '装備スロット/小分類',
    'item.fShopFlags': 'ショップ系ビット (買/売/捨。一点物は 0x40)',
    'item.rawHeading': 'raw (52 byte)',
    'item.basedOn': '根拠',
  },
  en: {
    'item.tabList': 'Item List',
    'item.tabDetail': 'Detail',
    'item.searchPlaceholder': 'Filter by number / name / category / effect_id...',
    'item.selectHint': 'Select an item to see all 52 bytes of fields',
    'item.noMatch': 'No matches',
    'item.noName': '(no name)',
    'item.records': 'records',
    'item.clickRowHint': 'Click a row for details.',
    'item.loadFailed': 'Load failed',
    'common.offset': 'offset',
    'common.field': 'field',
    'common.value': 'value',
    'item.fTypeFlags': 'Type/flags',
    'item.fNameId': 'Name string ID (0x0c~ segment)',
    'item.fPtr0c': 'Pointer into the 0x0c~ segment (consumables share 3 kinds)',
    'item.fBuy': 'Buy price (0 = not for sale)',
    'item.fSell': 'Sell price (often buy price / 2)',
    'item.fDescId': 'Description text ID',
    'item.fEffectId': 'Effect/catalog ID. 0 = no special effect. ExeFS dispatch key',
    'item.fEffectParam': 'Effect parameter',
    'item.fItemId': '= record number',
    'item.fParamValuePrefix': 'bonus added to',
    'item.fStatMod': 'Modifier (negative on swords = accuracy/two-handed penalty?)',
    'item.fStatX28': 'Extra stat (resistances etc.)',
    'item.fParamKind': 'Target stat for the effect (1=attack 2=defense 3=agility 4=wisdom 5=luck/special 6+=non-equipment)',
    'item.fSlot': 'Equipment slot/subcategory',
    'item.fShopFlags': 'Shop bitfield (buy/sell/discard; 0x40 = unique item)',
    'item.rawHeading': 'raw (52 bytes)',
    'item.basedOn': 'Based on',
  },
});

function plabel(it) {
  return DQ7I18N.getLang() === 'en' ? (it.param_kind_label_en || it.param_kind_label) : it.param_kind_label;
}
function slabel(it) {
  return DQ7I18N.getLang() === 'en' ? (it.slot_label_en || it.slot_label) : it.slot_label;
}

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
  listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.loading')}</div>`;
  let data;
  try {
    data = await (await fetch('/api/item_list')).json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('item.loadFailed')}: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.error')}: ${esc(data.error)}</div>`;
    return;
  }
  allItems = data.records || [];
  window._itemNote = data.note || '';
  subEl.textContent =
    `${data.source} — ${data.record_count} ${DQ7I18N.t('item.records')} x ${data.record_size}byte. ${DQ7I18N.t('item.clickRowHint')}`;
  statusEl.textContent = `${allItems.length} items`;
  renderList();
}
window.addEventListener('dq7lang:change', () => { renderList(); if (selectedIdx !== null) selectItem(selectedIdx); });

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
      <span class="icat">${esc(plabel(it))}</span>
      <span class="inm${it.name ? '' : ' noname'}">${esc(it.name || DQ7I18N.t('item.noName'))}</span>
    </div>`).join('') || `<div class="empty">${DQ7I18N.t('item.noMatch')}</div>`;
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
  h += `<div class="sec">#${it.index}  ${esc(it.name || DQ7I18N.t('item.noName'))}</div>`;
  h += `<table class="kv2"><tr><th>${DQ7I18N.t('common.offset')}</th><th>${DQ7I18N.t('common.field')}</th><th>${DQ7I18N.t('common.value')}</th><th></th></tr>`;
  h += row('+0x00', 'type_flags', it.type_flags, DQ7I18N.t('item.fTypeFlags'));
  h += row('+0x08', 'name_id', it.name_id, DQ7I18N.t('item.fNameId'));
  h += row('+0x0c', 'ptr0c', '0x' + it.ptr0c.toString(16), DQ7I18N.t('item.fPtr0c'));
  h += row('+0x10', 'buy', it.buy, DQ7I18N.t('item.fBuy'));
  h += row('+0x14', 'sell', it.sell, DQ7I18N.t('item.fSell'));
  h += row('+0x16', 'desc_id', it.desc_id, DQ7I18N.t('item.fDescId'));
  h += row('+0x1a', 'effect_id', it.effect_id, DQ7I18N.t('item.fEffectId'));
  h += row('+0x1c', 'effect_param', it.effect_param, DQ7I18N.t('item.fEffectParam'));
  h += row('+0x20', 'item_id', it.item_id, DQ7I18N.t('item.fItemId'));
  h += row('+0x22', 'param_value', it.param_value,
           `+0x2c(${plabel(it)}) ${DQ7I18N.t('item.fParamValuePrefix')}`);
  h += row('+0x24', 'stat_mod', it.stat_mod, DQ7I18N.t('item.fStatMod'));
  h += row('+0x28', 'stat_x28', it.stat_x28, DQ7I18N.t('item.fStatX28'));
  h += row('+0x2c', 'param_kind', `${it.param_kind} = ${plabel(it)}`, DQ7I18N.t('item.fParamKind'));
  h += row('+0x2d', 'slot', `${it.slot} = ${slabel(it)}`, DQ7I18N.t('item.fSlot'));
  h += row('+0x33', 'shop_flags', bits(it.shop_flags), DQ7I18N.t('item.fShopFlags'));
  h += `</table>`;

  h += `<div class="sec">${DQ7I18N.t('item.rawHeading')}</div><div class="mono">${it.raw_hex.replace(/(..)/g, '$1 ').trim()}</div>`;
  h += `<div class="sec hint" style="font-weight:normal">${esc(window._itemNote || '')}</div>`;

  detailEl.innerHTML = h;
}

loadList();
