// 特技/呪文データビューア - LEVELDATA/dq7_action_param.dat (804 x 92byte) と
// dq7_action_type.dat (100 x 32byte) を解読して表示する。
// バックエンドは /api/action_param, /api/action_type。
// 構造の根拠は docs/action_param_action_type_investigation.md。

DQ7I18N.extend({
  ja: {
    'action.tabList': '一覧',
    'action.tabDetail': '詳細',
    'action.tabType': 'action_type',
    'action.searchPlaceholder': '番号 / 名前 で絞り込み...',
    'action.selectHint': '特技/呪文を選択すると全フィールドが表示されます',
    'action.noMatch': '該当なし',
    'action.noName': '(名前なし。モンスター専用技と推測)',
    'action.records': 'レコード',
    'action.clickRowHint': '行クリックで詳細。',
    'action.loadFailed': '読み込み失敗',
    'common.offset': 'offset',
    'common.field': 'フィールド',
    'common.value': '値',
    'action.fTypeByte': 'type_byte',
    'action.fTypeByteHint': '上位5bit=category(推定), 下位3bit=sub(推定)。action_type.datの行番号ではない模様',
    'action.fMpCost': 'MP消費',
    'action.fMpCostHint': '255 = MP全消費(例: メガザル)',
    'action.fElement': '属性/系統',
    'action.fElementHint': '同系統スペル内でMP消費量が段階的に増える並びから逆算した推定ラベル',
    'action.fRoll': '基本威力/回復量ロール',
    'action.fRollHint': '[min,max]の一様乱数。ActionEffectValue::setEffectValueのデコンパイルで' +
      '実際にこのフィールドが読まれることを確認済み(2026-10-06)',
    'action.fUnknown3c': '用途不明 (+0x3c/+0x3e)',
    'action.fUnknown3cHint': '左のロールより常に小さいか等しい値だが、ダメージ計算関連の' +
      '関数を約25個調べても読み込み箇所が見つからず未確認。旧版では「複数/全体対象威力」と' +
      '説明していたが根拠が無かったため撤回した',
    'action.rawHeading': 'raw (92 byte)',
    'action.basedOn': '根拠',
    'action.typeIntro': 'dq7_action_type.dat (100レコード x 32byte)。戦闘エフェクト' +
      '(モデルスケール・アタッチ位置・パーティクル名)のテーブルと推測。' +
      'dq7_action_param.dat側のどのフィールドで本テーブルの行を参照しているかは未確認。',
    'action.thIndex': '#', 'action.thKey': 'key', 'action.thScale': 'scale',
    'action.thA': 'a', 'action.thB': 'b', 'action.thC': 'c', 'action.thD': 'd',
    'action.thNode': 'node', 'action.thParticle': 'particle', 'action.thFlags': 'flags',
  },
  en: {
    'action.tabList': 'List',
    'action.tabDetail': 'Detail',
    'action.tabType': 'action_type',
    'action.searchPlaceholder': 'Filter by number / name...',
    'action.selectHint': 'Select a skill/spell to see all fields',
    'action.noMatch': 'No matches',
    'action.noName': '(no name; likely a monster-only move)',
    'action.records': 'records',
    'action.clickRowHint': 'Click a row for details.',
    'action.loadFailed': 'Load failed',
    'common.offset': 'offset',
    'common.field': 'field',
    'common.value': 'value',
    'action.fTypeByte': 'type_byte',
    'action.fTypeByteHint': 'Upper 5 bits = category (estimated), lower 3 bits = sub (estimated). Does not appear to index dq7_action_type.dat rows',
    'action.fMpCost': 'MP cost',
    'action.fMpCostHint': '255 = consumes all remaining MP (e.g. Omniheal/Megazal)',
    'action.fElement': 'Element/family',
    'action.fElementHint': 'Estimated label, derived from the stepped MP cost within each spell family',
    'action.fRoll': 'Base power/heal roll',
    'action.fRollHint': 'Uniform random [min,max]. Confirmed by decompiling ' +
      'ActionEffectValue::setEffectValue, which reads exactly this field (2026-10-06)',
    'action.fUnknown3c': 'Unknown purpose (+0x3c/+0x3e)',
    'action.fUnknown3cHint': 'Always <= the roll on the left, but no read of this field ' +
      'turned up after decompiling ~25 damage-calculation-related functions. An earlier ' +
      'version of this viewer called it "group/all-target power" with no real evidence, ' +
      'and that claim has been retracted',
    'action.rawHeading': 'raw (92 bytes)',
    'action.basedOn': 'Based on',
    'action.typeIntro': 'dq7_action_type.dat (100 records x 32 bytes). Believed to be a battle ' +
      'effect table (model scale, attach point, particle name). How ' +
      'dq7_action_param.dat records reference a row here is unconfirmed.',
    'action.thIndex': '#', 'action.thKey': 'key', 'action.thScale': 'scale',
    'action.thA': 'a', 'action.thB': 'b', 'action.thC': 'c', 'action.thD': 'd',
    'action.thNode': 'node', 'action.thParticle': 'particle', 'action.thFlags': 'flags',
  },
});

const listInner = document.getElementById('actionListInner');
const searchBox = document.getElementById('actionSearch');
const subEl = document.getElementById('actionSub');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');
const typeTableEl = document.getElementById('typeTable');
const typeSubEl = document.getElementById('typeSub');

let allActions = [];
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

function elabel(a) {
  return DQ7I18N.getLang() === 'en' ? (a.element_label_en || a.element_label) : a.element_label;
}

async function loadList() {
  listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.loading')}</div>`;
  let data;
  try {
    data = await (await fetch('/api/action_param')).json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('action.loadFailed')}: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.error')}: ${esc(data.error)}</div>`;
    return;
  }
  allActions = data.records || [];
  window._actionNote = data.note || '';
  subEl.textContent =
    `${data.source} — ${data.record_count} ${DQ7I18N.t('action.records')} x ${data.record_size}byte. ${DQ7I18N.t('action.clickRowHint')}`;
  statusEl.textContent = `${allActions.length} actions`;
  renderList();
}
window.addEventListener('dq7lang:change', () => { renderList(); if (selectedIdx !== null) selectAction(selectedIdx); renderTypeTable(); });

function renderList() {
  const q = searchBox.value.trim().toLowerCase();
  const rows = allActions.filter(a => {
    if (!q) return true;
    if (String(a.index).includes(q)) return true;
    if (a.name && a.name.toLowerCase().includes(q)) return true;
    return false;
  });
  listInner.innerHTML = rows.map(a => `
    <div class="ac-row${a.index === selectedIdx ? ' selected' : ''}" data-idx="${a.index}">
      <span class="aid">#${a.index}</span>
      <span class="amp">${a.mp_cost ? 'MP' + a.mp_cost : ''}</span>
      <span class="anm${a.name ? '' : ' noname'}">${esc(a.name || DQ7I18N.t('action.noName'))}</span>
    </div>`).join('') || `<div class="empty">${DQ7I18N.t('action.noMatch')}</div>`;
  listInner.querySelectorAll('.ac-row').forEach(el => {
    el.addEventListener('click', () => selectAction(parseInt(el.dataset.idx, 10)));
  });
}
searchBox.addEventListener('input', renderList);

function selectAction(idx) {
  selectedIdx = idx;
  renderList();
  if (window.matchMedia('(max-width: 760px)').matches) showPane('detail');
  const a = allActions.find(x => x.index === idx);
  if (!a) return;

  const row = (off, label, val, hint) =>
    `<tr><th>${off}</th><th>${esc(label)}</th><td class="v">${esc(val)}</td>` +
    `<td class="hint">${hint ? esc(hint) : ''}</td></tr>`;

  let h = '';
  h += `<div class="sec">#${a.index}  ${esc(a.name || DQ7I18N.t('action.noName'))}</div>`;
  h += `<table class="kv2"><tr><th>${DQ7I18N.t('common.offset')}</th><th>${DQ7I18N.t('common.field')}</th><th>${DQ7I18N.t('common.value')}</th><th></th></tr>`;
  h += row('+0x00', 'type_byte', `${a.type_byte} (cat=${a.type_category}, sub=${a.type_sub})`, DQ7I18N.t('action.fTypeByteHint'));
  h += row('+0x38/0x3a', DQ7I18N.t('action.fRoll'), `${a.roll_min} - ${a.roll_max}`, DQ7I18N.t('action.fRollHint'));
  h += row('+0x3c/0x3e', DQ7I18N.t('action.fUnknown3c'), `${a.unknown3c_min} - ${a.unknown3c_max}`, DQ7I18N.t('action.fUnknown3cHint'));
  h += row('+0x4a', DQ7I18N.t('action.fElement'), `${a.element_id} = ${elabel(a)}`, DQ7I18N.t('action.fElementHint'));
  h += row('+0x4b', DQ7I18N.t('action.fMpCost'), a.mp_cost, DQ7I18N.t('action.fMpCostHint'));
  h += `</table>`;

  h += `<div class="sec">${DQ7I18N.t('action.rawHeading')}</div><div class="mono">${a.raw_hex.replace(/(..)/g, '$1 ').trim()}</div>`;
  h += `<div class="sec hint" style="font-weight:normal">${esc(window._actionNote || '')}</div>`;

  detailEl.innerHTML = h;
}

async function renderTypeTable() {
  let data;
  try {
    data = await (await fetch('/api/action_type')).json();
  } catch (e) {
    typeTableEl.innerHTML = `<div class="empty">${DQ7I18N.t('action.loadFailed')}: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    typeTableEl.innerHTML = `<div class="empty">${DQ7I18N.t('common.error')}: ${esc(data.error)}</div>`;
    return;
  }
  typeSubEl.textContent = DQ7I18N.t('action.typeIntro');
  const recs = data.records || [];
  let h = '<table><tr>' +
    ['thIndex', 'thKey', 'thScale', 'thA', 'thB', 'thC', 'thD', 'thNode', 'thParticle', 'thFlags']
      .map(k => `<th>${DQ7I18N.t('action.' + k)}</th>`).join('') + '</tr>';
  h += recs.map(r => `<tr><td>${r.index}</td><td>0x${r.key.toString(16).padStart(4, '0')}</td>` +
    `<td>${r.scale}</td><td>${r.field_a}</td><td>${r.field_b}</td><td>${r.field_c}</td>` +
    `<td>${r.field_d}</td><td>${r.node_id}</td><td>${esc(r.particle_name)}</td>` +
    `<td>0x${r.flags.toString(16).padStart(4, '0')}</td></tr>`).join('');
  h += '</table>';
  typeTableEl.innerHTML = h;
}

loadList();
renderTypeTable();
