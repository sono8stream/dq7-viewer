// RomFS 画像ブラウザ (スクリプト/FPT/フロア/モデル/セーブ と同列の独立ページ)。
// .bctex / .bcmdl(埋め込み) / .dmp / LAYOUTTEX の .fpt(中の .dmp) /
// SCREENTEX の .fpt.lz (type-0x40 圧縮 FPT0。転職ポートレート等。タイルは
// @assembled として合成表示) を横断し、全部 PNG にデコードして一覧表示する。

const statusEl = document.getElementById('status');
const treeInner = document.getElementById('imgTreeInner');
const searchBox = document.getElementById('imgSearch');
const headEl = document.getElementById('imgHead');
const gridEl = document.getElementById('imgGrid');
const zoom = document.getElementById('imgZoom');
const zoomImg = document.getElementById('imgZoomImg');
const zoomCap = document.getElementById('imgZoomCap');
const mobileTabs = document.getElementById('mobileTabs');

const isMobile = () => window.matchMedia('(max-width: 760px)').matches;
function showPane(name) {
  document.querySelectorAll('#imgLayout .pane').forEach(p => p.classList.remove('mobile-active'));
  document.getElementById(name).classList.add('mobile-active');
  mobileTabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.pane === name));
}
mobileTabs.querySelectorAll('button').forEach(b => b.addEventListener('click', () => showPane(b.dataset.pane)));

zoom.addEventListener('click', () => { zoom.style.display = 'none'; zoomImg.src = ''; });
function openZoom(src, cap) {
  zoomImg.src = src; zoomCap.textContent = cap; zoom.style.display = 'flex';
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

let tree = {};          // group -> [ {name, path, kind, size} ]
let selected = null;

async function loadTree() {
  let data;
  try {
    data = await (await fetch('/api/img/tree')).json();
  } catch (e) {
    treeInner.innerHTML = `<div class="empty">読み込み失敗: ${esc(e.message || e)}</div>`;
    return;
  }
  if (data.error) { treeInner.innerHTML = `<div class="empty">エラー: ${esc(data.error)}</div>`; return; }
  tree = data;
  renderTree();
}

function renderTree() {
  const q = searchBox.value.trim().toLowerCase();
  const groups = Object.keys(tree).sort();
  let total = 0, shown = 0;
  treeInner.innerHTML = '';
  for (const g of groups) {
    const items = tree[g].filter(f => !q || f.path.toLowerCase().includes(q));
    total += tree[g].length;
    shown += items.length;
    if (!items.length) continue;
    const det = document.createElement('details');
    det.className = 'igrp';
    det.open = !!q || items.length <= 40;
    const sm = document.createElement('summary');
    sm.textContent = `${g} (${items.length})`;
    det.appendChild(sm);
    // cap very large groups unless searching
    const list = (!q && items.length > 400) ? items.slice(0, 400) : items;
    for (const f of list) {
      const row = document.createElement('div');
      row.className = 'ifile' + (selected === f.path ? ' selected' : '');
      row.innerHTML = `${esc(f.name)}<span class="k">${f.kind}</span>`;
      row.onclick = () => selectFile(f.path, row);
      det.appendChild(row);
    }
    if (list.length < items.length) {
      const more = document.createElement('div');
      more.className = 'file-meta';
      more.style.padding = '3px 6px';
      more.textContent = `… 他 ${items.length - list.length} 件（絞り込みで表示）`;
      det.appendChild(more);
    }
    treeInner.appendChild(det);
  }
  statusEl.textContent = `${shown} / ${total} files`;
  if (!shown) treeInner.innerHTML = '<div class="empty">該当なし</div>';
}
searchBox.addEventListener('input', renderTree);

async function selectFile(path, rowEl) {
  selected = path;
  document.querySelectorAll('.ifile.selected').forEach(x => x.classList.remove('selected'));
  if (rowEl) rowEl.classList.add('selected');
  if (isMobile()) showPane('imgMain');
  headEl.textContent = `${path} — 読み込み中...`;
  gridEl.innerHTML = '';
  let imgs;
  try {
    imgs = await (await fetch(`/api/img/list?path=${encodeURIComponent(path)}`)).json();
  } catch (e) {
    headEl.textContent = `${path} — 失敗: ${e.message || e}`;
    return;
  }
  if (imgs.error) { headEl.textContent = `${path} — エラー: ${imgs.error}`; return; }
  headEl.textContent = `${path} — ${imgs.length} 画像`;
  const frag = document.createDocumentFragment();
  for (const im of imgs) {
    const cell = document.createElement('div');
    cell.className = 'icell';
    const cap = `${esc(im.name)}<br>${im.width}x${im.height} ${esc(im.format || '?')}`;
    if (im.ok) {
      const u = `/api/img/png?path=${encodeURIComponent(path)}&name=${encodeURIComponent(im.name)}`;
      cell.innerHTML = `<img src="${u}" loading="lazy" alt="${esc(im.name)}"><div class="cap">${cap}</div>`;
      cell.querySelector('img').onclick = () => openZoom(u, `${path}  ${im.name}  ${im.width}x${im.height} ${im.format || ''}`);
    } else {
      cell.innerHTML = `<div style="width:128px;height:128px;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;color:#a55;background:#222">×</div><div class="cap">${cap}</div>`;
    }
    frag.appendChild(cell);
  }
  gridEl.appendChild(frag);
}

loadTree();
