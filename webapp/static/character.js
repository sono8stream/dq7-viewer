// キャラクター関連データビューア。3種類のLEVELDATAテーブルを切り替えて表示する:
//   player_stats         : dq7_player_level{1..8}.dat (成長表, レベル別ステータス)
//   character_init_data  : dq7_character_init_data.dat (初期化データ, 46レコード)
//   chara_list            : dq7_chara_list.dat (全キャラ/NPCモデル寸法, 927レコード)
// バックエンドは /api/player_stats, /api/character_init_data, /api/chara_list。
// フィールド構造の根拠は docs/character_status_investigation.md および
// docs/playable_character_expansion_investigation.md。

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
  listInner.innerHTML = '<div class="empty">読み込み中...</div>';
  detailEl.innerHTML = '<div class="empty">左から項目を選んでください</div>';
  if (!dsData[ds]) {
    try {
      dsData[ds] = await (await fetch(DS_API[ds])).json();
    } catch (e) {
      listInner.innerHTML = `<div class="empty">読み込み失敗: ${esc(e.message || e)}</div>`;
      return;
    }
  }
  const data = dsData[ds];
  if (data.error) {
    listInner.innerHTML = `<div class="empty">エラー: ${esc(data.error)}</div>`;
    return;
  }
  renderList();
  const items = itemsOf(data);
  if (items.length) selectItem(keyOf(items[0]));
}

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
    subEl.textContent = `${data.source} — ${items.length} キャラ。名前は${data.note}`;
    listInner.innerHTML = items.map(c => `
      <div class="ch-row${keyOf(c) === selectedKey ? ' selected' : ''}" data-key="${keyOf(c)}">
        <span class="cslot">L${c.slot}</span>
        <span>${esc(c.name_guess)}</span>
        <span class="cslot">(${esc(c.file)})</span>
      </div>`).join('');
  } else if (currentDs === 'character_init_data') {
    subEl.textContent = `${data.source} — ${items.length}件。${data.note}`;
    listInner.innerHTML = items.map(c => `
      <div class="ch-row${keyOf(c) === selectedKey ? ' selected' : ''}" data-key="${keyOf(c)}">
        <span class="cslot">#${c.index}</span>
        <span>${esc(c.name || '(名前不明)')}</span>
        <span class="cslot">${esc(c.model)}</span>
      </div>`).join('');
  } else if (currentDs === 'chara_list') {
    subEl.textContent = `${data.source} — ${items.length}件。${data.note}`;
    listInner.innerHTML = items.map(c => `
      <div class="ch-row${keyOf(c) === selectedKey ? ' selected' : ''}" data-key="${keyOf(c)}">
        <span class="cslot">#${c.index}</span>
        <span>${esc(c.model || '(モデル名なし)')}</span>
      </div>`).join('');
  }
  listInner.querySelectorAll('.ch-row').forEach(el => {
    el.addEventListener('click', () => selectItem(parseInt(el.dataset.key, 10)));
  });
}

const GROWTH_COLS = [
  ['level', 'Lv'], ['exp', '累計EXP'], ['str', 'ちから'], ['agi', 'すばやさ'],
  ['luck', 'うんのよさ'], ['wis', 'かしこさ'], ['hp', 'HP'], ['mp', 'MP'],
];

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
  let h = `<div class="sec">${esc(c.name_guess)} — ${esc(c.file)} (${c.record_count} レコード x ${c.record_size}byte)</div>`;
  h += `<table class="stat"><tr>${GROWTH_COLS.map(([, l]) => `<th>${esc(l)}</th>`).join('')}</tr>`;
  let prev = null;
  for (const lv of c.levels) {
    h += '<tr>';
    for (const [k] of GROWTH_COLS) {
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
  h += `<div class="hint">スタッツ並び: ${esc((data.stat_order || []).join(' / '))}<br>${esc(data.note || '')}</div>`;
  detailEl.innerHTML = h;
}

function fieldRow(label, value) {
  return `<tr><td class="txt">${esc(label)}</td><td>${esc(value)}</td></tr>`;
}

const CHAR_INIT_CATEGORY_OPTIONS = [
  [0x08, '0x08 主人公(id1)'], [0x10, '0x10 本編プレイアブル(id2〜5)'],
  [0x310, '0x310 本編プレイアブル(id6)'], [0x1c, '0x1c 配置データありNPC/ゲスト'],
  [0x20, '0x20 名前のみプレースホルダ'], [0x28, '0x28 特殊8体グループ'],
];

function renderInitDataDetail(c, data) {
  let h = `<div class="sec">#${c.index} ${esc(c.name || '(名前不明)')} — ${esc(c.model || '(モデル名なし)')}</div>`;
  h += `<table class="rawtable">`;
  h += fieldRow('カテゴリコード', `0x${c.category_code.toString(16)} = ${c.category_label}`);
  h += fieldRow('配置データ(位置)', c.pos ? c.pos.map(v => v.toFixed(3)).join(', ') : '(なし)');
  h += fieldRow('配置データ(向き/スケール)', c.scale ? c.scale.map(v => v.toFixed(3)).join(', ') : '(なし)');
  h += fieldRow('初期レベル (+0x74, 確定)', c.init_level);
  h += fieldRow('初期EXP (+0x04, 確定)', c.init_exp);
  h += fieldRow('性別 (+0x4c, 確定)', `${c.gender_code} = ${c.gender_label}`);
  h += fieldRow('+0x6c (生成順連番, 情報用途のみ)', c.field_0x6c);
  h += fieldRow('ベースステータス (+0x32/34/36/38/3c, 確定)',
    `ちから${c.base_stats.str} すばやさ${c.base_stats.agi} うんのよさ${c.base_stats.luck} ` +
    `かしこさ${c.base_stats.wis} HP${c.base_stats.hp}`);
  h += `</table>`;
  h += `<div class="hint">${esc(data.note || '')}<br>詳細は ${esc(data.field_doc)} 参照。` +
       `<br><span style="font-family:var(--mono);font-size:10.5px;word-break:break-all;">raw: ${esc(c.raw_hex)}</span></div>`;

  h += `<div class="sec" style="margin-top:16px;">編集（プレイアブル初期化への関与を検証中 — 書き換え後はCIA再ビルドが必要）</div>`;
  h += `<div class="edit-form" id="charInitEditForm">
    <div>
      <label>カテゴリコード (+0x90上位u16)</label>
      <select id="editCategoryCode">
        ${CHAR_INIT_CATEGORY_OPTIONS.map(([v, l]) =>
          `<option value="${v}"${v === c.category_code ? ' selected' : ''}>${esc(l)}</option>`).join('')}
        <option value="${c.category_code}"${CHAR_INIT_CATEGORY_OPTIONS.some(([v]) => v === c.category_code) ? '' : ' selected'}>その他(現在値 0x${c.category_code.toString(16)})</option>
      </select>
    </div>
    <div class="form-actions"><button id="saveCategoryCode">カテゴリコードを保存</button></div>
    <div>
      <label>初期レベル (+0x74)</label>
      <input type="number" id="editInitLevel" value="${c.init_level}">
    </div>
    <div class="form-actions"><button id="saveInitLevel">初期レベルを保存</button></div>
    <div>
      <label>初期EXP (+0x04)</label>
      <input type="number" id="editInitExp" value="${c.init_exp}">
    </div>
    <div class="form-actions"><button id="saveInitExp">初期EXPを保存</button></div>
    <div id="charInitEditStatus" class="hint"></div>
  </div>`;
  detailEl.innerHTML = h;

  const statusBox = document.getElementById('charInitEditStatus');
  const wire = (btnId, field, inputId, parse) => {
    document.getElementById(btnId).addEventListener('click', async () => {
      const raw = document.getElementById(inputId).value;
      const value = parse(raw);
      statusBox.textContent = '保存中...';
      try {
        const res = await fetch('/api/character_init_data/edit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: c.index, field, value, comment: 'webビューアから編集' }),
        });
        const result = await res.json();
        if (!res.ok || result.error) throw new Error(result.error || `HTTP ${res.status}`);
        statusBox.textContent = `保存しました: ${field} ${result.before} → ${result.after}` +
          `（バックアップ: ${result.backup_path}）。CIA再ビルドで実機に反映されます。`;
        delete dsData.character_init_data; // 次回表示時に再取得
        await switchDataset('character_init_data');
        selectItem(c.index);
      } catch (e) {
        statusBox.textContent = `保存失敗: ${e.message || e}`;
      }
    });
  };
  wire('saveCategoryCode', 'category_code', 'editCategoryCode', v => parseInt(v, 10));
  wire('saveInitLevel', 'init_level', 'editInitLevel', v => parseInt(v, 10));
  wire('saveInitExp', 'init_exp', 'editInitExp', v => parseInt(v, 10));
}

function renderCharaListDetail(c, data) {
  let h = `<div class="sec">#${c.index} ${esc(c.model || '(モデル名なし)')}</div>`;
  h += `<table class="rawtable">`;
  h += fieldRow('asset_tag (+0x00下位u16)', c.asset_tag);
  h += fieldRow('+0x18 (float, 推定用途不明)', c.field_0x18);
  h += fieldRow('+0x1c (float, 推定用途不明)', c.field_0x1c);
  h += fieldRow('float列 +0x08〜+0x44 (推定: バウンディングボックス/スケール)',
                c.floats_0x08_0x44.join(', '));
  h += `</table>`;
  h += `<div class="hint">${esc(data.note || '')}<br>詳細は ${esc(data.field_doc)} 参照。</div>`;
  detailEl.innerHTML = h;
}

switchDataset('player_stats');
