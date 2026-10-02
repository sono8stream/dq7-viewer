// フロア(マップ)ビューア - LEVELDATA/dq7_floor_list.dat の
// フロアID <-> マップコード <-> SCRIPTファイルの対応を確認する。
// スクリプト/FPT/セーブと同列の独立ページ。バックエンドは
// /api/floor_list (一覧) と /api/floor_detail?id=N (詳細)。

DQ7I18N.extend({
  ja: {
    'floor.tabList': 'フロア一覧',
    'floor.searchPlaceholder': 'フロアID / マップコード / group で絞り込み...',
    'floor.selectPrompt': 'フロアを選択すると、対応ファイルと出入りのワープ一覧が表示されます',
    'floor.noMatch': '該当なし',
    'floor.loadFailed': '読み込み失敗',
    'floor.loadingInitial': '読み込み中... (初回はSCRIPT全走査のため数秒かかります)',
    'floor.noName': '(no name)',
    'floor.hasScript': 'が存在',
    'floor.noScriptFile': '対応する SCRIPT/<mapcode>.bin なし',
    'floor.warpsInTitle': 'このフロアを行き先にする MAP_WARP の数',
    'floor.warpsOutTitle': 'このフロアのSCRIPT内にある MAP_WARP の数',
    'floor.facing': '向き',
    'floor.flag5': 'flag5',
    'floor.floorIdLabel': 'フロアID',
    'floor.mapcodeLabel': 'マップコード',
    'floor.groupLabel': 'group',
    'floor.noNameLabel': '(名前なし)',
    'floor.layoutLabel': 'レイアウト',
    'floor.layoutDesc': '+0x00 u32=(未使用) / +0x04 u16=フロアID / +0x06 u16=group / +0x08 char[8]=マップコード',
    'floor.scriptFileLabel': '対応SCRIPTファイル',
    'floor.scriptFileNone': '(なし — SCRIPT/<mapcode>.bin が存在しない)',
    'floor.warpsInSection': 'このフロアへ入ってくる MAP_WARP',
    'floor.warpsInSub': '別のフロアのスクリプトが param0=%d で飛んでくる箇所:',
    'floor.none': '(なし)',
    'floor.warpsOutSection': 'このフロアのSCRIPT内にある MAP_WARP',
    'floor.warpsOutUnavailable': '(対応SCRIPTファイルがないため取得不可)',
    'floor.footnote1': '※ MAP_WARP(opcode 0x0001001f) は「有力な仮説・実機未検証」。',
    'floor.footnote2': '  詳細は docs/script_opcode_0x1001f_map_warp.md。',
  },
  en: {
    'floor.tabList': 'Floors',
    'floor.searchPlaceholder': 'Filter by floor ID / map code / group...',
    'floor.selectPrompt': 'Select a floor to see its file and inbound/outbound warps',
    'floor.noMatch': 'No matches',
    'floor.loadFailed': 'Load failed',
    'floor.loadingInitial': 'Loading... (first load scans all SCRIPT files, takes a few seconds)',
    'floor.noName': '(no name)',
    'floor.hasScript': 'exists',
    'floor.noScriptFile': 'no matching SCRIPT/<mapcode>.bin',
    'floor.warpsInTitle': 'Number of MAP_WARP commands that target this floor',
    'floor.warpsOutTitle': 'Number of MAP_WARP commands inside this floor\'s SCRIPT',
    'floor.facing': 'facing',
    'floor.flag5': 'flag5',
    'floor.floorIdLabel': 'Floor ID',
    'floor.mapcodeLabel': 'Map code',
    'floor.groupLabel': 'group',
    'floor.noNameLabel': '(no name)',
    'floor.layoutLabel': 'Layout',
    'floor.layoutDesc': '+0x00 u32=(unused) / +0x04 u16=floor ID / +0x06 u16=group / +0x08 char[8]=map code',
    'floor.scriptFileLabel': 'Matching SCRIPT file',
    'floor.scriptFileNone': '(none — SCRIPT/<mapcode>.bin does not exist)',
    'floor.warpsInSection': 'MAP_WARP commands entering this floor',
    'floor.warpsInSub': 'Places where another floor\'s script jumps here with param0=%d:',
    'floor.none': '(none)',
    'floor.warpsOutSection': 'MAP_WARP commands inside this floor\'s SCRIPT',
    'floor.warpsOutUnavailable': '(unavailable — no matching SCRIPT file)',
    'floor.footnote1': '* MAP_WARP (opcode 0x0001001f) is a "strong hypothesis, unverified on real hardware".',
    'floor.footnote2': '  See docs/script_opcode_0x1001f_map_warp.md for details.',
  },
});

const listInner = document.getElementById('floorListInner');
const searchBox = document.getElementById('floorSearch');
const subEl = document.getElementById('floorSub');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');

let allEntries = [];
let selectedId = null;

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

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

async function loadList() {
  listInner.innerHTML = `<div class="empty">${DQ7I18N.t('floor.loadingInitial')}</div>`;
  let data;
  try {
    const res = await fetch('/api/floor_list');
    data = await res.json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('floor.loadFailed')}: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('common.error')}: ${esc(data.error)}</div>`;
    return;
  }
  allEntries = data.entries || [];
  renderSub(data);
  renderList();
}

let lastListData = null;
function renderSub(data) {
  lastListData = data;
  if (DQ7I18N.getLang() === 'en') {
    subEl.textContent =
      `${data.source} — ${data.record_count} records / scanned ${data.scanned_script_files} SCRIPT files / ` +
      `${data.total_warp_commands} MAP_WARP commands total. Click a row for details.`;
  } else {
    subEl.textContent =
      `${data.source} — ${data.record_count} レコード / SCRIPT ${data.scanned_script_files} ファイル走査 / ` +
      `MAP_WARP 命令 ${data.total_warp_commands} 件。行クリックで詳細。`;
  }
}

function renderList() {
  const q = searchBox.value.trim().toLowerCase();
  const rows = q
    ? allEntries.filter(e =>
        String(e.floor_id).includes(q) ||
        (e.mapcode && e.mapcode.toLowerCase().includes(q)) ||
        ('group ' + e.group).includes(q) ||
        ('g' + e.group) === q)
    : allEntries;
  // skip blank-mapcode padding rows unless the user is searching for them
  const shown = q ? rows : rows.filter(e => e.mapcode);
  statusEl.textContent = `${shown.length} / ${allEntries.length}`;
  const frag = document.createDocumentFragment();
  for (const e of shown) {
    const row = document.createElement('div');
    row.className = 'floor-row' + (e.floor_id === selectedId ? ' selected' : '');
    row.dataset.id = e.floor_id;
    const mc = e.mapcode
      ? `<span class="mc">${esc(e.mapcode)}</span>`
      : `<span class="mc no-mc">${esc(DQ7I18N.t('floor.noName'))}</span>`;
    const scr = e.script_file
      ? `<span class="badge has" title="${esc(e.script_file)} ${esc(DQ7I18N.t('floor.hasScript'))}">▸SCRIPT</span>`
      : `<span class="badge" title="${esc(DQ7I18N.t('floor.noScriptFile'))}">–</span>`;
    row.innerHTML =
      `<span class="fid">#${e.floor_id}</span>` +
      mc +
      `<span class="grp">g${e.group}</span>` +
      scr +
      `<span class="badge" title="${esc(DQ7I18N.t('floor.warpsInTitle'))}">↘${e.warps_in}</span>` +
      `<span class="badge" title="${esc(DQ7I18N.t('floor.warpsOutTitle'))}">↗${e.warps_out}</span>`;
    row.onclick = () => selectFloor(e.floor_id, row);
    frag.appendChild(row);
  }
  listInner.innerHTML = '';
  if (!shown.length) {
    listInner.innerHTML = `<div class="empty">${DQ7I18N.t('floor.noMatch')}</div>`;
    return;
  }
  listInner.appendChild(frag);
}
searchBox.addEventListener('input', renderList);

function warpLine(w) {
  // "  g/o(tag)/proc #cmd  → <dstname> (#id) @(x,y,z) 向き=.. flag5=.."
  const pos = `(${w.pos.join(', ')})`;
  const face = w.facing === null || w.facing === undefined ? '' : `  ${DQ7I18N.t('floor.facing')}=${w.facing}`;
  const f5 = w.flag5 === null || w.flag5 === undefined ? '' : `  ${DQ7I18N.t('floor.flag5')}=${w.flag5}`;
  const dst = w.dst_map_name ? `${w.dst_map_name} (#${w.dst_map_id})` : `map#${w.dst_map_id}`;
  return `    g${w.group_idx}/o${w.obj_idx}(${w.obj_tag || '-'})/${w.proc_tag} #${w.cmd_idx}  → ${dst} @${pos}${face}${f5}`;
}

let lastFloorDetail = null;

async function selectFloor(fid, rowEl) {
  selectedId = fid;
  document.querySelectorAll('.floor-row.selected').forEach(x => x.classList.remove('selected'));
  if (rowEl) rowEl.classList.add('selected');
  detailEl.textContent = DQ7I18N.t('common.loading');
  if (isMobile()) showPane('detail');
  let d;
  try {
    const res = await fetch(`/api/floor_detail?id=${fid}`);
    d = await res.json();
  } catch (e) {
    detailEl.textContent = `${DQ7I18N.t('floor.loadFailed')}: ${e.message || e}`;
    return;
  }
  if (d.error) {
    detailEl.textContent = `${DQ7I18N.t('common.error')}: ${d.error}`;
    return;
  }
  lastFloorDetail = d;
  renderFloorDetail(d);
}

function renderFloorDetail(d) {
  const r = d.record || {};
  const t = DQ7I18N.t;
  const lines = [];
  lines.push(`${t('floor.floorIdLabel')} #${d.floor_id}`);
  lines.push(`${t('floor.mapcodeLabel')} : ${r.mapcode || t('floor.noNameLabel')}`);
  lines.push(`${t('floor.groupLabel')}        : ${r.group}`);
  lines.push(`dq7_floor_list.dat record #${r.rec_index}  raw=${r.raw_hex}`);
  lines.push(`  ${t('floor.layoutLabel')}: ${t('floor.layoutDesc').replace('+0x00 u32=', `+0x00 u32=${r.unk0} `)}`);
  lines.push('');
  lines.push(`${t('floor.scriptFileLabel')} : ${d.script_file || t('floor.scriptFileNone')}`);
  lines.push('');
  lines.push(`── ${t('floor.warpsInSection')} (${d.warps_in.length}) ──`);
  lines.push(`   ${t('floor.warpsInSub').replace('%d', d.floor_id)}`);
  if (!d.warps_in.length) {
    lines.push(`  ${t('floor.none')}`);
  } else {
    const byFile = {};
    for (const w of d.warps_in) (byFile[w.file] = byFile[w.file] || []).push(w);
    for (const f of Object.keys(byFile).sort()) {
      lines.push(`  【${f}】 ${byFile[f].length}`);
      for (const w of byFile[f]) lines.push(warpLine(w));
    }
  }
  lines.push('');
  lines.push(`── ${t('floor.warpsOutSection')} (${d.warps_out.length}) ──`);
  if (!d.script_file) {
    lines.push(`  ${t('floor.warpsOutUnavailable')}`);
  } else if (!d.warps_out.length) {
    lines.push(`  ${t('floor.none')}`);
  } else {
    for (const w of d.warps_out) lines.push(warpLine(w));
  }
  lines.push('');
  lines.push(t('floor.footnote1'));
  lines.push(t('floor.footnote2'));
  detailEl.textContent = lines.join('\n');
}

window.addEventListener('dq7lang:change', () => {
  if (lastListData) renderSub(lastListData);
  renderList();
  if (lastFloorDetail) renderFloorDetail(lastFloorDetail);
});

loadList();
