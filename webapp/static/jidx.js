DQ7I18N.extend({
  ja: {
    'jidx.title': 'person.jidx 構造解析ビュアー',
    'jidx.hint': '<code>CHARACTER/person.jidx</code>（22718byte、未解読）を6byteレコード'
      + '<code>{u16 a, u16 b, u16 c}</code>の並びとして読んだ結果を表示します。'
      + 'ヘッダの有無・各フィールドの意味は<strong>まだ確定していません</strong>'
      + '（<code>docs/keifa_job_animation_investigation.md</code>参照）。'
      + '「a」列は別のレコードのオフセットを指しているように見えるので、'
      + 'クリックするとそのオフセットへジャンプできます（自己参照構造の追跡用）。',
    'jidx.alignmentLabel': '読み方:',
    'jidx.noHeader': 'ヘッダ無し(offset 0開始)',
    'jidx.header2byte': '2byteヘッダ(offset 2開始)',
    'jidx.filterLabel': 'cでフィルタ(job idらしき値、空欄で全件):',
    'jidx.jumpLabel': 'オフセットへジャンプ:',
    'jidx.prev': '← 前',
    'jidx.next': '次 →',
    'jidx.loading': '読み込み中...',
    'jidx.commError': '通信エラー: ',
    'jidx.jumpThisOffset': 'このオフセットへジャンプ',
    'jidx.filterByThis': 'この値でフィルタ',
    'jidx.page': 'ページ',
    'jidx.dividesEvenly': '2byteヘッダで割り切れる',
    'jidx.currentRecordCount': '現在のレコード総数',
    'jidx.records': '件',
    'jidx.afterFilter': 'フィルタ後',
  },
  en: {
    'jidx.title': 'person.jidx Structure Viewer',
    'jidx.hint': 'Shows <code>CHARACTER/person.jidx</code> (22718 bytes, undeciphered) read as a sequence of '
      + '6-byte records <code>{u16 a, u16 b, u16 c}</code>. Whether there is a header, and the meaning of each '
      + 'field, are <strong>still unconfirmed</strong> '
      + '(see <code>docs/keifa_job_animation_investigation.md</code>). '
      + 'Column "a" appears to point to another record\'s offset, so clicking it jumps to that offset '
      + '(for tracing the self-referential structure).',
    'jidx.alignmentLabel': 'Alignment:',
    'jidx.noHeader': 'No header (starts at offset 0)',
    'jidx.header2byte': '2-byte header (starts at offset 2)',
    'jidx.filterLabel': 'Filter by c (presumed job id, blank = all):',
    'jidx.jumpLabel': 'Jump to offset:',
    'jidx.prev': '← Prev',
    'jidx.next': 'Next →',
    'jidx.loading': 'Loading...',
    'jidx.commError': 'Communication error: ',
    'jidx.jumpThisOffset': 'Jump to this offset',
    'jidx.filterByThis': 'Filter by this value',
    'jidx.page': 'Page',
    'jidx.dividesEvenly': 'Divides evenly with 2-byte header',
    'jidx.currentRecordCount': 'Current total records',
    'jidx.records': '',
    'jidx.afterFilter': 'after filter',
  },
});

function JT(key) { return DQ7I18N.t('jidx.' + key); }

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
  metaBox.textContent = JT('loading');
  try {
    const res = await fetch('/api/person_jidx');
    fullData = await res.json();
    if (fullData.error) {
      metaBox.textContent = DQ7I18N.t('common.error') + ': ' + fullData.error;
      return;
    }
    applyFilter();
  } catch (e) {
    metaBox.textContent = JT('commError') + e;
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
    `${JT('dividesEvenly')}: ${fullData.divides_evenly_with_2byte_header} (record_count=${fullData.record_count_with_2byte_header})`,
    `${JT('currentRecordCount')}: ${currentRecords().length} / ${JT('afterFilter')}: ${filteredRecords.length}`,
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
    aLink.title = JT('jumpThisOffset');
    aLink.addEventListener('click', () => {
      jumpOffset.value = r.a;
      doJump();
    });
    aCell.appendChild(aLink);

    const cCell = document.createElement('td');
    const cLink = document.createElement('button');
    cLink.className = 'jidx-link';
    cLink.textContent = r.c;
    cLink.title = JT('filterByThis');
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

  const infoText = `${JT('page')} ${page + 1} / ${totalPages}`;
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

window.addEventListener('dq7lang:change', () => { if (fullData) { renderMeta(); renderTable(); } });

load();
