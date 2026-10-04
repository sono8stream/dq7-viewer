if (window.DQ7I18N) {
  DQ7I18N.extend({
    ja: {
      'editor.editModeOff': '編集モード: OFF',
      'editor.editModeOn': '編集モード: ON',
      'editor.historyBtn': '変更履歴',
      'editor.flagsBtn': '使用フラグ',
      'editor.searchTextBtn': 'メッセージ検索',
      'editor.repackBtn': '再パック&Downloadsへ配置',
      'editor.repacking': 'リパック中...',
      'editor.repackInProgress': '再パック→検証→Downloadsへコピー中（1〜2分かかります）...',
      'editor.tabFiles': 'ファイル',
      'editor.tabTree': 'ツリー',
      'editor.tabDetail': '詳細',
      'editor.selCopy': 'コピー',
      'editor.selIndentInc': 'インデントを深く',
      'editor.selIndentDec': 'インデントを浅く',
      'editor.selDelete': '選択を一括削除',
      'editor.selClear': '選択解除',
      'editor.pendingSave': '保存',
      'editor.pendingDiscard': '破棄',
      'editor.fileSearchPlaceholder': 'ファイル名で絞り込み...',
      'editor.recentLabel': '最近開いたファイル',
      'editor.treeEmpty': '左からSCRIPTファイルを選択してください',
      'editor.detailEmpty': 'コマンドを選択すると詳細が表示されます',
      'editor.cancel': 'キャンセル',
      'editor.editThisCommand': 'このコマンドを編集',
      'editor.reload': '⟳ 再読み込み',
      'editor.reloadTitle': 'サーバー側の最新の内容を再取得します',
    },
    en: {
      'editor.editModeOff': 'Edit mode: OFF',
      'editor.editModeOn': 'Edit mode: ON',
      'editor.historyBtn': 'History',
      'editor.flagsBtn': 'Flag usage',
      'editor.searchTextBtn': 'Search messages',
      'editor.repackBtn': 'Repack & deploy to Downloads',
      'editor.repacking': 'Repacking...',
      'editor.repackInProgress': 'Repacking → verifying → copying to Downloads (takes 1-2 min)...',
      'editor.tabFiles': 'Files',
      'editor.tabTree': 'Tree',
      'editor.tabDetail': 'Detail',
      'editor.selCopy': 'Copy',
      'editor.selIndentInc': 'Indent +',
      'editor.selIndentDec': 'Indent -',
      'editor.selDelete': 'Delete selection',
      'editor.selClear': 'Clear selection',
      'editor.pendingSave': 'Save',
      'editor.pendingDiscard': 'Discard',
      'editor.fileSearchPlaceholder': 'Filter by filename...',
      'editor.recentLabel': 'Recently opened files',
      'editor.treeEmpty': 'Select a SCRIPT file on the left',
      'editor.detailEmpty': 'Select a command to see its details',
      'editor.cancel': 'Cancel',
      'editor.editThisCommand': 'Edit this command',
      'editor.reload': '⟳ Reload',
      'editor.reloadTitle': 'Re-fetch the latest content from the server',
    },
  });
}
const t = (window.DQ7I18N ? DQ7I18N.t : (k, f) => (f !== undefined ? f : k));

const fileListInner = document.getElementById('fileListInner');
const fileSearch = document.getElementById('fileSearch');
const treeEl = document.getElementById('tree');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const mobileTabs = document.getElementById('mobileTabs');
const recentListWrap = document.getElementById('recentListWrap');
const recentListInner = document.getElementById('recentListInner');
const editModeToggle = document.getElementById('editModeToggle');
const repackBtn = document.getElementById('repackBtn');
const repackStatusEl = document.getElementById('repackStatus');
const historyBtn = document.getElementById('historyBtn');
const flagsBtn = document.getElementById('flagsBtn');
const searchTextBtn = document.getElementById('searchTextBtn');
const pendingBarEl = document.getElementById('pendingBar');
const pendingBarCountEl = document.getElementById('pendingBarCount');
const pendingBarStatusEl = document.getElementById('pendingBarStatus');
const pendingSaveBtn = document.getElementById('pendingSaveBtn');
const pendingDiscardBtn = document.getElementById('pendingDiscardBtn');
const selectionBarEl = document.getElementById('selectionBar');
const selectionBarCountEl = document.getElementById('selectionBarCount');
const selectionCopyBtn = document.getElementById('selectionCopyBtn');
const selectionIndentIncBtn = document.getElementById('selectionIndentIncBtn');
const selectionIndentDecBtn = document.getElementById('selectionIndentDecBtn');
const selectionDeleteBtn = document.getElementById('selectionDeleteBtn');
const selectionClearBtn = document.getElementById('selectionClearBtn');
const clipboardStatusEl = document.getElementById('clipboardStatus');

let allFiles = [];
let currentTree = null;
let currentFileName = null;
let editMode = false;

// Staged-edit buffer (added 2026-08-25): edits made via the command editor
// no longer write to disk immediately - they accumulate here as an
// in-browser working copy (pendingDataB64) plus the ordered list of ops
// that produced it (pendingEdits), and the tree is re-rendered from that
// preview state (via POST /api/script/edit_preview, which never touches
// the real file). Nothing is actually written until 保存 replays
// pendingEdits against the real file in order (one real POST
// /api/script/edit per staged op, so change-history stays fully
// granular); 破棄 just drops the buffer and reloads from disk.
let pendingDataB64 = null;
let pendingEdits = [];

// Multi-select clipboard (added 2026-08-27): lets the user tick several
// commands (possibly spanning multiple procedures/objects, even across
// files - clipboardCommands is just raw {indent,opcode,params} data with
// no file/position info once copied) and either paste them as a block at
// any insertion point, or bulk-delete the selection in one action.
// selectedKeys holds `g{gi}-o{oi}-p{tag}-c{ci}` strings against the
// CURRENTLY displayed tree; copying/deleting reads the current tree via
// those keys, but the resulting clipboardCommands array is
// self-contained and survives navigating to a different file.
let selectedKeys = new Set();
let clipboardCommands = null;

editModeToggle.addEventListener('click', () => {
  editMode = !editMode;
  editModeToggle.textContent = t(editMode ? 'editor.editModeOn' : 'editor.editModeOff');
  editModeToggle.classList.toggle('active', editMode);
  if (!editMode) { selectedKeys = new Set(); renderSelectionBar(); }
  if (currentTree) renderTree(currentTree);
});

// Runs the same repack -> verify -> copy-to-Downloads sequence documented
// in docs/repack_and_test_workflow.md (webapp/server.py:repack_and_deploy).
// Takes 1-2 minutes - the request just blocks until it's done, no
// polling/progress endpoint, so the button is disabled meanwhile to avoid
// firing it twice concurrently.
repackBtn.addEventListener('click', async () => {
  repackBtn.disabled = true;
  const originalLabel = repackBtn.textContent;
  repackBtn.textContent = t('editor.repacking');
  repackStatusEl.textContent = t('editor.repackInProgress');
  repackStatusEl.style.color = '';
  try {
    const res = await fetch('/api/repack', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) {
      repackStatusEl.textContent = `${t('common.error')} (${data.stage || 'unknown'}): ${data.error || (data.stderr || '').slice(0, 200)}`;
      repackStatusEl.style.color = '#e88080';
    } else {
      const mb = (data.size / 1024 / 1024).toFixed(1);
      repackStatusEl.textContent = `完了: ${data.target} (${mb}MB) - VERIFY PASS`;
      repackStatusEl.style.color = '#9fd18a';
    }
  } catch (e) {
    repackStatusEl.textContent = `${t('common.error')}: ${e.message || e}`;
    repackStatusEl.style.color = '#e88080';
  } finally {
    repackBtn.disabled = false;
    repackBtn.textContent = originalLabel;
  }
});

historyBtn.addEventListener('click', () => {
  showHistoryPanel();
  if (isMobile()) showPane('detail');
});

flagsBtn.addEventListener('click', () => {
  showFlagUsagePanel();
  if (isMobile()) showPane('detail');
});

searchTextBtn.addEventListener('click', () => {
  showSearchTextPanel();
  if (isMobile()) showPane('detail');
});

pendingSaveBtn.addEventListener('click', () => { commitPendingEdits(); });
pendingDiscardBtn.addEventListener('click', () => { discardPendingEdits(); });

selectionCopyBtn.addEventListener('click', () => { copySelected(); });
selectionIndentIncBtn.addEventListener('click', () => { bulkIndentSelected(1); });
selectionIndentDecBtn.addEventListener('click', () => { bulkIndentSelected(-1); });
selectionDeleteBtn.addEventListener('click', () => { deleteSelected(); });
selectionClearBtn.addEventListener('click', () => { selectedKeys = new Set(); renderTree(currentTree); renderSelectionBar(); });

// --- recently opened files: remembered per-browser via localStorage so
// re-visiting the viewer doesn't require re-searching for the same
// SCRIPT file every time (most workflows revisit one file repeatedly
// while iterating on a patch).
const RECENT_KEY = 'dq7scriptviewer.recentFiles';
const RECENT_MAX = 8;

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveRecent(list) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch (e) {
    // ignore (e.g. storage disabled)
  }
}

function pushRecent(name) {
  let list = loadRecent().filter(n => n !== name);
  list.unshift(name);
  if (list.length > RECENT_MAX) list = list.slice(0, RECENT_MAX);
  saveRecent(list);
  renderRecentList();
}

function renderRecentList() {
  const list = loadRecent();
  recentListWrap.style.display = list.length ? '' : 'none';
  recentListInner.innerHTML = '';
  for (const name of list) {
    const div = document.createElement('div');
    div.className = 'file-item';
    div.textContent = name;
    div.onclick = () => selectFile(name);
    recentListInner.appendChild(div);
  }
}

// --- mobile pane switcher: below the CSS breakpoint only one .pane is
// shown at a time, driven by the tab bar; selecting a file/command also
// auto-advances to the next pane so the flow stays a single-column drill
// down (file list -> tree -> detail) instead of requiring manual taps.
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

async function loadFiles() {
  const res = await fetch('/api/files');
  allFiles = await res.json();
  renderFileList();
  renderRecentList();
  const recent = loadRecent();
  if (recent.length && allFiles.some(f => f.name === recent[0])) {
    selectFile(recent[0]);
  }
}

function renderFileList() {
  const q = fileSearch.value.trim().toLowerCase();
  fileListInner.innerHTML = '';
  const filtered = q ? allFiles.filter(f => f.name.toLowerCase().includes(q)) : allFiles;
  statusEl.textContent = `${filtered.length} / ${allFiles.length} files`;
  for (const f of filtered) {
    const div = document.createElement('div');
    div.className = 'file-item';
    div.textContent = f.name;
    const meta = document.createElement('span');
    meta.className = 'file-meta';
    meta.textContent = `${(f.size / 1024).toFixed(1)}KB`;
    div.appendChild(meta);
    div.onclick = () => selectFile(f.name);
    fileListInner.appendChild(div);
  }
}

fileSearch.addEventListener('input', renderFileList);

async function selectFile(name) {
  if (pendingEdits.length && !confirm(`未保存の変更${pendingEdits.length}件を破棄して別のファイルを開きますか？`)) return;
  pendingEdits = [];
  pendingDataB64 = null;
  renderPendingBar();
  selectedKeys = new Set(); // keys are tree-specific; clipboardCommands intentionally persists across files
  renderSelectionBar();
  treeEl.innerHTML = `<div class="empty">${t('common.loading')}</div>`;
  detailEl.innerHTML = `<div class="empty">${t('editor.detailEmpty')}</div>`;
  const res = await fetch(`/api/parse?file=${encodeURIComponent(name)}`);
  const tree = await res.json();
  if (tree.error) {
    treeEl.innerHTML = `<div class="empty">${t('common.error')}: ${tree.error}</div>`;
    return;
  }
  currentTree = tree;
  currentFileName = name;
  renderTree(tree);
  pushRecent(name);
  highlightActiveFile(name);
  if (isMobile()) showPane('tree');
}

function highlightActiveFile(name) {
  document.querySelectorAll('.file-item.active').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('#fileListInner .file-item, #recentListInner .file-item').forEach(x => {
    const label = x.childNodes[0] ? x.childNodes[0].textContent : x.textContent;
    if (label === name) x.classList.add('active');
  });
}

// Preserves which <details> nodes were open across a renderTree() call by
// key (group/object/procedure path, stable regardless of edits elsewhere
// in the file) - added 2026-08-25 alongside staged editing, since
// re-rendering after every micro-edit was collapsing the whole tree and
// making multi-step edits tedious.
function captureTreeOpenState() {
  const open = new Set();
  treeEl.querySelectorAll('details[data-key]').forEach(d => {
    if (d.open) open.add(d.dataset.key);
  });
  return open;
}

function restoreTreeOpenState(openKeys) {
  treeEl.querySelectorAll('details[data-key]').forEach(d => {
    if (openKeys.has(d.dataset.key)) d.open = true;
  });
}

function renderTree(tree) {
  const openKeys = captureTreeOpenState();
  treeEl.innerHTML = '';
  const header = document.createElement('div');
  header.className = 'file-meta';
  header.style.marginBottom = '6px';
  header.style.display = 'flex';
  header.style.alignItems = 'center';
  header.style.flexWrap = 'wrap';
  header.style.gap = '8px';
  const headerText = document.createElement('span');
  headerText.style.minWidth = '0';
  headerText.style.wordBreak = 'break-all';
  const displayName = pendingEdits.length ? `${currentFileName} [未保存の変更 x${pendingEdits.length}]` : (tree.file || currentFileName);
  headerText.textContent = `${displayName} (${tree.file_size} bytes, ${tree.groups.length} groups)`;
  header.appendChild(headerText);
  // サーバー側の編集(python直叩き等、ビュアー外からの変更)がブラウザの
  // キャッシュ/古い状態に反映されず「変わっていないように見える」ことが
  // 実際にあったため(2026-09-29)、いつでも現在のファイルを再取得できる
  // 明示的な再読み込みボタンを追加。
  const reloadBtn = document.createElement('button');
  reloadBtn.className = 'secondary';
  reloadBtn.textContent = t('editor.reload');
  reloadBtn.style.flex = '0 0 auto';
  reloadBtn.title = t('editor.reloadTitle');
  reloadBtn.onclick = () => { if (currentFileName) selectFile(currentFileName); };
  header.appendChild(reloadBtn);
  treeEl.appendChild(header);

  for (const g of tree.groups) {
    const gDetails = document.createElement('details');
    gDetails.className = 'tree-node';
    gDetails.dataset.key = `g${g.index}`;
    const gSummary = document.createElement('summary');
    gSummary.innerHTML = `group ${g.index} <span class="tag-name">${escapeHtml(g.tag)}</span> <span class="file-meta">(${g.objects.length} obj)</span>`;
    gDetails.appendChild(gSummary);
    if (editMode) {
      // deliberately NOT placed inside <summary> - summary has
      // white-space:nowrap + text-overflow:ellipsis for long tag names
      // (see style.css), so an inline button there risks being clipped
      // or squeezed unpredictably on narrow (~375px) mobile screens.
      // A plain block row below the summary avoids that entirely.
      const addObjBtn = document.createElement('button');
      addObjBtn.className = 'secondary add-object-btn';
      addObjBtn.textContent = '＋ このgroupにオブジェクトを追加';
      addObjBtn.onclick = (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        showAddObjectForm({ targetGroupIdx: g.index });
        if (isMobile()) showPane('detail');
      };
      gDetails.appendChild(addObjBtn);
    }

    for (const o of g.objects) {
      const oDetails = document.createElement('details');
      oDetails.className = 'tree-node';
      oDetails.dataset.key = `g${g.index}-o${o.index}`;
      const hasText = objectHasText(o);
      const oSummary = document.createElement('summary');
      let placementHtml = '';
      if (o.npc_placement) {
        const np = o.npc_placement;
        const lowConf = np.confidence === 'low' ? '?' : '';
        placementHtml = ` <span class="npc-placement" title="model#・座標(pos_x/y/z)は実機検証済み。unk_type_flag等その他フィールドは仮説段階">model#${np.npc_model_id}${lowConf} @(${np.pos_x}, ${np.pos_z})</span>`;
      }
      oSummary.innerHTML = `obj ${o.index} <span class="tag-name">${escapeHtml(o.tag)}</span>` +
        (hasText ? ' <span style="color:#9fd18a">●</span>' : '') + placementHtml;
      oDetails.appendChild(oSummary);
      if (editMode) {
        // same rationale as the group-level add button above: kept out
        // of <summary> to avoid the nowrap/ellipsis clipping risk on
        // narrow mobile screens.
        const copyObjBtn = document.createElement('button');
        copyObjBtn.className = 'secondary add-object-btn';
        copyObjBtn.textContent = '📋 このオブジェクトをコピーして追加';
        copyObjBtn.onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          showAddObjectForm({
            targetGroupIdx: g.index,
            srcFile: currentFileName, srcGroupIdx: g.index, srcObjIdx: o.index,
          });
          if (isMobile()) showPane('detail');
        };
        oDetails.appendChild(copyObjBtn);

        const takeoverBtn = document.createElement('button');
        takeoverBtn.className = 'secondary add-object-btn';
        takeoverBtn.textContent = '🔁 このオブジェクトを別のオブジェクトで乗っ取る';
        takeoverBtn.onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          showAddObjectForm({
            overwrite: true,
            targetGroupIdx: g.index, targetObjIdx: o.index,
          });
          if (isMobile()) showPane('detail');
        };
        oDetails.appendChild(takeoverBtn);

        const deleteObjBtn = document.createElement('button');
        deleteObjBtn.className = 'secondary add-object-btn danger';
        deleteObjBtn.textContent = '🗑 このオブジェクトを削除';
        deleteObjBtn.onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          deleteScriptObject(g.index, o.index);
        };
        oDetails.appendChild(deleteObjBtn);
      }

      if (o.npc_placement) {
        const plDetails = document.createElement('details');
        plDetails.className = 'tree-node';
        const plSummary = document.createElement('summary');
        plSummary.innerHTML = `<span class="tag-name">配置情報(model_id/pos_x/pos_y/pos_zは確定・他は仮説)</span> <span class="file-meta">(${o.npc_placement.fields.length} fields)</span>`;
        plDetails.appendChild(plSummary);

        const plWrap = document.createElement('div');
        o.npc_placement.fields.forEach((f, fi) => {
          const fDiv = document.createElement('div');
          fDiv.className = 'cmd-item npc-field-item';
          const val = f.primary_type === 'f32' ? f.f32 : f.u32;
          fDiv.textContent = ` #${fi} +0x${f.offset.toString(16)} ${f.name} = ${val}`;
          fDiv.onclick = (ev) => {
            ev.stopPropagation();
            document.querySelectorAll('.cmd-item.selected').forEach(x => x.classList.remove('selected'));
            fDiv.classList.add('selected');
            g_forDetail = g;
            showObjectDetail(o, f);
            if (isMobile()) showPane('detail');
          };
          plWrap.appendChild(fDiv);
        });
        plDetails.appendChild(plWrap);
        oDetails.appendChild(plDetails);
      }

      for (const p of o.procedures) {
        if (!p.tag || p.commands.length === 0) continue;
        const pDetails = document.createElement('details');
        pDetails.className = 'tree-node';
        pDetails.dataset.key = `g${g.index}-o${o.index}-p${p.tag}`;
        const pSummary = document.createElement('summary');
        pSummary.innerHTML = `<span class="tag-name">${escapeHtml(p.tag)}</span> <span class="file-meta">(${p.commands.length} cmds)</span>`;
        pDetails.appendChild(pSummary);

        const cmdWrap = document.createElement('div');
        let prevIndent = null;

        if (editMode) cmdWrap.appendChild(makeInsertRow(g, o, p, 0));

        p.commands.forEach((c, ci) => {
          const cDiv = document.createElement('div');
          cDiv.className = 'cmd-item' + (c.text ? ' has-text' : '') + (c.name === 'IF_FLAG' || c.name === 'IF_TALKED_TO' || c.name === 'IF_KO_STATUS' || c.name === 'IF_IS_PARTY_MEMBER' ? ' is-if' : '') + (c.name === 'ADD_PARTY_MEMBER' || c.name === 'REMOVE_PARTY_MEMBER' || c.name === 'PARTY_SLOT_ACTIVATE' || c.name === 'CONFIRM_YESNO' || c.name === 'CHOICE_MENU' || c.name === 'IF_KO_STATUS' || c.name === 'IF_IS_PARTY_MEMBER' ? ' is-party' : '');
          const label = c.name === 'IF_FLAG'
            ? `if flag[t${c.flag_type}:${c.flag_id}] == ${c.flag_value}`
            : c.name === 'SET_FLAG'
            ? `flag[t${c.flag_type}:${c.flag_id}] = ${c.flag_value}`
            : c.name === 'IF_TALKED_TO'
            ? `if talked_to (variant=${c.variant})`
            : c.name === 'IF_KO_STATUS'
            ? `if char=${c.character_id} is ${c.branch_when === 'ko' ? '戦闘不能' : '生存'}`
            : c.name === 'IF_IS_PARTY_MEMBER'
            ? `if char=${c.character_id} is in party`
            : c.name === 'ENCOUNT_SET_FLAG'
            ? `⚔️ ENCOUNT_SET_FLAG flag=${c.flag_id} type=${c.enc_type} value=${c.value}`
            : c.name === 'ADD_PARTY_MEMBER'
            ? `ADD_PARTY_MEMBER char=${c.character_id}`
            : c.name === 'REMOVE_PARTY_MEMBER'
            ? `REMOVE_PARTY_MEMBER char=${c.character_id} (mode=${c.mode_param})`
            : c.name === 'PARTY_SLOT_ACTIVATE'
            ? `PARTY_SLOT_ACTIVATE slot=${c.slot}`
            : c.name === 'PARTY_SLOT_QUERY'
            ? `PARTY_SLOT_QUERY slot=${c.slot}`
            : c.name === 'CONFIRM_YESNO'
            ? `CONFIRM_YESNO ->flag(${c.var_type},${c.var_id}) cancel=${c.cancel_value}`
            : c.name === 'CHOICE_MENU'
            ? `CHOICE_MENU slots2-6=[${(c.slot_flags || []).join(',')}]`
            : c.name === 'SET_POSITION'
            ? `SET_POSITION x=${c.pos_x} y=${c.pos_y} z=${c.pos_z}`
            : c.name === 'OBJECT_TOGGLE'
            ? `OBJECT_TOGGLE obj${c.target_object_idx}`
            : c.name === 'MAP_WARP'
            ? `🚪 MAP_WARP → ${c.dst_map_name ? `${c.dst_map_name} (#${c.dst_map_id})` : `map#${c.dst_map_id}`} @(${c.pos_x}, ${c.pos_y}, ${c.pos_z})`
            : c.name === 'MSG' && (c.turn_to_player !== undefined || c.repeat_mode !== undefined)
            ? `${c.turn_to_player === undefined ? '' : (c.turn_to_player ? '🗣→' : '🗣─')}${c.repeat_mode === undefined ? '' : (c.repeat_mode === 'repeats_every_time' ? '🔁' : '1️⃣')} ${c.text ? previewLabel(c.text) : ''}`
            : (c.text ? previewLabel(c.text) : (c.name || c.opcode || ''));
          const indent = typeof c.indent === 'number' ? c.indent : null;
          if (indent !== null) {
            cDiv.classList.add('indent-item');
            cDiv.style.paddingLeft = `${6 + indent * 14}px`;
            cDiv.style.borderLeft = `2px solid ${indentColor(indent)}`;
            if (prevIndent !== null && indent > prevIndent) {
              cDiv.classList.add('indent-open');
            }
            const badge = document.createElement('span');
            badge.className = 'indent-badge';
            badge.style.color = indentColor(indent);
            badge.textContent = `L${indent}`;
            cDiv.appendChild(badge);
            prevIndent = indent;
          }
          const label2 = document.createElement('span');
          label2.textContent = ` #${ci} ${c.opcode || ''} ${label}`;
          cDiv.appendChild(label2);
          cDiv.dataset.cmdKey = `g${g.index}-o${o.index}-p${p.tag}-c${ci}`;
          cDiv.onclick = (ev) => {
            ev.stopPropagation();
            document.querySelectorAll('.cmd-item.selected').forEach(x => x.classList.remove('selected'));
            cDiv.classList.add('selected');
            g_forDetail = g;
            showCommandDetail(c, o, p, ci);
            if (isMobile()) showPane('detail');
          };

          if (editMode) {
            const row = document.createElement('div');
            row.className = 'cmd-row';
            const cmdKey = `g${g.index}-o${o.index}-p${p.tag}-c${ci}`;
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'cmd-select-checkbox';
            checkbox.checked = selectedKeys.has(cmdKey);
            checkbox.onclick = (ev) => {
              ev.stopPropagation();
              if (checkbox.checked) selectedKeys.add(cmdKey);
              else selectedKeys.delete(cmdKey);
              renderSelectionBar();
            };
            row.appendChild(checkbox);
            row.appendChild(cDiv);
            const editBtn = document.createElement('button');
            editBtn.className = 'cmd-edit-btn';
            editBtn.textContent = '✎';
            editBtn.title = 'このコマンドを編集';
            editBtn.onclick = (ev) => {
              ev.stopPropagation();
              openCommandEditor(g, o, p, ci, c);
            };
            const delBtn = document.createElement('button');
            delBtn.className = 'cmd-del-btn';
            delBtn.textContent = '🗑';
            delBtn.title = 'このコマンドを削除';
            delBtn.onclick = (ev) => {
              ev.stopPropagation();
              deleteCommand(g, o, p, ci, c);
            };
            row.appendChild(editBtn);
            row.appendChild(delBtn);
            cmdWrap.appendChild(row);
            cmdWrap.appendChild(makeInsertRow(g, o, p, ci + 1));
          } else {
            cmdWrap.appendChild(cDiv);
          }
        });
        pDetails.appendChild(cmdWrap);
        oDetails.appendChild(pDetails);
      }
      gDetails.appendChild(oDetails);
    }
    treeEl.appendChild(gDetails);
  }
  restoreTreeOpenState(openKeys);
}

// block1 stores one nesting-depth byte per command (confirmed: this
// handler format encodes an if/elseif cascade - see script/README.md).
// Cycle a fixed color palette by depth so nested branches are visually
// distinguishable without needing many unique colors.
const INDENT_COLORS = ['#6ab0f3', '#9fd18a', '#e0a05a', '#d97ad9', '#f0d264', '#7ad9c9', '#e88080', '#a0a0e0'];
function indentColor(depth) {
  return INDENT_COLORS[depth % INDENT_COLORS.length];
}

function objectHasText(o) {
  return o.procedures.some(p => p.commands.some(c => c.text));
}

// NPC placement editing (added 2026-08-27): the 48-byte area is a fixed
// size, fixed-offset struct that isn't part of any block1/2/3 ref-table
// (see webapp/server.py:edit_npc_placement_field's docstring), so
// editing it in place never changes file size and needs none of the
// splice/offset-propagation machinery the command editor uses - just a
// plain 4-byte overwrite per field. Editing UI only appears when
// editMode is on, mirroring the command tree's edit affordances.
function showObjectDetail(o, focusField) {
  detailEl.innerHTML = '';

  const header = document.createElement('div');
  header.textContent = `object ${o.index} (${o.tag})  offset=${o.offset}  size=${o.size}`;
  detailEl.appendChild(header);

  const heading2 = document.createElement('div');
  heading2.style.marginTop = '8px';
  heading2.style.marginBottom = '6px';
  heading2.textContent = 'NPC配置情報 (scriptobjectヘッダ直後の0x30byte領域、全12フィールド。npc_model_id/pos_x/pos_y/pos_zは実機検証済み・他は仮説段階):';
  detailEl.appendChild(heading2);

  const np = o.npc_placement;
  const groupIdx = g_forDetail ? g_forDetail.index : null;

  const fieldsWrap = document.createElement('div');
  np.fields.forEach((f, fi) => {
    const row = document.createElement('div');
    row.className = 'cmd-block';
    row.style.marginBottom = '6px';
    if (focusField && f.offset === focusField.offset) row.style.borderColor = 'var(--accent)';

    const label = document.createElement('div');
    label.innerHTML = `#${fi} +0x${f.offset.toString(16).padStart(2, '0')} <b>${escapeHtml(f.name)}</b> — u32=${f.u32}  i32=${f.i32}  f32=${f.f32}  hex=${escapeHtml(f.hex)}`;
    row.appendChild(label);

    const note = document.createElement('div');
    note.className = 'file-meta';
    note.style.marginTop = '2px';
    note.textContent = f.note;
    row.appendChild(note);

    if (editMode && groupIdx !== null) {
      const editRow = document.createElement('div');
      editRow.style.marginTop = '6px';
      editRow.style.display = 'flex';
      editRow.style.gap = '6px';
      editRow.style.flexWrap = 'wrap';

      const typeSelect = document.createElement('select');
      typeSelect.className = 'param-type-select';
      ['u32', 'i32', 'f32'].forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        if (t === f.primary_type) opt.selected = true;
        typeSelect.appendChild(opt);
      });

      const valueInput = document.createElement('input');
      valueInput.type = 'text';
      valueInput.className = 'param-value-input';
      const syncInputValue = () => { valueInput.value = f[typeSelect.value]; };
      syncInputValue();
      typeSelect.addEventListener('change', syncInputValue);

      const saveBtn = document.createElement('button');
      saveBtn.className = 'secondary';
      saveBtn.textContent = '保存';

      const msgEl = document.createElement('div');
      msgEl.className = 'edit-msg';

      saveBtn.onclick = () => {
        saveNpcField(groupIdx, o.index, f.offset, typeSelect.value, valueInput.value, msgEl);
      };

      editRow.appendChild(typeSelect);
      editRow.appendChild(valueInput);
      editRow.appendChild(saveBtn);
      row.appendChild(editRow);
      row.appendChild(msgEl);
    }

    fieldsWrap.appendChild(row);
  });
  detailEl.appendChild(fieldsWrap);

  const footer = document.createElement('div');
  footer.style.marginTop = '8px';
  footer.style.whiteSpace = 'pre-wrap';
  footer.textContent = [
    `confidence: ${np.confidence}` + (np.confidence === 'low' ? '   (pos_x/y/zが全て0 - 物理配置を持たない別種のオブジェクトの可能性。フィールドの意味がずれているかも)' : ''),
    '',
    '【確定 2026-08-23】npc_model_id(offset+4)は実機検証済み: group3/obj7(シスター)の',
    'この値を182→2(マリベルのキャラID)に書き換えてCIA再ビルド・実機テストしたところ、',
    '見た目が実際にマリベルのモデルに変化した。表示モデル/アクターを選ぶフィールドと確定。',
    '',
    '【確定 2026-08-27】pos_x/pos_y/pos_z(offset+12/16/20)も実機検証済み: ビュアーの',
    'この編集機能で各値を書き換えてCIA再ビルド・実機テストしたところ、対象NPCの',
    '表示位置(X/Y/Z座標)がそれぞれ実際に変化した。マップ座標フィールドと確定。',
    '',
    '根拠(unk_instance_id/unk_type_flag等その他フィールド、まだ仮説): m01nk1f1.bin内で、',
    '同じ(unk_instance_id, npc_model_id)の組が複数のグループ(時間帯/天候違い等の',
    'バリエーションと推測)にまたがって出現し、その都度pos_x/pos_zだけが異なっていた',
    '（同一NPCが場面ごとに立ち位置を変えて再配置されているのと整合する）。詳細は',
    'docs/party_add_remove_command_investigation.md参照。',
  ].join('\n');
  detailEl.appendChild(footer);
}

// "スクリプトオブジェクトを追加" (added 2026-08-29 per user request, incl.
// mid-request follow-up "オブジェクトをコピーする機能が欲しい"): this
// does NOT synthesize a new object's internal layout (proc-ref table /
// NPC-placement metadata block relationship) from scratch - it always
// clones the full byte range of an EXISTING object somewhere in the ROM
// (see script/splice_procedure.py's splice_object()/insert_container_child()
// and docs/script_object_insertion.md) and only lets the user override
// the tag and a few known NPC-placement fields on the copy. This is both
// the safe path (never invents unverified structure) and directly
// implements "copy an object", which covers the common case of
// duplicating an object within its own group.
function showAddObjectForm(defaults) {
  defaults = defaults || {};
  const overwriteMode = !!defaults.overwrite;
  detailEl.innerHTML = '';

  const header = document.createElement('div');
  const updateHeader = (dstName) => {
    header.textContent = overwriteMode
      ? `オブジェクトを乗っ取る(既存を上書き) — 対象: ${dstName}`
      : `オブジェクトを追加(コピー) — 追加先: ${dstName}`;
  };
  updateHeader(defaults.dstFile || currentFileName);
  detailEl.appendChild(header);

  const note = document.createElement('div');
  note.className = 'file-meta';
  note.style.marginTop = '4px';
  note.style.marginBottom = '8px';
  note.textContent = overwriteMode
    ? '既存の(ゲーム側からすでに呼び出されている)オブジェクトの中身を、別のオブジェクトの複製で丸ごと上書きします。追加(新規object)がゲームに反映されなかったため、既に有効なobjectインデックスを乗っ取る方式を試すためのものです(docs/script_object_insertion.md参照)。元のオブジェクトの内容は失われるので必ずバックアップから復元できることを確認してください。'
    : '既存のオブジェクトを丸ごとコピーし、指定groupの末尾に新規オブジェクトとして追加します(内部構造は複製元のものをそのまま使うため安全)。tag名・配置情報の一部は上書きできます。ゲーム側から実際に呼び出されるかは未検証です。';
  detailEl.appendChild(note);

  const form = document.createElement('div');
  form.className = 'edit-form';

  function labeledInput(labelText, inputEl) {
    const wrap = document.createElement('div');
    const label = document.createElement('label');
    label.textContent = labelText;
    wrap.appendChild(label);
    wrap.appendChild(inputEl);
    return wrap;
  }

  // 貼り付け先(追加先)ファイル。従来はcurrentFileName固定で選べなかったが、
  // サーバ側 copy_script_object() は元々任意の dst_filename を受け付けるので
  // (ファイル跨ぎコピー対応済み)、フロントに選択欄を出すだけでよい。
  const dstFileInput = document.createElement('input');
  dstFileInput.type = 'text';
  dstFileInput.setAttribute('list', 'add-object-dst-file-list');
  dstFileInput.value = defaults.dstFile || currentFileName;
  const dstDataList = document.createElement('datalist');
  dstDataList.id = 'add-object-dst-file-list';
  allFiles.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.name;
    dstDataList.appendChild(opt);
  });
  dstFileInput.addEventListener('input', () => updateHeader(dstFileInput.value || currentFileName));
  form.appendChild(labeledInput(
    overwriteMode ? '乗っ取り先ファイル(空欄なら現在のファイル)' : '貼り付け先ファイル(空欄なら現在のファイル)',
    dstFileInput));
  form.appendChild(dstDataList);

  const targetGroupInput = document.createElement('input');
  targetGroupInput.type = 'number';
  targetGroupInput.value = defaults.targetGroupIdx ?? 0;
  form.appendChild(labeledInput(overwriteMode ? '上書き対象 group index' : '追加先 group index', targetGroupInput));

  let targetObjInput = null;
  if (overwriteMode) {
    targetObjInput = document.createElement('input');
    targetObjInput.type = 'number';
    targetObjInput.value = defaults.targetObjIdx ?? '';
    form.appendChild(labeledInput('上書き対象 object index(この内容が失われます)', targetObjInput));
  }

  let atIndexInput = null;
  if (!overwriteMode) {
    atIndexInput = document.createElement('input');
    atIndexInput.type = 'number';
    atIndexInput.placeholder = '空欄=末尾に追加';
    form.appendChild(labeledInput('挿入位置 index(空欄なら末尾に追加。指定するとそれ以降の既存objectは+1される)', atIndexInput));
  }

  const srcFileInput = document.createElement('input');
  srcFileInput.type = 'text';
  srcFileInput.setAttribute('list', 'add-object-src-file-list');
  srcFileInput.value = defaults.srcFile || currentFileName;
  const dataList = document.createElement('datalist');
  dataList.id = 'add-object-src-file-list';
  allFiles.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.name;
    dataList.appendChild(opt);
  });
  form.appendChild(labeledInput('コピー元ファイル(空欄なら現在のファイル)', srcFileInput));
  form.appendChild(dataList);

  const srcRow = document.createElement('div');
  srcRow.className = 'form-row';
  const srcGroupInput = document.createElement('input');
  srcGroupInput.type = 'number';
  srcGroupInput.value = defaults.srcGroupIdx ?? '';
  const srcObjInput = document.createElement('input');
  srcObjInput.type = 'number';
  srcObjInput.value = defaults.srcObjIdx ?? '';
  srcRow.appendChild(labeledInput('コピー元 group index', srcGroupInput));
  srcRow.appendChild(labeledInput('コピー元 object index', srcObjInput));
  form.appendChild(srcRow);

  const newTagInput = document.createElement('input');
  newTagInput.type = 'text';
  newTagInput.maxLength = 16;
  newTagInput.placeholder = '空欄ならコピー元のtagのまま';
  form.appendChild(labeledInput('新しいtag名(最大16文字、省略可)', newTagInput));

  const placementHeading = document.createElement('div');
  placementHeading.className = 'file-meta';
  placementHeading.style.marginTop = '4px';
  placementHeading.textContent = '配置情報の上書き(空欄なら変更しない・model_id/pos_x/y/zのみ実機確定済み):';
  form.appendChild(placementHeading);

  const modelIdInput = document.createElement('input');
  modelIdInput.type = 'number';
  modelIdInput.placeholder = '空欄=変更なし';
  form.appendChild(labeledInput('npc_model_id (u32, +0x04)', modelIdInput));

  const posRow = document.createElement('div');
  posRow.className = 'form-row';
  const posXInput = document.createElement('input');
  posXInput.type = 'number';
  posXInput.step = 'any';
  posXInput.placeholder = '空欄=変更なし';
  const posYInput = document.createElement('input');
  posYInput.type = 'number';
  posYInput.step = 'any';
  posYInput.placeholder = '空欄=変更なし';
  const posZInput = document.createElement('input');
  posZInput.type = 'number';
  posZInput.step = 'any';
  posZInput.placeholder = '空欄=変更なし';
  posRow.appendChild(labeledInput('pos_x (f32, +0x0c)', posXInput));
  posRow.appendChild(labeledInput('pos_y (f32, +0x10)', posYInput));
  posRow.appendChild(labeledInput('pos_z (f32, +0x14)', posZInput));
  form.appendChild(posRow);

  const commentInput = document.createElement('input');
  commentInput.type = 'text';
  commentInput.placeholder = '何のために追加したか...';
  form.appendChild(labeledInput('コメント', commentInput));

  const actions = document.createElement('div');
  actions.className = 'form-actions';
  const addBtn = document.createElement('button');
  if (overwriteMode) addBtn.className = 'danger';
  addBtn.textContent = overwriteMode ? '乗っ取る(既存を上書き)' : '追加する';
  const msgEl = document.createElement('div');
  msgEl.className = 'edit-msg';

  addBtn.onclick = async () => {
    if (srcGroupInput.value === '' || srcObjInput.value === '') {
      msgEl.textContent = 'コピー元のgroup/object indexを指定してください';
      msgEl.className = 'edit-msg error';
      return;
    }
    if (overwriteMode && targetObjInput.value === '') {
      msgEl.textContent = '上書き対象のobject indexを指定してください';
      msgEl.className = 'edit-msg error';
      return;
    }
    if (overwriteMode && !confirm(`group${targetGroupInput.value}/obj${targetObjInput.value}の内容を失って上書きします。よろしいですか？`)) return;

    const fieldOverrides = {};
    if (modelIdInput.value !== '') fieldOverrides[4] = { type: 'u32', value: Number(modelIdInput.value) };
    if (posXInput.value !== '') fieldOverrides[12] = { type: 'f32', value: Number(posXInput.value) };
    if (posYInput.value !== '') fieldOverrides[16] = { type: 'f32', value: Number(posYInput.value) };
    if (posZInput.value !== '') fieldOverrides[20] = { type: 'f32', value: Number(posZInput.value) };

    const dstFile = dstFileInput.value || currentFileName;

    msgEl.textContent = overwriteMode ? '上書き中...' : '追加中...';
    msgEl.className = 'edit-msg';
    try {
      const body = {
        dst_file: dstFile,
        target_group_idx: Number(targetGroupInput.value),
        src_file: srcFileInput.value || currentFileName,
        src_group_idx: Number(srcGroupInput.value),
        src_obj_idx: Number(srcObjInput.value),
        new_tag: newTagInput.value || null,
        field_overrides: Object.keys(fieldOverrides).length ? fieldOverrides : null,
        comment: commentInput.value,
      };
      if (overwriteMode) body.target_obj_idx = Number(targetObjInput.value);
      if (!overwriteMode && atIndexInput.value !== '') body.at_index = Number(atIndexInput.value);
      const res = await fetch(overwriteMode ? '/api/script/object/replace' : '/api/script/object/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!data.ok) {
        msgEl.textContent = `${t('common.error')}: ${data.error || 'unknown'}` + (data.anomalies ? `\n${JSON.stringify(data.anomalies)}` : '');
        msgEl.className = 'edit-msg error';
        return;
      }
      const dstLabel = dstFile === currentFileName ? '' : ` [${dstFile}]`;
      msgEl.textContent = overwriteMode
        ? `乗っ取りました (group${targetGroupInput.value}/obj${targetObjInput.value})${dstLabel}`
        : `追加しました (group${targetGroupInput.value}/obj${data.new_obj_idx})${dstLabel}`;
      msgEl.className = 'edit-msg success';
      // 別ファイルに貼り付けた場合はそのファイルを開き直して結果を見せる。
      // 同一ファイルなら従来どおりツリーを再読込するだけ。
      if (dstFile !== currentFileName) {
        await selectFile(dstFile);
      } else {
        await reloadCurrentFile();
      }
    } catch (err) {
      msgEl.textContent = `${t('common.error')}: ${err.message || err}`;
      msgEl.className = 'edit-msg error';
    }
  };

  actions.appendChild(addBtn);
  form.appendChild(actions);
  form.appendChild(msgEl);
  detailEl.appendChild(form);
}

async function deleteScriptObject(groupIdx, objIdx) {
  if (!confirm(`group${groupIdx}/obj${objIdx}を削除します。この操作は元に戻せません(履歴からの復元は可能)。よろしいですか？`)) return;
  const comment = prompt('削除理由(任意、履歴に記録されます):', '') || '';
  try {
    const res = await fetch('/api/script/object/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dst_file: currentFileName,
        target_group_idx: groupIdx,
        target_obj_idx: objIdx,
        comment,
      }),
    });
    const data = await res.json();
    if (!data.ok) {
      alert(`削除に失敗しました: ${data.error || 'unknown'}` + (data.anomalies ? `\n${JSON.stringify(data.anomalies)}` : ''));
      return;
    }
    await reloadCurrentFile();
  } catch (err) {
    alert(`削除に失敗しました: ${err.message || err}`);
  }
}

async function saveNpcField(groupIdx, objIdx, fieldOffset, valueType, rawValue, msgEl) {
  msgEl.textContent = '保存中...';
  msgEl.className = 'edit-msg';
  try {
    const res = await fetch('/api/script/npc_field/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file: currentFileName,
        group_idx: groupIdx,
        obj_idx: objIdx,
        field_offset: fieldOffset,
        value_type: valueType,
        value: rawValue,
        comment: `配置情報 +0x${fieldOffset.toString(16)} を編集`,
      }),
    });
    const data = await res.json();
    if (!data.ok) {
      msgEl.textContent = `${t('common.error')}: ${data.error || 'unknown'}`;
      msgEl.className = 'edit-msg error';
      return;
    }
    await reloadCurrentFile();
    // showObjectDetail() below rebuilds the whole detail pane from
    // scratch (including a fresh msgEl per field), so there's nothing
    // left to write a success message into on the old msgEl - the
    // updated value now showing in the field row IS the confirmation.
    const g = currentTree.groups[groupIdx];
    const o = g.objects[objIdx];
    g_forDetail = g;
    const f = (o.npc_placement && o.npc_placement.fields.find(fl => fl.offset === fieldOffset)) || null;
    showObjectDetail(o, f);
  } catch (e) {
    msgEl.textContent = `${t('common.error')}: ${e.message || e}`;
    msgEl.className = 'edit-msg error';
  }
}

function showCommandDetail(c, o, p, ci) {
  const lines = [];
  lines.push(`object ${o.index} (${o.tag})  procedure ${p.tag}  command #${ci}`);
  if (typeof c.indent === 'number') {
    lines.push(`indent (if/elseif nesting depth): ${c.indent}`);
  }
  lines.push(`rel_start=${c.rel_start}  rel_end=${c.rel_end}  size=${c.size}`);
  lines.push(`opcode: ${c.opcode || ''}   name: ${c.name || ''}`);
  if (c.params) lines.push(`params: [${c.params.join(', ')}]`);
  if (c.msgid !== undefined) lines.push(`msgID: ${c.msgid}   count: ${c.count}`);
  if (c.count_suspicious) {
    lines.push(`⚠ countの値が不自然に大きい（ページ数ではなく別の意味のパラメータの可能性）ため、`);
    lines.push(`  テキスト解決をスキップしています（確定 2026-10-04、全ROM走査で809件発見）。`);
  }
  if (c.style !== undefined) lines.push(`style: ${c.style}`);
  if (c.name === 'MSG' && c.turn_to_player !== undefined) {
    lines.push(`turn_to_player: ${c.turn_to_player} (確定 2026-08-28: opcode下位byte 0x09=プレイヤーの方を向く / 0x07=向かない。`);
    lines.push(`  それ以外は同一のメッセージ表示コマンド。0x0a/0x0b/0x0d/0x0eに同種の派生があるかは未調査)`);
  }
  if (c.name === 'MSG' && c.repeat_mode !== undefined) {
    lines.push(`repeat_mode: ${c.repeat_mode} (このコマンド自身のopcode上位16bitの生値)`);
    lines.push(`  【2026-10-03訂正】この値は「このメッセージ単体」の再生頻度ではない。`);
    lines.push(`  実機検証の結果、if/elseifブロック内で物理的に最後に置かれたコマンドの`);
    lines.push(`  上位16bitだけが意味を持ち、そのブロックに属する兄弟コマンド全員の完了状態を`);
    lines.push(`  まとめてリセットするかどうかを決めることが分かった: ブロック最後のコマンドが`);
    lines.push(`  0x0003(repeats_every_time)ならブロック全体が毎回最初から再実行され(途中の`);
    lines.push(`  0x0001コマンドも含めて)、最後が0x0001(once_until_scene_change)ならブロック`);
    lines.push(`  全体が1度きりで二度と実行されない(途中にあった0x0003コマンドも道連れになる)。`);
    lines.push(`  このコマンドがブロックの最後かどうかはビュアー側では判定していないため、`);
    lines.push(`  この値を「このメッセージが毎回出る/出ない」の確定情報として読まないこと。`);
    lines.push(`  全ROM検証では、repeatsの99.5%はIF_TALKED_TO分岐の中、onceの100%近く`);
    lines.push(`  (16261/16263)はIF_TALKED_TO分岐の外、という設計傾向が確認されている。`);
  }
  if (c.name === 'IF_FLAG' || c.name === 'SET_FLAG') {
    const verb = c.name === 'IF_FLAG' ? 'if' : 'write';
    lines.push(`${verb} flag[type=${c.flag_type}][${c.flag_id}] == ${c.flag_value}`);
    lines.push(`  【確定 2026-09-27】flag_type = GameFlag::check/set(this, type, flag_id)の"type"引数。`);
    lines.push(`  GameFlagオブジェクト内、3種類の独立したビット配列を選び分ける(r2直接デコンパイルで確認):`);
    lines.push(`    type=0 -> this+0x218 (オンディスク file 0x20+id//8。既存のFLAGS_REGION_BASEと一致)`);
    lines.push(`    type=1 -> this+0x418 (オンディスク file 0x220+id//8。type0とは別バイト列！`);
    lines.push(`              旧来「type違いを無視してtype0と同じ0x20+id//8で読み書き」していた場合は誤り)`);
    lines.push(`    type=2 -> this+0x008 (GameFlag::serializeがコピーする範囲(this+0x208〜+0x458)の`);
    lines.push(`              外側にあるため、セーブに一切永続化されない。起動のたびに0クリアされる)`);
    lines.push(`  observed idiom (IF_FLAG): value=0 checks "not yet done", value=1 marks "done" after the branch runs`);
    lines.push(`  詳細: docs/costa_npc_visibility_investigation.md`);
  }
  if (c.name === 'IF_TALKED_TO') {
    lines.push(`IF_TALKED_TO (確定 2026-08-28): 話しかけるとtrueになる分岐条件。variant=${c.variant}`);
    lines.push(`  全ROM走査で9044件ヒット、全て'execute'プロシージャの先頭コマンド(#0)として出現 -`);
    lines.push(`  NPCの会話ハンドラのほぼ普遍的な入口ゲート。variantは0が8548件・1が258件・2が238件`);
    lines.push(`  (0以外の意味は未確認 - 話しかける/調べる/押す等インタラクション種別の可能性)。`);
    lines.push(`  IF_FLAGと同じ if/elseif ネスト深さの慣習: このコマンドの直後、indent+1の位置に`);
    lines.push(`  実際に話しかけたときに表示されるコマンド(MSG等)が続く。`);
  }
  if (c.name === 'IF_KO_STATUS') {
    lines.push(`IF_KO_STATUS (確定 2026-09-29、ユーザー確認): character_id=${c.character_id}  branch_when=${c.branch_when}`);
    lines.push(`  params=[character_id, mode]。mode=1で「戦闘不能のとき」に分岐、mode=0で「生存しているとき」に分岐。`);
    lines.push(`  旧称"op_00000070"。かつては会話中の[N,0]/[N,1]ペア出現から「アクターウィンドウの`);
    lines.push(`  開閉ブラケット」と推測していたが誤りで、実際は同じキャラの生死をmode違いで`);
    lines.push(`  2回チェックしているだけだった(docs/party_add_remove_command_investigation.md等参照)。`);
  }
  if (c.name === 'IF_IS_PARTY_MEMBER') {
    lines.push(`IF_IS_PARTY_MEMBER (確定 2026-09-29、script::cmdIsPartyMember(file offset 0x219c44)のr2解析で確定): character_id=${c.character_id}`);
    lines.push(`  中身は生存パーティ配列を線形探索し、character_idと一致する要素があれば分岐成立(true)。modeパラメータは無い(常に「いるか」の1択、`);
    lines.push(`  「いないとき」に分岐したい場合はSET_FLAGで一時flagに1を立てておき、成立時に0へ戻す→その一時flagをIF_FLAGで見る、という定型パターンで代用する)。`);
    lines.push(`  旧称"op_0000006f"。過去に「実行すると対象キャラの表示状態に副作用(消失)」と誤解されていたが、実際はIF_FLAGと同じ`);
    lines.push(`  if/elseifネスト深さの条件分岐オペコードであり、対応するネスト先コマンド無しに単独アクションとして誤挿入したことによる構造崩れが原因だった。`);
  }
  if (c.name === 'SET_MAP_OBJ_NUMBER') {
    lines.push(`SET_MAP_OBJ_NUMBER (訂正 2026-10-04): 以前はSTART_BATTLE(script::cmdEncountSetFlagを呼ぶ)と誤って記録していたが、`);
    lines.push(`  実際のハンドラ呼び先はscript::cmdSetMapObjNumber(file offset 0x21cc04)で、戦闘とは無関係と見られる。`);
    lines.push(`  本当の役割は未調査。詳細: docs/battle_start_opcode_investigation.md「【重大な訂正】」節`);
  }
  if (c.name === 'ENCOUNT_SET_FLAG') {
    lines.push(`ENCOUNT_SET_FLAG (確定 2026-10-04、script::cmdEncountSetFlag/file offset 0x21b3c0のr2解析で確定): flag_id=${c.flag_id} type=${c.enc_type} value=${c.value}`);
    lines.push(`  以前はopcode 0x1bがこの関数を呼ぶと誤って記録していたが、実際に呼んでいるのはopcode 0x24(このコマンド)だった。`);
    lines.push(`  params=[1(未使用), flag_id, type, value]。flag_id(観測値164〜268)はエンカウント状態構造体のフィールドに`);
    lines.push(`  格納され、type(0/1/2)とvalue(観測値5〜2091、おそらくモンスターグループID相当)はfcn.00126140`);
    lines.push(`  (エンカウントレコード操作関数)へ渡される。その直後に無条件(固定引数r0=0xf,r1=0)でPartUtility::startBattle`);
    lines.push(`  相当の関数を呼ぶが、引数が固定なため「どの戦闘が始まるか」はfcn.00126140側の登録内容に依存すると見られる。`);
    lines.push(`  詳細: docs/battle_start_opcode_investigation.md`);
  }
  if (c.name === 'ADD_PARTY_MEMBER') {
    lines.push(`ADD_PARTY_MEMBER: character_id=${c.character_id}  mode_param=${c.mode_param}`);
    lines.push(`  confirmed on real hardware to add this character to the save's Party array.`);
    lines.push(`  does NOT by itself populate the Charactors (stats) slot - character won't`);
    lines.push(`  show on the status screen / battle without further investigation (see docs/).`);
    lines.push(`  【確定 2026-09-23、Ghidra解析】mode_param(旧称"予備フラグ")は動作モードで、`);
    lines.push(`  0=add / 非0=remove。CmdPartyJoin::initializeがこの値でPlayerManager::`);
    lines.push(`  addPlayer と PlayerManager::delPlayerIndex(内部でPlayerParty::delMemberを`);
    lines.push(`  呼びParty配列から実際に削除・詰め直す)を分岐している。`);
  }
  if (c.name === 'REMOVE_PARTY_MEMBER') {
    lines.push(`REMOVE_PARTY_MEMBER: character_id=${c.character_id}  mode_param=${c.mode_param}`);
    lines.push(`  【2026-09-23、Ghidra解析で確定、実機未検証】mode_paramが非0のため、ADD_PARTY_MEMBER`);
    lines.push(`  と同じopcodeがPlayerManager::delPlayerIndex経由でこのキャラをParty配列から`);
    lines.push(`  削除する(内部でPlayerParty::delMemberが隙間を前方の非0要素で詰める)。`);
    lines.push(`  docs/party_add_remove_command_investigation.md参照。`);
  }
  if (c.name === 'FANFARE_MSG') {
    lines.push(`FANFARE_MSG (旧称JOIN_BANNER): style=${c.style}  style_hint=${c.style_hint || ''}`);
    lines.push(`  【2026-09-30訂正】当初"仲間になった専用バナー"と呼んでいたが、全ROM325件の`);
    lines.push(`  実テキストを確認したところ、style=36(52件、全て「〇〇が仲間にくわわった！」)は`);
    lines.push(`  用途の一部に過ぎず、style=44/45(270件超)は「{I_NAME}を手に入れた」「〇〇を`);
    lines.push(`  見つけた」等のアイテム入手・イベント演出テキストで占められていた。`);
    lines.push(`  すなわちこれは効果音(ジングル)付きの汎用「特殊演出メッセージ」コマンドで、`);
    lines.push(`  仲間加入はそのうちの一用途(style=36)にすぎない。style=46は観測1件のみ未確定。`);
    lines.push(`  msgID/countの意味は通常のMSGと同じ。ExeFS側の実装クラスは未確定`);
    lines.push(`  (docs/party_add_remove_command_investigation.md参照 - 名前が似ている`);
    lines.push(`  CmdPartyJoinDisplayを候補に調べたが辻褄が合わず却下、真のハンドラは不明のまま)。`);
  }
  if (c.name === 'PARTY_SLOT_ACTIVATE') {
    lines.push(`PARTY_SLOT_ACTIVATE: slot=${c.slot} (1-based, suspected)`);
    lines.push(`  seen after FANFARE_MSG's party-join usage (style=36, formerly called`);
    lines.push(`  JOIN_BANNER) in every sampled "character rejoins" scene.`);
    lines.push(`  role not fully confirmed - did not alone fix status-screen visibility.`);
  }
  if (c.name === 'PARTY_SLOT_QUERY') {
    lines.push(`PARTY_SLOT_QUERY: slot=${c.slot} (tentative name)`);
    lines.push(`  occurs far more often than PARTY_SLOT_ACTIVATE per scene - looks like a`);
    lines.push(`  read/branch-condition check rather than a state-changing write.`);
  }
  if (c.name === 'CONFIRM_YESNO') {
    lines.push(`CONFIRM_YESNO: var_type=${c.var_type} var_id=${c.var_id} cancel_value=${c.cancel_value} (tentative name/params, unconfirmed)`);
    lines.push(`  hypothesis (user, 2026-08-23): pops a yes/no prompt, writes the result into`);
    lines.push(`  flag(var_type, var_id) - matches the (type,id) pair read by IF_FLAG right after`);
    lines.push(`  it in every sampled occurrence. cancel_value is written if the player cancels.`);
    lines.push(`  Under investigation as a possible cause of the transplanted-scene stall (see`);
    lines.push(`  docs/party_add_remove_command_investigation.md) - a real UI prompt may not`);
    lines.push(`  resolve correctly when the scene is transplanted out of its original context.`);
  }
  if (c.name === 'SET_POSITION') {
    lines.push(`SET_POSITION (ユーザー仮説、2026-08-27・未確定): params[0..2]をfloatとして解釈`);
    lines.push(`  x=${c.pos_x}  y=${c.pos_y}  z=${c.pos_z}`);
    lines.push(`  NPC配置情報テーブルのpos_x/pos_y/pos_z(実機検証済み・上記docs参照)と同じ形。`);
    lines.push(`  こちらはスクリプト実行時にアクターを動的に移動させるコマンドと推測。まだ実機未検証。`);
  }
  if (c.name === 'OBJECT_TOGGLE') {
    lines.push(`OBJECT_TOGGLE (確定 2026-08-30、ユーザーが実機で発見): 同じgroup内のobj${c.target_object_idx}の表示on/offを切り替える`);
    lines.push(`  params[0]=${c.params ? c.params[0] : '?'} -> target object index = params[0]+1 = ${c.target_object_idx}`);
    lines.push(`  docs/script_object_insertion.md「乗っ取りでもobj9だけ表示されない」現象の原因。`);
    lines.push(`  m01nk1f1.bin group3のobj0のinitializeにこの命令(param=8)があり、これがobj9の表示を制御していた。`);
    lines.push(`  実機で0x10005 8を実行するとobj9が表示されることを確認済み。on/offどちら向きの操作か(トグルか常時onか)は未確定。`);
  }
  if (c.name === 'MAP_WARP') {
    lines.push(`MAP_WARP / マップ移動(ワープ) (有力な仮説 2026-08-31・実機未検証、script/scan_opcode_0x1001f.py):`);
    lines.push(`  移動先フロアID param[0]=${c.dst_map_id}${c.dst_map_name ? ` → ${c.dst_map_name}` : ' (dq7_floor_list.datに該当なし)'}`);
    lines.push(`  移動先座標 (x, y, z) = (${c.pos_x}, ${c.pos_y}, ${c.pos_z})  ※param[1..3]をf32解釈`);
    if (c.facing !== undefined) lines.push(`  param[4]=${c.facing} - 移動後の向き(4方位 0..3)と推測、未確定`);
    if (c.warp_flag5 !== undefined) lines.push(`  param[5]=${c.warp_flag5} - 0/1のフラグ、意味未確定(フェード有無/カメラ引き継ぎ等の候補)`);
    lines.push(`  フロアID→マップコードの対応は LEVELDATA/dq7_floor_list.dat のレコード+0x04(u16)。`);
    lines.push(`  例: 407→m01nm2f2, 2→c01nf1, 301→h01nout1, 5161→wld_n25a(ワールドマップタイル)。`);
    lines.push(`  座標の並び・スケールは SET_POSITION / NPC配置テーブルの pos_x/pos_y/pos_z と同じ。`);
    lines.push(`  全SCRIPT走査で1121件、全て'execute'内。直前は 0x00010004(フェード系?)が最多。`);
  }
  if (c.name === 'CHOICE_MENU') {
    lines.push(`CHOICE_MENU (full-ROM scan 2026-08-25, script/scan_opcode_0x100c5.py;`);
    lines.push(`  exe-side investigation 2026-09-23, docs/opcode_0x100c5_exefs_investigation.md`);
    lines.push(`  - NOTE: the opcode<->handler link itself is NOT confirmed, see docs "重要な訂正"):`);
    lines.push(`  msgID=${c.msgid}  count=${c.count} (likely: consecutive message pages starting at`);
    lines.push(`  msgID, same convention as other MSG-family opcodes. Always 1 in all 20 real`);
    lines.push(`  occurrences, i.e. a single-page prompt.)`);
    lines.push(`  raw params[2..6]=[${(c.slot_flags || []).join(', ')}]`);
    lines.push(`  These are NOT indexed by formation slot number. They are hardcoded to`);
    lines.push(`  MENULIST/party_menu.txt character IDs: idx0=charID2(Maribel), idx1=charID4(Gabo),`);
    lines.push(`  idx2=charID5(Melvin), idx3=charID6(Aira). idx4 (last param) is a CANCEL/`);
    lines.push(`  fallback flag id - used both when the player cancels the menu AND when the`);
    lines.push(`  picked character doesn't match any of the 4 hardcoded IDs (e.g. selecting the`);
    lines.push(`  last item in the candidate list). A value of 0 means "this is the asking`);
    lines.push(`  character's own ID (can't pick yourself)".`);
    lines.push(`  Consequence: this identity mapping is hardcoded to exactly these 4 characters -`);
    lines.push(`  it does NOT generalize to a variable/free-swap party (Keifa, Matilda, Hank etc.`);
    lines.push(`  would all fall through to the cancel/fallback flag, indistinguishable from Cancel).`);
  }
  lines.push(`raw: ${c.hex}`);

  detailEl.innerHTML = '';
  const pre = document.createElement('div');
  pre.textContent = lines.join('\n');
  detailEl.appendChild(pre);

  if (c.text) {
    const box = document.createElement('div');
    box.className = 'msgtext';
    box.textContent = c.text;
    detailEl.appendChild(box);
  }

  if (editMode) {
    const editBtn = document.createElement('button');
    editBtn.className = 'mode-btn';
    editBtn.style.marginTop = '10px';
    editBtn.textContent = t('editor.editThisCommand');
    editBtn.onclick = () => openCommandEditor(g_forDetail, o, p, ci, c);
    detailEl.appendChild(editBtn);
  }
}

// ============================================================
// Command editor (insert / edit / delete) - see /api/script/edit
// (webapp/server.py:edit_script_commands, backed by
// script/splice_procedure.py:replace_commands). All three operations
// are the same underlying "replace commands [start_idx,end_idx) with
// a new list" call: edit = same range in/out, insert = empty old
// range, delete = empty new list. See docs/party_add_remove_command_investigation.md
// for how the splice math itself was derived and validated.
// ============================================================

// showCommandDetail's caller doesn't currently pass the containing
// group `g` through to it (only o/p/ci/c) - stash it here whenever we
// render a command row so the detail panel's own edit button can still
// reach it without threading an extra parameter through every call site.
let g_forDetail = null;

function makeInsertRow(g, o, p, atIdx) {
  const row = document.createElement('div');
  row.className = 'cmd-insert-row';
  row.title = `#${atIdx}の位置に新規コマンドを挿入`;
  row.onclick = (ev) => {
    ev.stopPropagation();
    openInsertEditor(g, o, p, atIdx);
  };
  if (clipboardCommands && clipboardCommands.length) {
    row.classList.add('has-clipboard');
    const pasteBtn = document.createElement('button');
    pasteBtn.className = 'paste-btn';
    pasteBtn.textContent = `📋貼り付け(${clipboardCommands.length})`;
    pasteBtn.title = `#${atIdx}の位置にクリップボードの${clipboardCommands.length}件を貼り付け`;
    pasteBtn.onclick = (ev) => {
      ev.stopPropagation();
      pasteClipboardAt(g, o, p, atIdx);
    };
    row.appendChild(pasteBtn);
  }
  return row;
}

function parseIntFlexible(s) {
  s = s.trim();
  if (s === '') throw new Error('空の値があります');
  if (/^0x/i.test(s)) return parseInt(s, 16);
  const v = parseInt(s, 10);
  if (Number.isNaN(v)) throw new Error(`数値として解釈できません: ${s}`);
  return v;
}

// Per-param u32/i32/f32 typing (added 2026-08-27, per user request): the
// wire format always stores each param as a raw 4-byte LE value, but a
// float-carrying command like SET_POSITION is unreadable/unwritable by
// hand as a u32 bit pattern (e.g. typing "1065353216" instead of "1.0").
// This lets each param be edited in whichever representation makes
// sense, converting to/from the underlying u32 only at encode/decode
// time. Known opcodes get sensible defaults pre-assigned; anything else
// defaults to u32 (matching the previous plain-integer behavior).
function floatToU32(f) {
  const buf = new ArrayBuffer(4);
  new Float32Array(buf)[0] = f;
  return new Uint32Array(buf)[0];
}

function u32ToFloat(u) {
  const buf = new ArrayBuffer(4);
  new Uint32Array(buf)[0] = u >>> 0;
  return new Float32Array(buf)[0];
}

function paramValueForType(u32val, type) {
  if (type === 'f32') return String(Math.round(u32ToFloat(u32val) * 10000) / 10000);
  if (type === 'i32') return String(u32val | 0);
  return String(u32val >>> 0);
}

function encodeParamValue(value, type) {
  const v = String(value).trim();
  if (v === '') throw new Error('空のパラメータ値があります');
  if (type === 'f32') {
    const f = Number(v);
    if (Number.isNaN(f)) throw new Error(`floatとして解釈できません: ${v}`);
    return floatToU32(f);
  }
  const n = parseIntFlexible(v);
  return type === 'i32' ? (n | 0) : (n >>> 0);
}

// prefix: per-index default type for this opcode's known params; rest:
// fallback type for any params beyond the prefix (e.g. CHOICE_MENU's
// variable-length trailing slot flags). Mirrors the opcode constants /
// _decode_command() branches in webapp/server.py - kept as a separate
// hand-maintained table here since the frontend doesn't share that
// module; update both places together when a new opcode is confirmed.
const _KNOWN_PARAM_TYPES = {
  '0x00000003': { prefix: ['u32', 'u32', 'u32'], rest: 'u32' },  // IF_FLAG
  '0x00010004': { prefix: ['u32', 'u32', 'u32'], rest: 'u32' },  // SET_FLAG (分岐途中)
  '0x00030004': { prefix: ['u32', 'u32', 'u32'], rest: 'u32' },  // SET_FLAG (分岐終了マーカー、high16=0x0003)
  '0x00010022': { prefix: ['u32'], rest: 'u32' },                 // ADD_PARTY_MEMBER
  '0x00010023': { prefix: ['u32'], rest: 'u32' },                 // ADD_PARTY_MEMBER
  '0x00010064': { prefix: ['u32'], rest: 'u32' },                 // PARTY_SLOT_ACTIVATE
  '0x00010093': { prefix: ['u32', 'u32'], rest: 'u32' },          // PARTY_SLOT_QUERY
  '0x00010025': { prefix: ['u32', 'u32', 'u32'], rest: 'u32' },   // CONFIRM_YESNO
  '0x000100c5': { prefix: ['u32', 'u32'], rest: 'u32' },          // CHOICE_MENU
  '0x00010096': { prefix: ['u32', 'u32', 'u32'], rest: 'u32' },   // FANFARE_MSG (旧称JOIN_BANNER、2026-09-30訂正: 仲間加入専用ではなくアイテム入手等でも使われる汎用ジングルメッセージ)
  '0x00010014': { prefix: ['f32', 'f32', 'f32'], rest: 'u32' },   // SET_POSITION (仮説、2026-08-27)
  '0x00010005': { prefix: ['u32'], rest: 'u32' },                 // OBJECT_TOGGLE (確定、2026-08-30)
  '0x00030005': { prefix: ['u32'], rest: 'u32' },                 // OBJECT_TOGGLE (high16=0x0003版、確定2026-10-04): 話しかけ直すたびに毎回有効化し直したい場合に使う
  '0x0001001f': { prefix: ['u32', 'f32', 'f32', 'f32', 'u32', 'u32'], rest: 'u32' },  // MAP_WARP (有力な仮説、2026-08-31): [dst_floor_id, x, y, z, facing?, flag?]
  '0x0000000f': { prefix: ['u32'], rest: 'u32' },                 // IF_TALKED_TO (確定、2026-08-28)
  '0x00000070': { prefix: ['u32', 'u32'], rest: 'u32' },          // IF_KO_STATUS (確定、2026-09-29): [character_id, mode(1=戦闘不能で分岐/0=生存で分岐)]
  '0x0000006f': { prefix: ['u32'], rest: 'u32' },                 // IF_IS_PARTY_MEMBER (確定、2026-09-29): [character_id]
  '0x0000001b': { prefix: ['u32'], rest: 'u32' },                 // SET_MAP_OBJ_NUMBER (訂正、2026-10-04: START_BATTLEではなかった、意味未調査)
  '0x00000024': { prefix: ['u32', 'u32', 'u32', 'u32'], rest: 'u32' },  // ENCOUNT_SET_FLAG (確定、2026-10-04): [1, flag_id, type, value]
};
// mirrors server.py's _MESSAGE_OPCODE_LO (MSG-family opcodes matched by
// low byte, not exact value) - [msgID, count, ...] shape, both u32.
const _MESSAGE_OPCODE_LO_JS = new Set([0x09, 0x0a, 0x0b, 0x0d, 0x0e]);

function normalizeOpcodeHex(s) {
  const n = parseIntFlexible(String(s).trim());
  return `0x${(n >>> 0).toString(16).padStart(8, '0')}`;
}

function defaultParamTypesFor(opcodeStr, count) {
  let spec = null;
  try {
    spec = _KNOWN_PARAM_TYPES[normalizeOpcodeHex(opcodeStr)];
    if (!spec) {
      const n = parseIntFlexible(String(opcodeStr).trim());
      if (_MESSAGE_OPCODE_LO_JS.has(n & 0xff)) spec = { prefix: ['u32', 'u32'], rest: 'u32' };
    }
  } catch (e) {
    spec = null;
  }
  const types = [];
  for (let i = 0; i < count; i++) {
    types.push(spec ? (spec.prefix[i] !== undefined ? spec.prefix[i] : spec.rest) : 'u32');
  }
  return types;
}

function commandToFormRow(c) {
  const params = c.params || [];
  const types = defaultParamTypesFor(c.opcode || '0x00000000', params.length);
  return {
    indent: typeof c.indent === 'number' ? c.indent : 0,
    opcode: c.opcode || '0x00000000',
    paramRows: params.map((v, i) => ({ type: types[i], value: paramValueForType(v, types[i]) })),
  };
}

function openCommandEditor(g, o, p, ci, c) {
  g_forDetail = g;
  renderEditForm({
    title: `object ${o.index} (${o.tag}) / ${p.tag} — command #${ci} を編集`,
    g, o, p,
    startIdx: ci, endIdx: ci + 1,
    rows: [commandToFormRow(c)],
    allowMulti: true,
    submitLabel: '変更を予約',
  });
}

function openInsertEditor(g, o, p, atIdx) {
  g_forDetail = g;
  const neighborIndent = p.commands[atIdx] ? p.commands[atIdx].indent
    : (p.commands[atIdx - 1] ? p.commands[atIdx - 1].indent : 0);
  renderEditForm({
    title: `object ${o.index} (${o.tag}) / ${p.tag} — #${atIdx}の位置に新規コマンドを挿入`,
    g, o, p,
    startIdx: atIdx, endIdx: atIdx,
    rows: [{ indent: neighborIndent || 0, opcode: '0x00000000', paramRows: [] }],
    allowMulti: true,
    submitLabel: '挿入を予約',
  });
}

async function deleteCommand(g, o, p, ci, c) {
  // No per-delete comment prompt (removed 2026-08-27, per user feedback -
  // didn't fit the staged-editing workflow where several deletes happen
  // in a row before a single 保存). An auto-generated comment still
  // shows up in the batch's per-op breakdown in the history panel;
  // commitPendingEdits() asks for an overall comment once, at save time.
  const label = c.name || c.opcode || '';
  const ok = await stageEdit(g, o, p, ci, ci + 1, [], `#${ci} (${label}) を削除`, null);
  if (ok) statusEl.textContent = `#${ci} の削除を予約しました`;
}

function renderEditForm({ title, g, o, p, startIdx, endIdx, rows, submitLabel }) {
  detailEl.innerHTML = '';

  const heading = document.createElement('div');
  heading.textContent = title;
  heading.style.marginBottom = '8px';
  detailEl.appendChild(heading);

  const form = document.createElement('div');
  form.className = 'edit-form';
  const blocksWrap = document.createElement('div');
  form.appendChild(blocksWrap);

  const state = rows.map(r => ({ ...r }));

  function renderBlocks() {
    blocksWrap.innerHTML = '';
    state.forEach((row, i) => {
      const block = document.createElement('div');
      block.className = 'cmd-block';

      const r1 = document.createElement('div');
      r1.className = 'form-row';
      const indentField = document.createElement('div');
      indentField.innerHTML = '<label>indent (if/elseifネスト深さ)</label>';
      const indentInput = document.createElement('input');
      indentInput.type = 'number';
      indentInput.min = '0';
      indentInput.value = row.indent;
      indentInput.oninput = () => { row.indent = Number(indentInput.value); };
      indentField.appendChild(indentInput);
      r1.appendChild(indentField);

      const opcodeField = document.createElement('div');
      opcodeField.innerHTML = '<label>opcode (hex, 例: 0x00030009)</label>';
      const opcodeInput = document.createElement('input');
      opcodeInput.type = 'text';
      opcodeInput.value = row.opcode;
      opcodeInput.oninput = () => { row.opcode = opcodeInput.value; };
      opcodeField.appendChild(opcodeInput);
      r1.appendChild(opcodeField);
      block.appendChild(r1);

      const paramsLabel = document.createElement('label');
      paramsLabel.textContent = 'params（パラメータごとに型(u32/i32/f32)を指定して編集）';
      paramsLabel.style.display = 'block';
      paramsLabel.style.marginTop = '6px';
      block.appendChild(paramsLabel);

      const paramsWrap = document.createElement('div');
      paramsWrap.style.display = 'flex';
      paramsWrap.style.flexDirection = 'column';
      paramsWrap.style.gap = '4px';

      function renderParamRows() {
        paramsWrap.innerHTML = '';
        row.paramRows.forEach((pr, pi) => {
          const pRow = document.createElement('div');
          pRow.style.display = 'flex';
          pRow.style.gap = '4px';
          pRow.style.alignItems = 'center';
          pRow.style.flexWrap = 'wrap';

          const idxLabel = document.createElement('span');
          idxLabel.className = 'file-meta';
          idxLabel.style.minWidth = '20px';
          idxLabel.textContent = `#${pi}`;
          pRow.appendChild(idxLabel);

          const typeSelect = document.createElement('select');
          typeSelect.className = 'param-type-select';
          ['u32', 'i32', 'f32'].forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            if (t === pr.type) opt.selected = true;
            typeSelect.appendChild(opt);
          });
          typeSelect.onchange = () => { pr.type = typeSelect.value; };
          pRow.appendChild(typeSelect);

          const valueInput = document.createElement('input');
          valueInput.type = 'text';
          valueInput.className = 'param-value-input';
          valueInput.value = pr.value;
          valueInput.oninput = () => { pr.value = valueInput.value; };
          pRow.appendChild(valueInput);

          const rmParamBtn = document.createElement('button');
          rmParamBtn.className = 'secondary';
          rmParamBtn.textContent = '−';
          rmParamBtn.title = 'このパラメータを削除';
          rmParamBtn.onclick = () => { row.paramRows.splice(pi, 1); renderParamRows(); };
          pRow.appendChild(rmParamBtn);

          paramsWrap.appendChild(pRow);
        });
      }
      renderParamRows();
      block.appendChild(paramsWrap);

      const paramBtnsRow = document.createElement('div');
      paramBtnsRow.style.marginTop = '4px';
      paramBtnsRow.style.display = 'flex';
      paramBtnsRow.style.gap = '6px';

      const addParamBtn = document.createElement('button');
      addParamBtn.className = 'secondary';
      addParamBtn.textContent = '+ パラメータ追加';
      addParamBtn.onclick = () => {
        const nextType = defaultParamTypesFor(row.opcode, row.paramRows.length + 1)[row.paramRows.length];
        row.paramRows.push({ type: nextType, value: '0' });
        renderParamRows();
      };
      paramBtnsRow.appendChild(addParamBtn);

      const applyDefaultsBtn = document.createElement('button');
      applyDefaultsBtn.className = 'secondary';
      applyDefaultsBtn.textContent = '型を既定値に合わせる';
      applyDefaultsBtn.title = '現在のopcodeに対応する既知の型を各パラメータに割り当てます（値はそのまま、型のみ変更）';
      applyDefaultsBtn.onclick = () => {
        const types = defaultParamTypesFor(row.opcode, row.paramRows.length);
        row.paramRows.forEach((pr, pi) => { pr.type = types[pi]; });
        renderParamRows();
      };
      paramBtnsRow.appendChild(applyDefaultsBtn);
      block.appendChild(paramBtnsRow);

      if (state.length > 1) {
        const rmBtn = document.createElement('button');
        rmBtn.className = 'secondary';
        rmBtn.textContent = 'この行を削除';
        rmBtn.style.marginTop = '6px';
        rmBtn.onclick = () => { state.splice(i, 1); renderBlocks(); };
        block.appendChild(rmBtn);
      }

      blocksWrap.appendChild(block);
    });
  }
  renderBlocks();

  const addRowBtn = document.createElement('button');
  addRowBtn.className = 'secondary';
  addRowBtn.textContent = '+ コマンドを追加（複数一括挿入/置換）';
  addRowBtn.onclick = () => {
    const last = state[state.length - 1];
    state.push({ indent: last ? last.indent : 0, opcode: '0x00000000', paramRows: [] });
    renderBlocks();
  };
  form.appendChild(addRowBtn);

  const commentField = document.createElement('div');
  commentField.innerHTML = '<label>コメント（任意、変更履歴に残ります - 何をなぜ変えたか）</label>';
  const commentInput = document.createElement('input');
  commentInput.type = 'text';
  commentInput.placeholder = '例: CONFIRM_YESNOをバイパス';
  commentField.appendChild(commentInput);
  form.appendChild(commentField);

  const msgEl = document.createElement('div');
  msgEl.className = 'edit-msg';
  form.appendChild(msgEl);

  const actions = document.createElement('div');
  actions.className = 'form-actions';
  const saveBtn = document.createElement('button');
  saveBtn.textContent = submitLabel;
  saveBtn.onclick = async () => {
    let commands;
    try {
      commands = state.map(row => ({
        indent: Number(row.indent),
        opcode: row.opcode.trim(),
        params: row.paramRows.map(pr => encodeParamValue(pr.value, pr.type)),
      }));
    } catch (e) {
      msgEl.className = 'edit-msg error';
      msgEl.textContent = `入力エラー: ${e.message}`;
      return;
    }
    msgEl.className = 'edit-msg';
    msgEl.textContent = '検証中...';
    await stageEdit(g, o, p, startIdx, endIdx, commands, commentInput.value, msgEl);
  };
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'secondary';
  cancelBtn.textContent = t('editor.cancel');
  cancelBtn.onclick = () => { detailEl.innerHTML = `<div class="empty">${t('editor.detailEmpty')}</div>`; };
  actions.appendChild(saveBtn);
  actions.appendChild(cancelBtn);
  form.appendChild(actions);

  detailEl.appendChild(form);
}

async function submitCommandsEdit(g, o, p, startIdx, endIdx, commands, comment, successMsg, msgEl) {
  try {
    const res = await fetch('/api/script/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file: currentFileName,
        group_idx: g.index, obj_idx: o.index, proc_tag: p.tag,
        start_idx: startIdx, end_idx: endIdx, commands, comment,
      }),
    });
    const data = await res.json();
    if (!data.ok) {
      const text = `${t('common.error')}: ${data.error || 'unknown'}${data.anomalies ? '\n' + data.anomalies.join('\n') : ''}`;
      if (msgEl) { msgEl.className = 'edit-msg error'; msgEl.textContent = text; }
      else alert(text);
      return;
    }
    await reloadCurrentFile();
    if (msgEl) {
      msgEl.className = 'edit-msg success';
      msgEl.textContent = `保存しました (${data.old_size} -> ${data.new_size} bytes, backup: ${data.backup_path})`;
    }
    statusEl.textContent = successMsg || `保存しました (${data.old_size} -> ${data.new_size} bytes)`;
  } catch (e) {
    const text = `${t('common.error')}: ${e.message || e}`;
    if (msgEl) { msgEl.className = 'edit-msg error'; msgEl.textContent = text; }
    else alert(text);
  }
}

async function reloadCurrentFile() {
  if (!currentFileName) return;
  const res = await fetch(`/api/parse?file=${encodeURIComponent(currentFileName)}`);
  const tree = await res.json();
  if (tree.error) return;
  currentTree = tree;
  renderTree(tree);
}

// ============================================================
// Staged editing: stage an op into the in-browser preview buffer
// (pendingDataB64/pendingEdits) instead of writing to disk immediately.
// See the pendingDataB64/pendingEdits declaration near the top of this
// file for the overall design.
// ============================================================

async function ensurePendingBuffer() {
  if (pendingDataB64 !== null) return;
  const res = await fetch(`/api/script/raw?file=${encodeURIComponent(currentFileName)}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  pendingDataB64 = data.data_b64;
}

// Pulls the same {opcode,name,params,text} shape the server's
// _summarize_commands() produces, but computed client-side from a tree
// already in hand - used to capture "before" (from currentTree, prior to
// staging) and "after" (from the preview response's tree) summaries for
// each staged op, so a whole batch can still show per-op detail in the
// history panel even though it's saved/logged as a single entry.
function extractCmdSummary(tree, groupIdx, objIdx, procTag, start, end) {
  const g = tree.groups[groupIdx];
  const o = g.objects[objIdx];
  const p = o.procedures.find(pr => pr.tag === procTag);
  return p.commands.slice(start, end).map(c => ({
    indent: c.indent, opcode: c.opcode, name: c.name, params: c.params, text: (c.text || '').slice(0, 60) || null,
  }));
}

async function stageEdit(g, o, p, startIdx, endIdx, commands, comment, msgEl) {
  try {
    await ensurePendingBuffer();
    const before = extractCmdSummary(currentTree, g.index, o.index, p.tag, startIdx, endIdx);
    const res = await fetch('/api/script/edit_preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        data_b64: pendingDataB64,
        group_idx: g.index, obj_idx: o.index, proc_tag: p.tag,
        start_idx: startIdx, end_idx: endIdx, commands,
      }),
    });
    const data = await res.json();
    if (!data.ok) {
      const text = `${t('common.error')}: ${data.error || 'unknown'}${data.anomalies ? '\n' + data.anomalies.join('\n') : ''}`;
      if (msgEl) { msgEl.className = 'edit-msg error'; msgEl.textContent = text; }
      else alert(text);
      return false;
    }
    pendingDataB64 = data.data_b64;
    const after = extractCmdSummary(data.tree, g.index, o.index, p.tag, startIdx, startIdx + commands.length);
    pendingEdits.push({
      group_idx: g.index, obj_idx: o.index, proc_tag: p.tag,
      start_idx: startIdx, end_idx: endIdx,
      op: commands.length === 0 ? 'delete' : (startIdx === endIdx ? 'insert' : 'edit'),
      before, after, comment,
    });
    currentTree = data.tree;
    // any command index anywhere in the file may have shifted - a stale
    // selectedKeys entry would silently point at the wrong command, so
    // drop the selection rather than risk an incorrect bulk op later.
    // (deleteSelected() already captured its own target list before
    // calling this, so clearing mid-batch here doesn't affect it.)
    selectedKeys = new Set();
    renderTree(currentTree);
    renderPendingBar();
    renderSelectionBar();
    if (msgEl) {
      msgEl.className = 'edit-msg success';
      msgEl.textContent = `変更を予約しました（未保存 x${pendingEdits.length}件）- 「保存」を押すまで実ファイルには反映されません`;
    }
    return true;
  } catch (e) {
    const text = `${t('common.error')}: ${e.message || e}`;
    if (msgEl) { msgEl.className = 'edit-msg error'; msgEl.textContent = text; }
    else alert(text);
    return false;
  }
}

async function commitPendingEdits() {
  if (pendingEdits.length === 0) return;
  const count = pendingEdits.length;
  const defaultComment = pendingEdits.map(o => o.comment).filter(Boolean).join('; ');
  const comment = prompt(`${count}件の変更をまとめて保存します。コメント（任意）:`, defaultComment) || '';
  pendingBarStatusEl.textContent = '保存中...';
  const res = await fetch('/api/script/commit_batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file: currentFileName, data_b64: pendingDataB64, ops: pendingEdits, comment }),
  });
  const data = await res.json();
  if (!data.ok) {
    pendingBarStatusEl.textContent = `${t('common.error')}: ${data.error || 'unknown'}${data.anomalies ? '\n' + data.anomalies.join('\n') : ''}`;
    pendingBarStatusEl.style.color = '#e88080';
    return;
  }
  pendingEdits = [];
  pendingDataB64 = null;
  await reloadCurrentFile();
  renderPendingBar();
  renderSelectionBar();
  statusEl.textContent = `${count}件の変更を1つの履歴エントリとして保存しました`;
}

async function discardPendingEdits() {
  if (pendingEdits.length === 0) return;
  if (!confirm(`未保存の変更${pendingEdits.length}件を破棄しますか？`)) return;
  pendingEdits = [];
  pendingDataB64 = null;
  selectedKeys = new Set();
  await reloadCurrentFile();
  renderPendingBar();
  renderSelectionBar();
}

function renderPendingBar() {
  pendingBarEl.style.display = pendingEdits.length ? '' : 'none';
  pendingBarCountEl.textContent = `未保存の変更: ${pendingEdits.length}件`;
  pendingBarStatusEl.textContent = '';
  pendingBarStatusEl.style.color = '';
}

// ============================================================
// Multi-select copy/paste/bulk-delete (added 2026-08-27). See
// selectedKeys/clipboardCommands declaration near the top of this file.
// ============================================================

function renderSelectionBar() {
  const hasClipboard = clipboardCommands && clipboardCommands.length > 0;
  selectionBarEl.style.display = (selectedKeys.size > 0 || hasClipboard) ? '' : 'none';
  selectionBarCountEl.textContent = `選択中: ${selectedKeys.size}件`;
  selectionCopyBtn.disabled = selectedKeys.size === 0;
  selectionIndentIncBtn.disabled = selectedKeys.size === 0;
  selectionIndentDecBtn.disabled = selectedKeys.size === 0;
  selectionDeleteBtn.disabled = selectedKeys.size === 0;
  clipboardStatusEl.textContent = hasClipboard
    ? `📋 クリップボード: ${clipboardCommands.length}件（挿入位置に貼り付けボタンが出ます。indentは元の値のまま複製されるので、ネスト位置がずれる場合は貼り付け後に✎編集で調整してください）`
    : '';
}

// Walks the tree in file order (group -> object -> procedure -> command
// index) collecting every command whose selection key is set - so
// copy/delete always operate in a stable, predictable order regardless
// of the order commands were clicked in.
function getSelectedCommandsInFileOrder(tree) {
  const items = [];
  for (const g of tree.groups) {
    for (const o of g.objects) {
      for (const p of o.procedures) {
        p.commands.forEach((c, ci) => {
          const key = `g${g.index}-o${o.index}-p${p.tag}-c${ci}`;
          if (selectedKeys.has(key)) {
            items.push({ group_idx: g.index, obj_idx: o.index, proc_tag: p.tag, cmd_idx: ci, command: c, g, o, p });
          }
        });
      }
    }
  }
  return items;
}

function copySelected() {
  if (!currentTree) return;
  const items = getSelectedCommandsInFileOrder(currentTree);
  if (items.length === 0) return;
  clipboardCommands = items.map(it => ({
    indent: it.command.indent,
    opcode: it.command.opcode,
    params: it.command.params || [],
  }));
  renderTree(currentTree); // so insert-rows pick up the new clipboard paste buttons
  renderSelectionBar();
  statusEl.textContent = `${clipboardCommands.length}件をコピーしました`;
}

async function deleteSelected() {
  if (!currentTree) return;
  const items = getSelectedCommandsInFileOrder(currentTree);
  if (items.length === 0) return;
  if (!confirm(`選択した${items.length}件を一括削除しますか？（実ファイルへの保存は後で「保存」を押すまで行われません）`)) return;

  // group by procedure - deletions in different procedures don't affect
  // each other's indices, but within the SAME procedure, deleting must
  // proceed from the highest index downward so earlier (not-yet-deleted)
  // indices stay valid for the next staged op.
  const buckets = new Map();
  for (const it of items) {
    const bucketKey = `${it.group_idx}-${it.obj_idx}-${it.proc_tag}`;
    if (!buckets.has(bucketKey)) buckets.set(bucketKey, { g: it.g, o: it.o, p: it.p, indices: [] });
    buckets.get(bucketKey).indices.push(it.cmd_idx);
  }

  for (const bucket of buckets.values()) {
    const indices = bucket.indices.slice().sort((a, b) => a - b);
    const runs = [];
    let runStart = indices[0];
    let runEnd = indices[0];
    for (let i = 1; i < indices.length; i++) {
      if (indices[i] === runEnd + 1) {
        runEnd = indices[i];
      } else {
        runs.push([runStart, runEnd]);
        runStart = indices[i];
        runEnd = indices[i];
      }
    }
    runs.push([runStart, runEnd]);
    runs.sort((a, b) => b[0] - a[0]); // highest first

    for (const [s, e] of runs) {
      const label = `#${s}${e > s ? `-${e}` : ''}`;
      const ok = await stageEdit(bucket.g, bucket.o, bucket.p, s, e + 1, [], `${label} を一括削除`, null);
      if (!ok) {
        alert('一括削除の途中でエラーが発生しました。ここまでの削除は予約済みです。');
        selectedKeys = new Set();
        renderSelectionBar();
        return;
      }
    }
  }
  selectedKeys = new Set();
  renderSelectionBar();
  statusEl.textContent = `${items.length}件の一括削除を予約しました`;
}

// Bulk indent shift for the multi-select (added 2026-08-27, per user
// request): re-encodes each selected command with the same
// opcode/params but indent+delta (clamped to 0, since indent is an
// if/elseif nesting depth and can't go negative). Reuses the same
// contiguous-run grouping as deleteSelected() - unlike delete/insert,
// an in-place edit doesn't shift any indices, so runs don't need to be
// processed highest-first here, but grouping by run still keeps each
// stageEdit() call (and its history-log line) scoped to one contiguous
// block instead of one call per command.
async function bulkIndentSelected(delta) {
  if (!currentTree) return;
  const items = getSelectedCommandsInFileOrder(currentTree);
  if (items.length === 0) return;
  const label = delta > 0 ? '深く' : '浅く';
  if (!confirm(`選択した${items.length}件のインデントを${label}しますか？（実ファイルへの保存は後で「保存」を押すまで行われません）`)) return;

  const buckets = new Map();
  for (const it of items) {
    const bucketKey = `${it.group_idx}-${it.obj_idx}-${it.proc_tag}`;
    if (!buckets.has(bucketKey)) buckets.set(bucketKey, { g: it.g, o: it.o, p: it.p, byIdx: new Map() });
    buckets.get(bucketKey).byIdx.set(it.cmd_idx, it.command);
  }

  for (const bucket of buckets.values()) {
    const indices = [...bucket.byIdx.keys()].sort((a, b) => a - b);
    const runs = [];
    let runStart = indices[0];
    let runEnd = indices[0];
    for (let i = 1; i < indices.length; i++) {
      if (indices[i] === runEnd + 1) {
        runEnd = indices[i];
      } else {
        runs.push([runStart, runEnd]);
        runStart = indices[i];
        runEnd = indices[i];
      }
    }
    runs.push([runStart, runEnd]);

    for (const [s, e] of runs) {
      const commands = [];
      for (let idx = s; idx <= e; idx++) {
        const c = bucket.byIdx.get(idx);
        commands.push({
          indent: Math.max(0, (typeof c.indent === 'number' ? c.indent : 0) + delta),
          opcode: c.opcode,
          params: (c.params || []).slice(),
        });
      }
      const rangeLabel = `#${s}${e > s ? `-${e}` : ''}`;
      const ok = await stageEdit(bucket.g, bucket.o, bucket.p, s, e + 1, commands, `${rangeLabel} のインデントを${label}`, null);
      if (!ok) {
        alert('インデント変更の途中でエラーが発生しました。ここまでの変更は予約済みです。');
        selectedKeys = new Set();
        renderSelectionBar();
        return;
      }
    }
  }
  selectedKeys = new Set();
  renderSelectionBar();
  statusEl.textContent = `${items.length}件のインデントを${label}しました（予約）`;
}

async function pasteClipboardAt(g, o, p, atIdx) {
  if (!clipboardCommands || clipboardCommands.length === 0) return;
  const commands = clipboardCommands.map(c => ({ indent: c.indent, opcode: c.opcode, params: c.params.slice() }));
  const ok = await stageEdit(g, o, p, atIdx, atIdx, commands, `クリップボードから${commands.length}件貼り付け`, null);
  if (ok) statusEl.textContent = `#${atIdx}の位置に${commands.length}件を貼り付け予約しました`;
}

// ============================================================
// Change history panel (GET /api/script/history, POST .../comment,
// POST .../revert - see webapp/server.py). Every edit/insert/delete
// made through the command editor above is logged here automatically;
// this panel is just a reader/annotator/revert UI over that log.
// ============================================================

// ============================================================
// Used-flags panel: scans the currently loaded file (tree.flag_usage,
// computed server-side by _collect_flag_usage in webapp/server.py) for
// every (type,id) pair referenced by IF_FLAG/op_00010004/op_00030004/
// CONFIRM_YESNO, so a collision-free id can be picked before
// transplanting new content. Working theory (user, 2026-08-24): ids
// under a given type are map-local variables shared across every
// object/procedure in the file (possibly the whole group) - so
// "unused within this one procedure" isn't good enough, it has to be
// unused across the whole file.
// ============================================================

function showFlagUsagePanel() {
  if (!currentTree) {
    detailEl.innerHTML = '<div class="empty">先にファイルを選択してください</div>';
    return;
  }
  const usage = currentTree.flag_usage || [];
  detailEl.innerHTML = '';

  const heading = document.createElement('div');
  heading.textContent = `使用フラグ一覧: ${currentFileName} (${usage.length}件の参照, IF_FLAG/op_00010004/op_00030004/CONFIRM_YESNOをスキャン)`;
  heading.style.marginBottom = '10px';
  detailEl.appendChild(heading);

  if (usage.length === 0) {
    detailEl.appendChild(Object.assign(document.createElement('div'), { className: 'empty', textContent: 'このファイルにはフラグ参照が見つかりませんでした。' }));
    return;
  }

  // group by type, then by id
  const byType = new Map();
  for (const e of usage) {
    if (!byType.has(e.type)) byType.set(e.type, new Map());
    const byId = byType.get(e.type);
    if (!byId.has(e.id)) byId.set(e.id, []);
    byId.get(e.id).push(e);
  }

  for (const type of [...byType.keys()].sort((a, b) => a - b)) {
    const byId = byType.get(type);
    const ids = [...byId.keys()].sort((a, b) => a - b);
    const maxId = ids[ids.length - 1];

    const typeBlock = document.createElement('details');
    typeBlock.className = 'tree-node';
    typeBlock.open = true;
    const typeSummary = document.createElement('summary');
    typeSummary.innerHTML = `<span class="tag-name">type=${type}</span> <span class="file-meta">(${ids.length}個のID使用中: ${ids.join(', ')})</span>`;
    typeBlock.appendChild(typeSummary);

    const hint = document.createElement('div');
    hint.className = 'file-meta';
    hint.style.margin = '4px 0 8px';
    hint.textContent = `空き候補の例: ${maxId + 1}（最大使用値+1） / 99999（大きく離れた未使用番号、本セッションで実績あり）`;
    typeBlock.appendChild(hint);

    for (const id of ids) {
      const entries = byId.get(id);
      const idBlock = document.createElement('details');
      idBlock.className = 'tree-node';
      const idSummary = document.createElement('summary');
      const reads = entries.filter(e => e.rw === 'read').length;
      const writes = entries.filter(e => e.rw === 'write').length;
      idSummary.innerHTML = `id=${id} <span class="file-meta">(read x${reads}, write x${writes})</span>`;
      idBlock.appendChild(idSummary);

      const list = document.createElement('div');
      for (const e of entries) {
        const line = document.createElement('div');
        line.className = 'cmd-item';
        line.textContent = `[${e.rw === 'read' ? '読' : '書'}] group${e.group_idx}/obj${e.obj_idx}/${e.proc_tag} #${e.cmd_idx} (${e.opcode_name})`;
        list.appendChild(line);
      }
      idBlock.appendChild(list);
      typeBlock.appendChild(idBlock);
    }

    detailEl.appendChild(typeBlock);
  }
}

// Full-ROM message-text search (added 2026-08-27): finds which event
// files/objects display a message containing the given text, so the
// user doesn't have to guess a filename before browsing the tree. The
// heavy lifting (matching MESS text, then scanning every SCRIPT file's
// commands for a reference to a matching message id) happens server-side
// in search_message_text() - see webapp/server.py for why it's a
// two-pass design instead of resolving every command's text directly.
async function showSearchTextPanel() {
  detailEl.innerHTML = '';

  const heading = document.createElement('div');
  heading.textContent = 'メッセージテキストで検索（イベントファイル/オブジェクトを特定）';
  heading.style.marginBottom = '10px';
  detailEl.appendChild(heading);

  const formRow = document.createElement('div');
  formRow.style.display = 'flex';
  formRow.style.gap = '6px';
  formRow.style.marginBottom = '10px';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'メッセージに含まれる文字列（例: マリベル）';
  input.style.flex = '1';
  input.value = lastSearchTextQuery || '';
  const btn = document.createElement('button');
  btn.className = 'mode-btn';
  btn.textContent = '検索';
  formRow.appendChild(input);
  formRow.appendChild(btn);
  detailEl.appendChild(formRow);

  const resultsWrap = document.createElement('div');
  detailEl.appendChild(resultsWrap);

  const runSearch = async () => {
    const q = input.value.trim();
    if (!q) return;
    lastSearchTextQuery = q;
    resultsWrap.innerHTML = '<div class="empty">検索中...(全SCRIPTファイルを走査するため数秒〜十数秒かかります)</div>';
    btn.disabled = true;
    try {
      const res = await fetch(`/api/search_text?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      renderSearchTextResults(resultsWrap, data);
    } catch (e) {
      resultsWrap.innerHTML = `<div class="empty">${t('common.error')}: ${e.message || e}</div>`;
    } finally {
      btn.disabled = false;
    }
  };
  btn.onclick = runSearch;
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') runSearch(); });

  if (lastSearchTextQuery) runSearch();
}

function renderSearchTextResults(wrap, data) {
  wrap.innerHTML = '';
  if (data.error) {
    wrap.appendChild(Object.assign(document.createElement('div'), { className: 'empty', textContent: `${t('common.error')}: ${data.error}` }));
    return;
  }
  const results = data.results || [];
  const countLine = document.createElement('div');
  countLine.className = 'file-meta';
  countLine.style.marginBottom = '8px';
  countLine.textContent = `"${data.query}" の一致: ${results.length}件` +
    (data.truncated ? '（上限に達したため一部のみ表示。文字列を長くして絞り込んでください）' : '');
  wrap.appendChild(countLine);

  if (results.length === 0) {
    wrap.appendChild(Object.assign(document.createElement('div'), { className: 'empty', textContent: '一致するメッセージが見つかりませんでした。' }));
    return;
  }

  // group by file so results for the same event file cluster together
  const byFile = new Map();
  for (const r of results) {
    if (!byFile.has(r.file)) byFile.set(r.file, []);
    byFile.get(r.file).push(r);
  }

  for (const [file, hits] of byFile) {
    const fileBlock = document.createElement('details');
    fileBlock.className = 'tree-node';
    fileBlock.open = byFile.size <= 5;
    const fileSummary = document.createElement('summary');
    fileSummary.innerHTML = `<span class="tag-name">${escapeHtml(file)}</span> <span class="file-meta">(${hits.length}件)</span>`;
    fileBlock.appendChild(fileSummary);

    for (const r of hits) {
      const line = document.createElement('div');
      line.className = 'cmd-item has-text';
      line.textContent = `group${r.group_idx}/obj${r.obj_idx}(${r.obj_tag})/${r.proc_tag} #${r.cmd_idx}: ${previewLabel(r.text)}`;
      line.title = 'クリックでツリー内の該当コマンドへ移動';
      line.onclick = () => navigateToCommand(r.file, r.group_idx, r.obj_idx, r.proc_tag, r.cmd_idx);
      fileBlock.appendChild(line);
    }
    wrap.appendChild(fileBlock);
  }
}

let lastSearchTextQuery = '';

// Jumps the tree/detail panes to a specific command found via search (or
// any other future cross-file lookup): loads the file if needed, expands
// its ancestor <details> nodes, then simulates a click on the matching
// cmd-item (identified by the same `g{gi}-o{oi}-p{tag}-c{ci}` key used
// for the multi-select checkboxes) so the existing selection/detail-view
// logic just runs normally.
async function navigateToCommand(fileName, groupIdx, objIdx, procTag, cmdIdx) {
  if (currentFileName !== fileName) {
    await selectFile(fileName);
  }
  const gKey = `g${groupIdx}`;
  const oKey = `g${groupIdx}-o${objIdx}`;
  const pKey = `g${groupIdx}-o${objIdx}-p${procTag}`;
  for (const key of [gKey, oKey, pKey]) {
    const el = treeEl.querySelector(`details[data-key="${cssEscape(key)}"]`);
    if (el) el.open = true;
  }
  const cmdKey = `${pKey}-c${cmdIdx}`;
  const target = treeEl.querySelector(`[data-cmd-key="${cssEscape(cmdKey)}"]`);
  if (!target) return;
  target.scrollIntoView({ block: 'center' });
  target.click();
  if (isMobile()) showPane('tree');
}

function cssEscape(s) {
  return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
}

function summarizeCmdList(list) {
  if (!list || list.length === 0) return '(なし)';
  return list.map(c => c.name || c.opcode || '?').join(', ');
}

// <textarea> does NOT grow to fit its content on its own (that was a
// wrong assumption when this was first switched over from <input> -
// user caught it 2026-08-27: it just sat at `rows` height regardless of
// how much text was in it). This measures the content's natural height
// via scrollHeight and applies it as an explicit inline height; the
// CSS max-height + overflow-y:auto on .history-input (~10 lines) still
// caps it and switches to a scrollbar beyond that.
function autoGrowTextarea(el) {
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

async function showHistoryPanel() {
  if (!currentFileName) {
    detailEl.innerHTML = '<div class="empty">先にファイルを選択してください</div>';
    return;
  }
  detailEl.innerHTML = '<div class="empty">読み込み中...</div>';
  const res = await fetch(`/api/script/history?file=${encodeURIComponent(currentFileName)}`);
  const entries = await res.json();

  detailEl.innerHTML = '';
  const heading = document.createElement('div');
  heading.textContent = `変更履歴: ${currentFileName} (${entries.length}件、新しい順)`;
  heading.style.marginBottom = '10px';
  detailEl.appendChild(heading);

  if (entries.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'まだこのファイルへの編集履歴はありません。';
    detailEl.appendChild(empty);
    return;
  }

  for (const e of entries) {
    const block = document.createElement('div');
    block.className = 'cmd-block';
    block.style.marginBottom = '10px';

    const opLabel = { edit: '編集', insert: '挿入', delete: '削除', revert: '復元', batch: `まとめて${(e.ops || []).length}件`, npc_field_edit: '配置情報編集', add_object: 'オブジェクト追加', overwrite_object: 'オブジェクト乗っ取り', delete_object: 'オブジェクト削除' }[e.op] || e.op;
    const target = (e.op === 'revert' || e.op === 'batch')
      ? ''
      : e.op === 'npc_field_edit'
      ? ` — group${e.group_idx}/obj${e.obj_idx} ${e.field_name || ''}(+0x${(e.field_offset || 0).toString(16)})`
      : e.op === 'add_object'
      ? ` — group${e.target_group_idx}/obj${e.new_obj_idx} ← ${e.src_file}:group${e.src_group_idx}/obj${e.src_obj_idx}${e.new_tag ? ` (tag=${e.new_tag})` : ''}`
      : e.op === 'overwrite_object'
      ? ` — group${e.target_group_idx}/obj${e.target_obj_idx} ← ${e.src_file}:group${e.src_group_idx}/obj${e.src_obj_idx}${e.new_tag ? ` (tag=${e.new_tag})` : ''}`
      : e.op === 'delete_object'
      ? ` — group${e.target_group_idx}/obj${e.target_obj_idx}`
      : ` — group${e.group_idx}/obj${e.obj_idx}/${e.proc_tag} #${e.start_idx}${e.end_idx - e.start_idx > 1 ? `-${e.end_idx - 1}` : ''}`;
    const head = document.createElement('div');
    head.innerHTML = `<b>[${escapeHtml(opLabel)}]</b> ${escapeHtml(e.timestamp)}${escapeHtml(target)}`;
    block.appendChild(head);

    if (e.op === 'batch') {
      const subOpLabel = { edit: '編集', insert: '挿入', delete: '削除' };
      for (const sub of (e.ops || [])) {
        const subDiv = document.createElement('div');
        subDiv.className = 'file-meta';
        subDiv.style.marginTop = '2px';
        subDiv.textContent = `  [${subOpLabel[sub.op] || sub.op}] group${sub.group_idx}/obj${sub.obj_idx}/${sub.proc_tag} #${sub.start_idx}${sub.end_idx - sub.start_idx > 1 ? `-${sub.end_idx - 1}` : ''}: ${summarizeCmdList(sub.before)} → ${summarizeCmdList(sub.after)}${sub.comment ? ` (${sub.comment})` : ''}`;
        block.appendChild(subDiv);
      }
    } else if (e.op === 'npc_field_edit') {
      const diff = document.createElement('div');
      diff.className = 'file-meta';
      diff.style.marginTop = '4px';
      const bv = e.before || {}, av = e.after || {};
      diff.textContent = `u32:${bv.u32}/i32:${bv.i32}/f32:${bv.f32}  →  u32:${av.u32}/i32:${av.i32}/f32:${av.f32}`;
      block.appendChild(diff);
    } else if (e.op !== 'revert') {
      const diff = document.createElement('div');
      diff.className = 'file-meta';
      diff.style.marginTop = '4px';
      diff.textContent = `${summarizeCmdList(e.before)}  →  ${summarizeCmdList(e.after)}`;
      block.appendChild(diff);
    }

    const commentWrap = document.createElement('div');
    commentWrap.style.marginTop = '6px';
    const commentInput = document.createElement('textarea');
    commentInput.rows = 2;
    commentInput.className = 'history-input';
    commentInput.placeholder = 'コメント（何をなぜ変えたか）...';
    commentInput.value = e.comment || '';
    commentInput.addEventListener('input', () => autoGrowTextarea(commentInput));
    const commentSaveBtn = document.createElement('button');
    commentSaveBtn.className = 'secondary';
    commentSaveBtn.textContent = 'コメントを保存';
    commentSaveBtn.style.marginTop = '4px';
    const commentSaveMsg = document.createElement('span');
    commentSaveMsg.className = 'file-meta';
    commentSaveMsg.style.marginLeft = '8px';
    commentSaveBtn.onclick = async () => {
      // Deliberately does NOT call showHistoryPanel() to refresh (that
      // was the bug reported 2026-08-28: saving ONE entry's comment
      // re-rendered the WHOLE panel from a fresh fetch, wiping out
      // whatever the user had typed-but-not-yet-saved into any OTHER
      // entry's comment/result box in the meantime - very disruptive
      // for the actual workflow of adding real-hardware test notes to
      // several entries in one sitting). Just patch this one entry's
      // in-memory state and show an inline confirmation instead.
      commentSaveMsg.textContent = '保存中...';
      try {
        await fetch('/api/script/history/comment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entry_id: e.id, comment: commentInput.value }),
        });
        e.comment = commentInput.value;
        commentSaveMsg.textContent = '保存しました';
      } catch (err) {
        commentSaveMsg.textContent = `${t('common.error')}: ${err.message || err}`;
      }
    };
    commentWrap.appendChild(commentInput);
    commentWrap.appendChild(commentSaveBtn);
    commentWrap.appendChild(commentSaveMsg);
    block.appendChild(commentWrap);

    const resultWrap = document.createElement('div');
    resultWrap.style.marginTop = '6px';
    const rcInput = document.createElement('textarea');
    rcInput.rows = 2;
    rcInput.className = 'history-input';
    rcInput.placeholder = '実機テスト結果などを記録...';
    rcInput.value = e.result_comment || '';
    rcInput.addEventListener('input', () => autoGrowTextarea(rcInput));
    const rcSaveBtn = document.createElement('button');
    rcSaveBtn.className = 'secondary';
    rcSaveBtn.textContent = '結果を保存';
    rcSaveBtn.style.marginTop = '4px';
    const rcSaveMsg = document.createElement('span');
    rcSaveMsg.className = 'file-meta';
    rcSaveMsg.style.marginLeft = '8px';
    rcSaveBtn.onclick = async () => {
      // Same fix as commentSaveBtn above - no full-panel re-render.
      rcSaveMsg.textContent = '保存中...';
      try {
        await fetch('/api/script/history/comment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entry_id: e.id, result_comment: rcInput.value }),
        });
        e.result_comment = rcInput.value;
        rcSaveMsg.textContent = '保存しました';
      } catch (err) {
        rcSaveMsg.textContent = `${t('common.error')}: ${err.message || err}`;
      }
    };
    resultWrap.appendChild(rcInput);
    resultWrap.appendChild(rcSaveBtn);
    resultWrap.appendChild(rcSaveMsg);
    block.appendChild(resultWrap);

    if (e.op !== 'revert' && e.op !== 'add_object' && e.op !== 'overwrite_object' && e.op !== 'delete_object') {
      const undoBtn = document.createElement('button');
      undoBtn.className = 'danger';
      undoBtn.textContent = 'この変更を打ち消す (revert)';
      undoBtn.style.marginTop = '6px';
      undoBtn.onclick = async () => {
        if (!confirm(`${e.timestamp}の変更を打ち消す変更を新たに追加しますか？\n（gitのrevertと同様、この履歴自体やそれ以降の変更は残ります）`)) return;
        const r = await fetch('/api/script/history/revert_op', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file: currentFileName, entry_id: e.id }),
        });
        const data = await r.json();
        if (!data.ok) {
          let msg = `打ち消せませんでした: ${data.error || 'unknown'}`;
          if (data.conflicts) {
            msg += `\n\n競合箇所: ${data.conflicts.map(c => `group${c.group_idx}/obj${c.obj_idx}/${c.proc_tag} #${c.start_idx}`).join(', ')}`;
            msg += '\n\n必要であれば、下の「（強制）これより前の状態に一括で戻す」で対処してください。';
          }
          alert(msg);
          return;
        }
        await reloadCurrentFile();
        showHistoryPanel();
      };
      block.appendChild(undoBtn);
    }

    const revertBtn = document.createElement('button');
    revertBtn.className = 'danger';
    revertBtn.style.marginLeft = '6px';
    revertBtn.textContent = '（強制）これより前の状態に一括で戻す';
    revertBtn.style.marginTop = '6px';
    revertBtn.onclick = async () => {
      if (!confirm(`${e.timestamp}の変更(および、それ以降の全ての変更)を取り消して元に戻しますか？\n（この操作自体も履歴に記録され、取り消せます）`)) return;
      const r = await fetch('/api/script/history/revert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_id: e.id }),
      });
      const data = await r.json();
      if (!data.ok) {
        alert(`${t('common.error')}: ${data.error || 'unknown'}`);
        return;
      }
      await reloadCurrentFile();
      showHistoryPanel();
    };
    block.appendChild(revertBtn);

    detailEl.appendChild(block);
    // scrollHeight only reflects real content once attached to the
    // document, so the initial grow-to-fit (for pre-filled long
    // comments) has to happen after this append, not at creation time.
    autoGrowTextarea(commentInput);
    autoGrowTextarea(rcInput);
  }
}

// MESS entries are fixed-size chunks of a continuous text stream (see
// mess/README.md), not aligned to sentence boundaries - so a message's
// raw text often starts mid-word (showing as a garbled/replacement-char
// prefix) or with a bare "#NNNN"/"TALKER=NNNN" inline control-code line
// before the actual dialogue. Skip those so list previews show something
// recognizable instead of that leading garbage.
function previewLabel(text) {
  const rawLines = text.split('\r\n');
  // "#NNNN" / "TALKER=NNNN" lines are inline speaker/portrait control
  // codes. Everything before the FIRST one is usually bleed-over from the
  // previous chunk's sentence (see comment above); prefer content right
  // after it - this message's own line, not a later reply further down
  // (a multi-count entry can contain several speakers' turns in one blob).
  let firstMarker = rawLines.findIndex(
    l => /^#\d+$/.test(l.trim()) || /^TALKER=\d+$/.test(l.trim())
  );

  const clean = (line) => {
    line = line.replace(/^�+/, '');
    const rubyTail = line.match(/^[^{]{0,6}\}/);
    if (rubyTail) line = line.slice(rubyTail[0].length);
    return line.trim();
  };

  if (firstMarker >= 0) {
    for (let i = firstMarker + 1; i < rawLines.length; i++) {
      const line = clean(rawLines[i]);
      if (line) return line.slice(0, 28);
    }
  }

  let fallback = '';
  for (const raw of rawLines) {
    const line = clean(raw);
    if (!line) continue;
    if (/^#\d+$/.test(line) || /^TALKER=\d+$/.test(line)) continue;
    if (!fallback) fallback = line;
    if (line.length >= 6) return line.slice(0, 28);
  }
  return (fallback || text.replace(/�/g, '')).slice(0, 28);
}

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

window.addEventListener('dq7lang:change', () => {
  renderFileList();
  renderRecentList();
  renderPendingBar();
  renderSelectionBar();
  if (currentTree) renderTree(currentTree);
  editModeToggle.textContent = t(editMode ? 'editor.editModeOn' : 'editor.editModeOff');
});

loadFiles();
