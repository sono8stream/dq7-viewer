// フロア(マップ)ビューア - LEVELDATA/dq7_floor_list.dat の
// フロアID <-> マップコード <-> SCRIPTファイルの対応を確認する。
// スクリプト/FPT/セーブと同列の独立ページ。バックエンドは
// /api/floor_list (一覧) と /api/floor_detail?id=N (詳細)。

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
  listInner.innerHTML = '<div class="empty">読み込み中... (初回はSCRIPT全走査のため数秒かかります)</div>';
  let data;
  try {
    const res = await fetch('/api/floor_list');
    data = await res.json();
  } catch (e) {
    listInner.innerHTML = `<div class="empty">読み込み失敗: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) {
    listInner.innerHTML = `<div class="empty">エラー: ${esc(data.error)}</div>`;
    return;
  }
  allEntries = data.entries || [];
  subEl.textContent =
    `${data.source} — ${data.record_count} レコード / SCRIPT ${data.scanned_script_files} ファイル走査 / ` +
    `MAP_WARP 命令 ${data.total_warp_commands} 件。行クリックで詳細。`;
  renderList();
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
      : `<span class="mc no-mc">(no name)</span>`;
    const scr = e.script_file
      ? `<span class="badge has" title="${esc(e.script_file)} が存在">▸SCRIPT</span>`
      : `<span class="badge" title="対応する SCRIPT/&lt;mapcode&gt;.bin なし">–</span>`;
    row.innerHTML =
      `<span class="fid">#${e.floor_id}</span>` +
      mc +
      `<span class="grp">g${e.group}</span>` +
      scr +
      `<span class="badge" title="このフロアを行き先にする MAP_WARP の数">↘${e.warps_in}</span>` +
      `<span class="badge" title="このフロアのSCRIPT内にある MAP_WARP の数">↗${e.warps_out}</span>`;
    row.onclick = () => selectFloor(e.floor_id, row);
    frag.appendChild(row);
  }
  listInner.innerHTML = '';
  if (!shown.length) {
    listInner.innerHTML = '<div class="empty">該当なし</div>';
    return;
  }
  listInner.appendChild(frag);
}
searchBox.addEventListener('input', renderList);

function warpLine(w) {
  // "  g/o(tag)/proc #cmd  → <dstname> (#id) @(x,y,z) 向き=.. flag5=.."
  const pos = `(${w.pos.join(', ')})`;
  const face = w.facing === null || w.facing === undefined ? '' : `  向き=${w.facing}`;
  const f5 = w.flag5 === null || w.flag5 === undefined ? '' : `  flag5=${w.flag5}`;
  const dst = w.dst_map_name ? `${w.dst_map_name} (#${w.dst_map_id})` : `map#${w.dst_map_id}`;
  return `    g${w.group_idx}/o${w.obj_idx}(${w.obj_tag || '-'})/${w.proc_tag} #${w.cmd_idx}  → ${dst} @${pos}${face}${f5}`;
}

async function selectFloor(fid, rowEl) {
  selectedId = fid;
  document.querySelectorAll('.floor-row.selected').forEach(x => x.classList.remove('selected'));
  if (rowEl) rowEl.classList.add('selected');
  detailEl.textContent = '読み込み中...';
  if (isMobile()) showPane('detail');
  let d;
  try {
    const res = await fetch(`/api/floor_detail?id=${fid}`);
    d = await res.json();
  } catch (e) {
    detailEl.textContent = `読み込み失敗: ${e.message || e}`;
    return;
  }
  if (d.error) {
    detailEl.textContent = `エラー: ${d.error}`;
    return;
  }
  const r = d.record || {};
  const lines = [];
  lines.push(`フロアID #${d.floor_id}`);
  lines.push(`マップコード : ${r.mapcode || '(名前なし)'}`);
  lines.push(`group        : ${r.group}`);
  lines.push(`dq7_floor_list.dat レコード#${r.rec_index}  raw=${r.raw_hex}`);
  lines.push(`  レイアウト: +0x00 u32=${r.unk0} (未使用) / +0x04 u16=フロアID / +0x06 u16=group / +0x08 char[8]=マップコード`);
  lines.push('');
  lines.push(`対応SCRIPTファイル : ${d.script_file || '(なし — SCRIPT/<mapcode>.bin が存在しない)'}`);
  lines.push('');
  lines.push(`── このフロアへ入ってくる MAP_WARP (${d.warps_in.length}件) ──`);
  lines.push(`   別のフロアのスクリプトが param0=${d.floor_id} で飛んでくる箇所:`);
  if (!d.warps_in.length) {
    lines.push('  (なし)');
  } else {
    const byFile = {};
    for (const w of d.warps_in) (byFile[w.file] = byFile[w.file] || []).push(w);
    for (const f of Object.keys(byFile).sort()) {
      lines.push(`  【${f}】 ${byFile[f].length}件`);
      for (const w of byFile[f]) lines.push(warpLine(w));
    }
  }
  lines.push('');
  lines.push(`── このフロアのSCRIPT内にある MAP_WARP (${d.warps_out.length}件) ──`);
  if (!d.script_file) {
    lines.push('  (対応SCRIPTファイルがないため取得不可)');
  } else if (!d.warps_out.length) {
    lines.push('  (なし)');
  } else {
    for (const w of d.warps_out) lines.push(warpLine(w));
  }
  lines.push('');
  lines.push('※ MAP_WARP(opcode 0x0001001f) は「有力な仮説・実機未検証」。');
  lines.push('  詳細は docs/script_opcode_0x1001f_map_warp.md。');
  detailEl.textContent = lines.join('\n');
}

loadList();
