const alignmentSel = document.getElementById('alignmentSel');
const filterC = document.getElementById('filterC');
const jumpOffset = document.getElementById('jumpOffset');
const jumpBtn = document.getElementById('jumpBtn');
const metaBox = document.getElementById('metaBox');
const tableBody = document.getElementById('tableBody');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const pageInfo = document.getElementById('pageInfo');
const prevBtn2 = document.getElementById('prevBtn2');
const nextBtn2 = document.getElementById('nextBtn2');
const pageInfo2 = document.getElementById('pageInfo2');

const PAGE_SIZE = 50;

let fullData = null;
let filteredRecords = [];
let page = 0;
let highlightOffset = null;

async function load() {
  metaBox.textContent = '読み込み中...';
  try {
    const res = await fetch('/api/person_jidx');
    fullData = await res.json();
    if (fullData.error) {
      metaBox.textContent = 'エラー: ' + fullData.error;
      return;
    }
    applyFilter();
  } catch (e) {
    metaBox.textContent = '通信エラー: ' + e;
  }
}

function currentRecords() {
  const alignment = alignmentSel.value;
  return fullData.alignments[alignment].records;
}

function applyFilter() {
  const records = currentRecords();
  const cVal = filterC.value.trim();
  if (cVal === '') {
    filteredRecords = records;
  } else {
    const c = parseInt(cVal, 10);
    filteredRecords = records.filter((r) => r.c === c);
  }
  page = 0;
  renderMeta();
  renderTable();
}

function renderMeta() {
  const lines = [
    `file_size: ${fullData.file_size}`,
    `2byteヘッダで割り切れる: ${fullData.divides_evenly_with_2byte_header} (record_count=${fullData.record_count_with_2byte_header})`,
    `現在のレコード総数: ${currentRecords().length}件 / フィルタ後: ${filteredRecords.length}件`,
  ];
  metaBox.textContent = lines.join('\n');
}

function renderTable() {
  const totalPages = Math.max(1, Math.ceil(filteredRecords.length / PAGE_SIZE));
  if (page >= totalPages) page = totalPages - 1;
  if (page < 0) page = 0;

  const start = page * PAGE_SIZE;
  const rows = filteredRecords.slice(start, start + PAGE_SIZE);

  tableBody.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    if (highlightOffset !== null && r.offset === highlightOffset) {
      tr.classList.add('jidx-highlight');
    }
    const aCell = document.createElement('td');
    const aLink = document.createElement('button');
    aLink.className = 'jidx-link';
    aLink.textContent = r.a;
    aLink.title = 'このオフセットへジャンプ';
    aLink.addEventListener('click', () => {
      jumpOffset.value = r.a;
      doJump();
    });
    aCell.appendChild(aLink);

    const cCell = document.createElement('td');
    const cLink = document.createElement('button');
    cLink.className = 'jidx-link';
    cLink.textContent = r.c;
    cLink.title = 'この値でフィルタ';
    cLink.addEventListener('click', () => {
      filterC.value = r.c;
      applyFilter();
    });
    cCell.appendChild(cLink);

    tr.innerHTML = `<td>${r.index}</td><td>${r.offset} (0x${r.offset.toString(16)})</td>`;
    tr.appendChild(aCell);
    tr.innerHTML += `<td>${r.b}</td>`;
    tr.appendChild(cCell);
    tableBody.appendChild(tr);
  }

  const infoText = `ページ ${page + 1} / ${totalPages}`;
  pageInfo.textContent = infoText;
  pageInfo2.textContent = infoText;

  if (highlightOffset !== null) {
    const row = [...tableBody.children].find((tr) => tr.classList.contains('jidx-highlight'));
    if (row) row.scrollIntoView({ block: 'center' });
  }
}

function doJump() {
  const val = parseInt(jumpOffset.value, 10);
  if (Number.isNaN(val)) return;
  // オフセットに一致する(無ければ一番近い)レコードを、現在のフィルタに関係なく
  // アライメント全体から探す
  const records = currentRecords();
  let best = null;
  for (const r of records) {
    if (r.offset === val) { best = r; break; }
    if (best === null || Math.abs(r.offset - val) < Math.abs(best.offset - val)) best = r;
  }
  if (!best) return;
  // フィルタを解除してジャンプ先が必ず見えるようにする
  filterC.value = '';
  filteredRecords = records;
  highlightOffset = best.offset;
  page = Math.floor(filteredRecords.indexOf(best) / PAGE_SIZE);
  renderMeta();
  renderTable();
}

alignmentSel.addEventListener('change', applyFilter);
filterC.addEventListener('change', applyFilter);
jumpBtn.addEventListener('click', doJump);
jumpOffset.addEventListener('keydown', (e) => { if (e.key === 'Enter') doJump(); });

for (const [prev, next] of [[prevBtn, nextBtn], [prevBtn2, nextBtn2]]) {
  prev.addEventListener('click', () => { page = Math.max(0, page - 1); renderTable(); });
  next.addEventListener('click', () => { page += 1; renderTable(); });
}

load();
