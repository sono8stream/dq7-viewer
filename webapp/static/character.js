// キャラクター関連データビューア。3種類のLEVELDATAテーブルを切り替えて表示する:
//   player_stats         : dq7_player_level{1..8}.dat (成長表, レベル別ステータス)
//   character_init_data  : dq7_character_init_data.dat (初期化データ, 46レコード)
//   chara_list            : dq7_chara_list.dat (全キャラ/NPCモデル寸法, 927レコード)
// バックエンドは /api/player_stats, /api/character_init_data, /api/chara_list。
// フィールド構造の根拠は docs/character_status_investigation.md および
// docs/playable_character_expansion_investigation.md。

DQ7I18N.extend({
  ja: {
    'character.tabGrowth': '成長表(LvN)',
    'character.tabInit': '初期化データ',
    'character.tabCharaList': 'モデル寸法(全NPC)',
    'character.tabSelect': 'キャラ選択',
    'character.selectHint': 'キャラを選ぶとレベル1〜99の成長表が出ます',
    'character.listHintEmpty': '左から項目を選んでください',
    'character.loadFailed': '読み込み失敗',
    'character.charCountSuffix': 'キャラ。名前は',
    'character.recordsSuffix': '件',
    'character.noNameUnknown': '(名前不明)',
    'character.noModel': '(モデル名なし)',
    'character.colLevel': 'Lv', 'character.colExp': '累計EXP', 'character.colStr': 'ちから',
    'character.colAgi': 'すばやさ', 'character.colLuck': 'うんのよさ', 'character.colWis': 'かしこさ',
    'character.colHp': 'HP', 'character.colMp': 'MP',
    'character.recordCountSuffix': 'レコード x',
    'character.statOrderLabel': 'スタッツ並び',
    'character.cat0x08': '0x08 主人公(id1)', 'character.cat0x10': '0x10 本編プレイアブル(id2〜5)',
    'character.cat0x310': '0x310 本編プレイアブル(id6)', 'character.cat0x1c': '0x1c 配置データありNPC/ゲスト',
    'character.cat0x20': '0x20 名前のみプレースホルダ', 'character.cat0x28': '0x28 特殊8体グループ',
    'character.catOther': 'その他(現在値',
    'character.fCategoryCode': 'カテゴリコード',
    'character.fPos': '配置データ(位置)',
    'character.fScale': '配置データ(向き/スケール)',
    'character.fInitLevel': '初期レベル (+0x74, 確定)',
    'character.fInitExp': '初期EXP (+0x04, 確定)',
    'character.fGender': '性別 (+0x4c, 確定)',
    'character.f0x6c': '+0x6c (生成順連番, 情報用途のみ)',
    'character.fBaseStats': 'ベースステータス (+0x32/34/36/38/3c, 確定)',
    'character.statStr': 'ちから', 'character.statAgi': 'すばやさ', 'character.statLuck': 'うんのよさ',
    'character.statWis': 'かしこさ', 'character.statHp': 'HP',
    'character.detailDocPrefix': '詳細は',
    'character.detailDocSuffix': '参照。',
    'character.editSectionTitle': '編集（プレイアブル初期化への関与を検証中 — 書き換え後はCIA再ビルドが必要）',
    'character.editCategoryLabel': 'カテゴリコード (+0x90上位u16)',
    'character.saveCategory': 'カテゴリコードを保存',
    'character.editInitLevelLabel': '初期レベル (+0x74)',
    'character.saveInitLevel': '初期レベルを保存',
    'character.editInitExpLabel': '初期EXP (+0x04)',
    'character.saveInitExp': '初期EXPを保存',
    'character.saving': '保存中...',
    'character.savedPrefix': '保存しました',
    'character.savedBackupSuffix': '（バックアップ:',
    'character.savedRebuildSuffix': '）。CIA再ビルドで実機に反映されます。',
    'character.saveFailed': '保存失敗',
    'character.fAssetTag': 'asset_tag (+0x00下位u16)',
    'character.f0x18': '+0x18 (float, 推定用途不明)',
    'character.f0x1c': '+0x1c (float, 推定用途不明)',
    'character.fFloats': 'float列 +0x08〜+0x44 (推定: バウンディングボックス/スケール)',
  },
  en: {
    'character.tabGrowth': 'Growth (LvN)',
    'character.tabInit': 'Init Data',
    'character.tabCharaList': 'Model Dimensions (all NPCs)',
    'character.tabSelect': 'Select Character',
    'character.selectHint': 'Select a character to see the level 1-99 growth table',
    'character.listHintEmpty': 'Select an entry on the left',
    'character.loadFailed': 'Load failed',
    'character.charCountSuffix': 'characters. Names are',
    'character.recordsSuffix': 'entries',
    'character.noNameUnknown': '(unknown name)',
    'character.noModel': '(no model name)',
    'character.colLevel': 'Lv', 'character.colExp': 'Total EXP', 'character.colStr': 'STR',
    'character.colAgi': 'AGI', 'character.colLuck': 'LUCK', 'character.colWis': 'WIS',
    'character.colHp': 'HP', 'character.colMp': 'MP',
    'character.recordCountSuffix': 'records x',
    'character.statOrderLabel': 'Stat order',
    'character.cat0x08': '0x08 Hero (id1)', 'character.cat0x10': '0x10 main playable (id2-5)',
    'character.cat0x310': '0x310 main playable (id6)', 'character.cat0x1c': '0x1c NPC/guest with placement data',
    'character.cat0x20': '0x20 name-only placeholder', 'character.cat0x28': '0x28 special group of 8',
    'character.catOther': 'Other (current value',
    'character.fCategoryCode': 'Category code',
    'character.fPos': 'Placement data (position)',
    'character.fScale': 'Placement data (facing/scale)',
    'character.fInitLevel': 'Initial level (+0x74, confirmed)',
    'character.fInitExp': 'Initial EXP (+0x04, confirmed)',
    'character.fGender': 'Gender (+0x4c, confirmed)',
    'character.f0x6c': '+0x6c (creation-order sequence, informational only)',
    'character.fBaseStats': 'Base stats (+0x32/34/36/38/3c, confirmed)',
    'character.statStr': 'STR', 'character.statAgi': 'AGI', 'character.statLuck': 'LUCK',
    'character.statWis': 'WIS', 'character.statHp': 'HP',
    'character.detailDocPrefix': 'See',
    'character.detailDocSuffix': 'for details.',
    'character.editSectionTitle': 'Edit (verifying involvement in playable init — requires CIA rebuild after changes)',
    'character.editCategoryLabel': 'Category code (+0x90 upper u16)',
    'character.saveCategory': 'Save category code',
    'character.editInitLevelLabel': 'Initial level (+0x74)',
    'character.saveInitLevel': 'Save initial level',
    'character.editInitExpLabel': 'Initial EXP (+0x04)',
    'character.saveInitExp': 'Save initial EXP',
    'character.saving': 'Saving...',
    'character.savedPrefix': 'Saved',
    'character.savedBackupSuffix': '(backup:',
    'character.savedRebuildSuffix': '). Rebuild the CIA to apply on real hardware.',
    'character.saveFailed': 'Save failed',
    'character.fAssetTag': 'asset_tag (+0x00 lower u16)',
    'character.f0x18': '+0x18 (float, presumed purpose unknown)',
    'character.f0x1c': '+0x1c (float, presumed purpose unknown)',
    'character.fFloats': 'float array +0x08~+0x44 (presumed: bounding box/scale)',
  },
});

function catLabel(code) {
  const key = { 0x08: 'character.cat0x08', 0x10: 'character.cat0x10', 0x310: 'character.cat0x310',
    0x1c: 'character.cat0x1c', 0x20: 'character.cat0x20', 0x28: 'character.cat0x28' }[code];
  return key ? DQ7I18N.t(key) : null;
}
function genderLabel(c) {
  return DQ7I18N.getLang() === 'en' ? (c.gender_label_en || c.gender_label) : c.gender_label;
}

const listInner = document.getElementById('charListInner');
const subEl = document.getElementById('charSub');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');
const datasetTabs = document.getElementById('datasetTabs');

let currentDs = 'player_stats';
let dsData = {};        // dataset名 -> APIレスポンス(キャッシュ)
let selectedKey = null; // 現在選択中の行のキー(slot/index)

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
datasetTabs.querySelectorAll('button').forEach(b => {
  b.addEventListener('click', () => switchDataset(b.dataset.ds));
});

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const DS_API = {
  player_stats: '/api/player_stats',
  character_init_data: '/api/character_init_data',
  chara_list: '/api/chara_list',
};

async function switchDataset(ds) {
  currentDs = ds;
  selectedKey = null;
  datasetTabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.ds === ds));
  listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.loading')}</div>`;
  detailEl.innerHTML = `<div class="empty">${DQ7I18N.t('character.listHintEmpty')}</div>`;
  if (!dsData[ds]) {
    try {
      dsData[ds] = await (await fetch(DS_API[ds])).json();
    } catch (e) {
      listInner.innerHTML = `<div class="empty">${DQ7I18N.t('character.loadFailed')}: ${esc(e.message || e)}</div>`;
      return;
    }
  }
  const data = dsData[ds];
  if (data.error) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.error')}: ${esc(data.error)}</div>`;
    return;
  }
  renderList();
  const items = itemsOf(data);
  if (items.length) selectItem(keyOf(items[0]));
}
window.addEventListener('dq7lang:change', () => {
  if (!dsData[currentDs]) return;
  renderList();
  if (selectedKey !== null) selectItem(selectedKey);
});

function itemsOf(data) {
  return data.characters || data.records || [];
}
function keyOf(item) {
  return item.slot !== undefined ? item.slot : item.index;
}

function renderList() {
  const data = dsData[currentDs];
  if (!data) return;
  const items = itemsOf(data);
  if (currentDs === 'player_stats') {
    subEl.textContent = `${data.source} — ${items.length} ${DQ7I18N.t('character.charCountSuffix')}${data.note}`;
    listInner.innerHTML = items.map(c => `
      <div class="ch-row${keyOf(c) === selectedKey ? ' selected' : ''}" data-key="${keyOf(c)}">
        <span class="cslot">L${c.slot}</span>
        <span>${esc(c.name_guess)}</span>
        <span class="cslot">(${esc(c.file)})</span>
      </div>`).join('');
  } else if (currentDs === 'character_init_data') {
    subEl.textContent = `${data.source} — ${items.length}${DQ7I18N.t('character.recordsSuffix')}. ${data.note}`;
    listInner.innerHTML = items.map(c => `
      <div class="ch-row${keyOf(c) === selectedKey ? ' selected' : ''}" data-key="${keyOf(c)}">
        <span class="cslot">#${c.index}</span>
        <span>${esc(c.name || DQ7I18N.t('character.noNameUnknown'))}</span>
        <span class="cslot">${esc(c.model)}</span>
      </div>`).join('');
  } else if (currentDs === 'chara_list') {
    subEl.textContent = `${data.source} — ${items.length}${DQ7I18N.t('character.recordsSuffix')}. ${data.note}`;
    listInner.innerHTML = items.map(c => `
      <div class="ch-row${keyOf(c) === selectedKey ? ' selected' : ''}" data-key="${keyOf(c)}">
        <span class="cslot">#${c.index}</span>
        <span>${esc(c.model || DQ7I18N.t('character.noModel'))}</span>
      </div>`).join('');
  }
  listInner.querySelectorAll('.ch-row').forEach(el => {
    el.addEventListener('click', () => selectItem(parseInt(el.dataset.key, 10)));
  });
}

function growthCols() {
  return [
    ['level', DQ7I18N.t('character.colLevel')], ['exp', DQ7I18N.t('character.colExp')],
    ['str', DQ7I18N.t('character.colStr')], ['agi', DQ7I18N.t('character.colAgi')],
    ['luck', DQ7I18N.t('character.colLuck')], ['wis', DQ7I18N.t('character.colWis')],
    ['hp', DQ7I18N.t('character.colHp')], ['mp', DQ7I18N.t('character.colMp')],
  ];
}

function selectItem(key) {
  selectedKey = key;
  renderList();
  if (window.matchMedia('(max-width: 760px)').matches) showPane('detail');
  const data = dsData[currentDs];
  const items = itemsOf(data);
  const c = items.find(x => keyOf(x) === key);
  if (!c) return;

  if (currentDs === 'player_stats') renderGrowthDetail(c, data);
  else if (currentDs === 'character_init_data') renderInitDataDetail(c, data);
  else if (currentDs === 'chara_list') renderCharaListDetail(c, data);
  detailEl.scrollTop = 0;
}

function renderGrowthDetail(c, data) {
  const cols = growthCols();
  let h = `<div class="sec">${esc(c.name_guess)} — ${esc(c.file)} (${c.record_count} ${DQ7I18N.t('character.recordCountSuffix')} ${c.record_size}byte)</div>`;
  h += `<table class="stat"><tr>${cols.map(([, l]) => `<th>${esc(l)}</th>`).join('')}</tr>`;
  let prev = null;
  for (const lv of c.levels) {
    h += '<tr>';
    for (const [k] of cols) {
      let v = lv[k];
      let up = '';
      if (prev && ['str', 'agi', 'luck', 'wis', 'hp', 'mp'].includes(k)) {
        const d = v - prev[k];
        if (d > 0) up = ` <span class="up">+${d}</span>`;
      }
      const cls = k === 'level' ? ' class="lv"' : '';
      h += `<td${cls}>${v.toLocaleString()}${up}</td>`;
    }
    h += '</tr>';
    prev = lv;
  }
  h += '</table>';
  h += `<div class="hint">${DQ7I18N.t('character.statOrderLabel')}: ${esc((data.stat_order || []).join(' / '))}<br>${esc(data.note || '')}</div>`;
  detailEl.innerHTML = h;
}

function fieldRow(label, value) {
  return `<tr><td class="txt">${esc(label)}</td><td>${esc(value)}</td></tr>`;
}

function charInitCategoryOptions() {
  return [
    [0x08, DQ7I18N.t('character.cat0x08')], [0x10, DQ7I18N.t('character.cat0x10')],
    [0x310, DQ7I18N.t('character.cat0x310')], [0x1c, DQ7I18N.t('character.cat0x1c')],
    [0x20, DQ7I18N.t('character.cat0x20')], [0x28, DQ7I18N.t('character.cat0x28')],
  ];
}

function renderInitDataDetail(c, data) {
  const CHAR_INIT_CATEGORY_OPTIONS = charInitCategoryOptions();
  let h = `<div class="sec">#${c.index} ${esc(c.name || DQ7I18N.t('character.noNameUnknown'))} — ${esc(c.model || DQ7I18N.t('character.noModel'))}</div>`;
  h += `<table class="rawtable">`;
  h += fieldRow(DQ7I18N.t('character.fCategoryCode'), `0x${c.category_code.toString(16)} = ${catLabel(c.category_code) || c.category_label}`);
  h += fieldRow(DQ7I18N.t('character.fPos'), c.pos ? c.pos.map(v => v.toFixed(3)).join(', ') : DQ7I18N.t('common.none'));
  h += fieldRow(DQ7I18N.t('character.fScale'), c.scale ? c.scale.map(v => v.toFixed(3)).join(', ') : DQ7I18N.t('common.none'));
  h += fieldRow(DQ7I18N.t('character.fInitLevel'), c.init_level);
  h += fieldRow(DQ7I18N.t('character.fInitExp'), c.init_exp);
  h += fieldRow(DQ7I18N.t('character.fGender'), `${c.gender_code} = ${genderLabel(c)}`);
  h += fieldRow(DQ7I18N.t('character.f0x6c'), c.field_0x6c);
  h += fieldRow(DQ7I18N.t('character.fBaseStats'),
    `${DQ7I18N.t('character.statStr')}${c.base_stats.str} ${DQ7I18N.t('character.statAgi')}${c.base_stats.agi} ` +
    `${DQ7I18N.t('character.statLuck')}${c.base_stats.luck} ${DQ7I18N.t('character.statWis')}${c.base_stats.wis} ` +
    `${DQ7I18N.t('character.statHp')}${c.base_stats.hp}`);
  h += `</table>`;
  h += `<div class="hint">${esc(data.note || '')}<br>${DQ7I18N.t('character.detailDocPrefix')} ${esc(data.field_doc)} ${DQ7I18N.t('character.detailDocSuffix')}` +
       `<br><span style="font-family:var(--mono);font-size:10.5px;word-break:break-all;">raw: ${esc(c.raw_hex)}</span></div>`;

  h += `<div class="sec" style="margin-top:16px;">${DQ7I18N.t('character.editSectionTitle')}</div>`;
  h += `<div class="edit-form" id="charInitEditForm">
    <div>
      <label>${DQ7I18N.t('character.editCategoryLabel')}</label>
      <select id="editCategoryCode">
        ${CHAR_INIT_CATEGORY_OPTIONS.map(([v, l]) =>
          `<option value="${v}"${v === c.category_code ? ' selected' : ''}>${esc(l)}</option>`).join('')}
        <option value="${c.category_code}"${CHAR_INIT_CATEGORY_OPTIONS.some(([v]) => v === c.category_code) ? '' : ' selected'}>${DQ7I18N.t('character.catOther')} 0x${c.category_code.toString(16)})</option>
      </select>
    </div>
    <div class="form-actions"><button id="saveCategoryCode">${DQ7I18N.t('character.saveCategory')}</button></div>
    <div>
      <label>${DQ7I18N.t('character.editInitLevelLabel')}</label>
      <input type="number" id="editInitLevel" value="${c.init_level}">
    </div>
    <div class="form-actions"><button id="saveInitLevel">${DQ7I18N.t('character.saveInitLevel')}</button></div>
    <div>
      <label>${DQ7I18N.t('character.editInitExpLabel')}</label>
      <input type="number" id="editInitExp" value="${c.init_exp}">
    </div>
    <div class="form-actions"><button id="saveInitExp">${DQ7I18N.t('character.saveInitExp')}</button></div>
    <div id="charInitEditStatus" class="hint"></div>
  </div>`;
  detailEl.innerHTML = h;

  const statusBox = document.getElementById('charInitEditStatus');
  const wire = (btnId, field, inputId, parse) => {
    document.getElementById(btnId).addEventListener('click', async () => {
      const raw = document.getElementById(inputId).value;
      const value = parse(raw);
      statusBox.textContent = DQ7I18N.t('character.saving');
      try {
        const res = await fetch('/api/character_init_data/edit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: c.index, field, value, comment: 'webビューアから編集' }),
        });
        const result = await res.json();
        if (!res.ok || result.error) throw new Error(result.error || `HTTP ${res.status}`);
        statusBox.textContent = `${DQ7I18N.t('character.savedPrefix')}: ${field} ${result.before} → ${result.after}` +
          `${DQ7I18N.t('character.savedBackupSuffix')} ${result.backup_path}${DQ7I18N.t('character.savedRebuildSuffix')}`;
        delete dsData.character_init_data; // 次回表示時に再取得
        await switchDataset('character_init_data');
        selectItem(c.index);
      } catch (e) {
        statusBox.textContent = `${DQ7I18N.t('character.saveFailed')}: ${e.message || e}`;
      }
    });
  };
  wire('saveCategoryCode', 'category_code', 'editCategoryCode', v => parseInt(v, 10));
  wire('saveInitLevel', 'init_level', 'editInitLevel', v => parseInt(v, 10));
  wire('saveInitExp', 'init_exp', 'editInitExp', v => parseInt(v, 10));
}

function renderCharaListDetail(c, data) {
  let h = `<div class="sec">#${c.index} ${esc(c.model || DQ7I18N.t('character.noModel'))}</div>`;
  h += `<table class="rawtable">`;
  h += fieldRow(DQ7I18N.t('character.fAssetTag'), c.asset_tag);
  h += fieldRow(DQ7I18N.t('character.f0x18'), c.field_0x18);
  h += fieldRow(DQ7I18N.t('character.f0x1c'), c.field_0x1c);
  h += fieldRow(DQ7I18N.t('character.fFloats'), c.floats_0x08_0x44.join(', '));
  h += `</table>`;
  h += `<div class="hint">${esc(data.note || '')}<br>${DQ7I18N.t('character.detailDocPrefix')} ${esc(data.field_doc)} ${DQ7I18N.t('character.detailDocSuffix')}</div>`;
  detailEl.innerHTML = h;
}

switchDataset('player_stats');
