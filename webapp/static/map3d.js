// Map 3D viewer: RomFS MAP/MAPDATA/*.pack.lz (see mappack.py and
// docs/formats/models/map_pack.md). A map pack is a set of parts (one CGFX model
// each, part-local coordinates) plus placement nodes (GNOD: translation /
// rotation / scale per instance). Each part's geometry is built once and
// instanced by every node that references it.
//
// Material handling follows the same rule as model.js: everything comes
// from what the server decoded out of the material structures, nothing is
// guessed from texture pixels -
//   alphaTest  {enabled, reference}  GfxAlphaTest command (bcmdl._alpha_test)
//   side       front/back/double     FaceCulling command (bcmdl._cull_mode)
//   textureUV  uv channel per stage  GfxTextureCoord.SourceCoordIndex
//   vertexColor 'modulate'           TexEnv stage reads PrimaryColor
//                                    (bcmdl._tex_env_vertex_color_mode)
// Every map material seen so far is stage0 = Modulate(PrimaryColor,
// Texture0) with the remaining stages passthrough, so only stage 0 is drawn;
// shapes whose combiner samples more textures are counted in the info pane.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const I18N = window.DQ7I18N;
const t = I18N ? I18N.t : (k, f) => f !== undefined ? f : k;
if (I18N) {
  I18N.extend({
    ja: {
      'map3d.tabFile': 'ファイル',
      'map3d.tab3d': '3D',
      'map3d.tabInfo': '情報',
      'map3d.searchPlaceholder': 'マップ名で絞り込み...',
      'map3d.threeLoading': 'Three.js 読み込み中...',
      'map3d.btnTexture': 'テクスチャ',
      'map3d.btnVertexColor': '頂点カラー',
      'map3d.btnWireframe': 'ワイヤーフレーム',
      'map3d.btnBoxes': 'ノード枠',
      'map3d.btnColl': 'コリジョン',
      'map3d.collision': 'コリジョン (COLL/PLGN)',
      'map3d.collCount': 'ポリゴン {n}',
      'map3d.btnReset': '視点リセット',
      'map3d.selectPrompt': 'マップを選択してください',
      'map3d.noMap': 'マップ未選択',
      'map3d.loading': '読み込み中...',
      'map3d.error': 'エラー',
      'map3d.summary': 'ノード {n} / 部品 {p} / シェイプ {s}',
      'map3d.chunks': 'チャンク',
      'map3d.params': 'パラメータ (PARM)',
      'map3d.background': '背景色',
      'map3d.nodes': '配置ノード (WNOD/GNOD)',
      'map3d.nodeHint': '行をタップするとそのノードへ視点移動',
      'map3d.missingTextures': 'パック外テクスチャ参照（未解決）',
      'map3d.extraStages': '2枚目以降のテクスチャを合成に使うシェイプ（未描画）',
      'map3d.textures': '共有テクスチャ',
      'map3d.colName': '名前',
      'map3d.colPart': '部品',
      'map3d.colPos': '位置',
      'map3d.colRotY': '回転Y',
      'map3d.colScale': 'スケール',
      'map3d.animGroup': 'a_ (アニメ部品)',
      'map3d.otherGroup': 'その他',
    },
    en: {
      'map3d.tabFile': 'Files',
      'map3d.tab3d': '3D',
      'map3d.tabInfo': 'Info',
      'map3d.searchPlaceholder': 'Filter by map name...',
      'map3d.threeLoading': 'Loading Three.js...',
      'map3d.btnTexture': 'Texture',
      'map3d.btnVertexColor': 'Vertex color',
      'map3d.btnWireframe': 'Wireframe',
      'map3d.btnBoxes': 'Node boxes',
      'map3d.btnColl': 'Collision',
      'map3d.collision': 'Collision (COLL/PLGN)',
      'map3d.collCount': '{n} polygons',
      'map3d.btnReset': 'Reset view',
      'map3d.selectPrompt': 'Select a map',
      'map3d.noMap': 'No map selected',
      'map3d.loading': 'Loading...',
      'map3d.error': 'Error',
      'map3d.summary': '{n} nodes / {p} parts / {s} shapes',
      'map3d.chunks': 'Chunks',
      'map3d.params': 'Parameters (PARM)',
      'map3d.background': 'Background',
      'map3d.nodes': 'Placement nodes (WNOD/GNOD)',
      'map3d.nodeHint': 'tap a row to move the camera to that node',
      'map3d.missingTextures': 'Texture references outside this pack (unresolved)',
      'map3d.extraStages': 'Shapes whose combiner uses a 2nd+ texture (not drawn)',
      'map3d.textures': 'Shared textures',
      'map3d.colName': 'Name',
      'map3d.colPart': 'Part',
      'map3d.colPos': 'Position',
      'map3d.colRotY': 'Rot Y',
      'map3d.colScale': 'Scale',
      'map3d.animGroup': 'a_ (animated parts)',
      'map3d.otherGroup': 'Other',
    },
  });
}
const fmt = (s, o) => s.replace(/\{(\w+)\}/g, (_, k) => o[k]);

const statusEl = document.getElementById('status');
const listInner = document.getElementById('mapFileListInner');
const searchBox = document.getElementById('mapSearch');
const infoEl = document.getElementById('mapInfo');
const mstatus = document.getElementById('mapStatus');
const canvas = document.getElementById('mapCanvas');
const mobileTabs = document.getElementById('mobileTabs');

function showPane(name) {
  document.querySelectorAll('#mapLayout .pane').forEach(p => p.classList.remove('mobile-active'));
  document.getElementById(name).classList.add('mobile-active');
  mobileTabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.pane === name));
  if (name === 'mapViewport') { resize(); if (mapGroup.children.length && !framed) frameAll(); }
}
mobileTabs.querySelectorAll('button').forEach(b => b.addEventListener('click', () => showPane(b.dataset.pane)));
const isMobile = () => window.matchMedia('(max-width: 760px)').matches;

// ---- Three.js scene ---------------------------------------------------------
let renderer, scene, camera, controls, mapGroup, boxGroup, collGroup;
let texMode = true, vcolMode = true, wireframe = false, boxesMode = false, collMode = false;
let collBox = null;   // THREE.Box3 of the PLGN collision extent (initial framing)
let framed = false;
const DEFAULT_BG = 0x0d0f17;

function initThree() {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  scene = new THREE.Scene();
  scene.background = new THREE.Color(DEFAULT_BG);
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  camera.position.set(30, 30, 30);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  mapGroup = new THREE.Group();
  scene.add(mapGroup);
  boxGroup = new THREE.Group();
  boxGroup.visible = boxesMode;
  scene.add(boxGroup);
  collGroup = new THREE.Group();
  collGroup.visible = collMode;
  scene.add(collGroup);
  resize();
  window.addEventListener('resize', resize);
  animate();
  mstatus.textContent = t('map3d.noMap');
}

let _lastW = 0, _lastH = 0;
function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (w < 2 || h < 2 || (w === _lastW && h === _lastH)) return;
  _lastW = w; _lastH = h;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function animate() {
  requestAnimationFrame(animate);
  resize();
  controls.update();
  renderer.render(scene, camera);
}

function frameBox(box) {
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(radius * 0.9, radius * 0.9, radius * 1.2));
  camera.near = Math.max(radius / 500, 0.01);
  camera.far = radius * 50;
  camera.updateProjectionMatrix();
}
// Initial view: the collision extent (where the player can actually walk),
// not the whole model - most outdoor maps include a backdrop cylinder/sky
// part hundreds of units across that would shrink the playable area to a
// dot. Falls back to all geometry when the pack has no PLGN.
function frameAll() {
  if (_lastW < 2) return;   // viewport hidden (mobile): frame when it is shown
  frameBox(collBox && !collBox.isEmpty() ? collBox : new THREE.Box3().setFromObject(mapGroup));
  framed = true;
}

// ---- materials / textures ----------------------------------------------------
let currentFile = null;
let buildGen = 0;
const texCache = new Map();
const _texLoader = new THREE.TextureLoader();

// mipmaps on: maps are viewed from far away, so unfiltered textures shimmer.
// (model.js disables mipmaps because averaged alpha broke small cutout
// details on characters; map cutouts - foliage, fences - are coarser.)
function loadTexture(file, name) {
  const key = `${file}|${name}`;
  if (!texCache.has(key)) {
    const url = `/api/map/texture?file=${encodeURIComponent(file)}&name=${encodeURIComponent(name)}`;
    texCache.set(key, _texLoader.loadAsync(url).then(tex => {
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.flipY = true;            // 3DS v=0 is the bottom row, same as model.js
      tex.anisotropy = 4;
      tex.needsUpdate = true;
      return tex;
    }).catch(() => null));
  }
  return texCache.get(key);
}

const _SIDE = { front: THREE.FrontSide, back: THREE.BackSide, double: THREE.DoubleSide };

// One material per part shape, shared by every node instancing that part.
function makeMaterial(s) {
  const at = s.alphaTest;
  const useVC = vcolMode && s.vertexColor === 'modulate' && !!s.colors;
  return new THREE.MeshBasicMaterial({
    color: texMode ? 0xffffff : 0xb8c4d0,
    vertexColors: useVC,
    side: _SIDE[s.side] ?? THREE.DoubleSide,
    wireframe,
    // GfxAlphaTest: discard below reference (Greater/Gequal). Alpha
    // blending is a separate GfxFragOp setting not decoded here, so cutout
    // only - no transparent sort.
    alphaTest: (texMode && at && at.enabled) ? Math.max(at.reference / 255, 0.01) : 0,
  });
}

function shapeStages(s) {
  return (s.textures && s.textures.length) ? s.textures : (s.texture ? [s.texture] : []);
}

function buildPartGeometry(s) {
  const nv = s.positions.length / 3;
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(s.positions, 3));
  const uvArrays = [s.uvs, s.uvs1, s.uvs2];
  const uv = uvArrays[(s.textureUV || [0])[0] ?? 0];
  if (uv && uv.length === nv * 2) g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  if (s.colors && s.colors.length === nv * 4) {
    // PICA multiplies texel * vertex color on the raw (gamma-space) values.
    // three samples the sRGB texture into linear space, so the vertex color
    // must be linearized too for the product to come out the same:
    // lin(t) * lin(v) == lin(t * v) for the power-curve part of sRGB.
    const rgb = new Float32Array(nv * 3);
    const c = new THREE.Color();
    for (let i = 0; i < nv; i++) {
      c.setRGB(s.colors[i * 4], s.colors[i * 4 + 1], s.colors[i * 4 + 2], THREE.SRGBColorSpace);
      rgb[i * 3] = c.r; rgb[i * 3 + 1] = c.g; rgb[i * 3 + 2] = c.b;
    }
    g.setAttribute('color', new THREE.Float32BufferAttribute(rgb, 3));
  }
  if (s.indices && s.indices.length >= 3) g.setIndex(s.indices);
  g.computeBoundingSphere();
  return g;
}

let partShapes = new Map();   // part index -> [{shape, geometry, material}]

function disposeMap() {
  for (const list of partShapes.values()) {
    for (const ps of list) { ps.geometry.dispose(); ps.material.dispose(); }
  }
  partShapes = new Map();
  mapGroup.clear();
  for (const grp of [boxGroup, collGroup]) {
    grp.traverse(o => { if (o !== grp) { o.geometry?.dispose(); o.material?.dispose(); } });
    grp.clear();
  }
  collBox = null;
}

function buildCollision(c) {
  if (!c || !c.positions || !c.positions.length) return;
  collBox = new THREE.Box3(new THREE.Vector3(...c.bboxMin), new THREE.Vector3(...c.bboxMax));
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(c.positions, 3));
  // polygon offset pulls the overlay in front of coplanar floor geometry
  collGroup.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({
    color: 0x33ff99, transparent: true, opacity: 0.25, side: THREE.DoubleSide,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4,
  })));
  collGroup.add(new THREE.LineSegments(new THREE.WireframeGeometry(g),
    new THREE.LineBasicMaterial({ color: 0x33ff99, transparent: true, opacity: 0.6 })));
}

function applyTextures(gen) {
  for (const list of partShapes.values()) {
    for (const ps of list) {
      const name = shapeStages(ps.shape)[0];
      if (!texMode || !name || !ps.geometry.getAttribute('uv')) {
        ps.material.map = null; ps.material.needsUpdate = true;
        continue;
      }
      loadTexture(currentFile, name).then(tex => {
        if (gen !== buildGen || !tex || !texMode) return;
        ps.material.map = tex;
        ps.material.needsUpdate = true;
      });
    }
  }
}

function rebuildMaterials() {
  for (const list of partShapes.values()) {
    for (const ps of list) {
      const old = ps.material;
      ps.material = makeMaterial(ps.shape);
      ps.material.map = old.map;
      for (const m of ps.meshes) m.material = ps.material;
      old.dispose();
    }
  }
  applyTextures(buildGen);
}

function buildMap(r) {
  disposeMap();
  currentFile = r.file;
  const gen = ++buildGen;
  framed = false;

  const bg = r.params && r.params.background;
  scene.background = new THREE.Color(DEFAULT_BG);
  if (bg && bg.length >= 3) scene.background.setRGB(bg[0], bg[1], bg[2], THREE.SRGBColorSpace);

  for (const p of r.parts) {
    const list = [];
    for (const s of p.shapes) {
      if (!s.positions || s.positions.length < 9) continue;
      list.push({ shape: s, geometry: buildPartGeometry(s), material: makeMaterial(s), meshes: [] });
    }
    partShapes.set(p.index, list);
  }

  let nShapes = 0;
  r.nodes.forEach((n, ni) => {
    if (n.type !== 1) return;
    const grp = new THREE.Group();
    grp.name = n.name;
    grp.position.set(...n.translation);
    // Euler order: only Y rotations occur in the data seen so far, so
    // the X/Y/Z composition order is not yet confirmed.
    grp.rotation.set(n.rotation[0], n.rotation[1], n.rotation[2], 'XYZ');
    grp.scale.set(...n.scale);
    grp.userData.nodeIndex = ni;
    for (const ps of (partShapes.get(n.part) || [])) {
      const m = new THREE.Mesh(ps.geometry, ps.material);
      ps.meshes.push(m);
      grp.add(m);
      nShapes++;
    }
    mapGroup.add(grp);

    const box = new THREE.Box3(new THREE.Vector3(...n.bboxMin), new THREE.Vector3(...n.bboxMax));
    const helper = new THREE.Box3Helper(box, 0xffcc33);
    const hg = new THREE.Group();
    hg.position.copy(grp.position); hg.rotation.copy(grp.rotation); hg.scale.copy(grp.scale);
    hg.add(helper);
    hg.userData.nodeIndex = ni;
    boxGroup.add(hg);
  });
  buildCollision(r.collision);
  applyTextures(gen);
  frameAll();
  return nShapes;
}

// ---- file list -----------------------------------------------------------------
let allFiles = [];
let selected = null;

function groupKey(name) {
  if (name.startsWith('a_')) return t('map3d.animGroup');
  const m = name.match(/^([a-z]+\d\d[pn]?)/);
  if (m) return m[1];
  const u = name.split('_')[0];
  return u || t('map3d.otherGroup');
}

async function loadFiles() {
  const res = await fetch('/api/map_files');
  allFiles = await res.json();
  renderFileList();
}

function renderFileList() {
  const q = searchBox.value.trim().toLowerCase();
  const groups = new Map();
  let shown = 0;
  for (const f of allFiles) {
    if (q && !f.name.toLowerCase().includes(q)) continue;
    const k = groupKey(f.name);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(f);
    shown++;
  }
  statusEl.textContent = `${shown} / ${allFiles.length}`;
  listInner.innerHTML = '';
  for (const [k, files] of groups) {
    const det = document.createElement('details');
    det.className = 'mapfile-group';
    det.open = !!q && shown <= 300;
    const sm = document.createElement('summary');
    sm.textContent = `${k} (${files.length})`;
    det.appendChild(sm);
    // rows are created lazily on first open: 2000+ rows up front is slow on phones
    const fill = () => {
      if (det.dataset.filled) return;
      det.dataset.filled = '1';
      for (const f of files) {
        const row = document.createElement('div');
        row.className = 'mapfile-row' + (selected === f.path ? ' selected' : '');
        row.dataset.path = f.path;
        row.innerHTML = `${esc(f.name)}<span class="size">${(f.size / 1024).toFixed(0)}K</span>`;
        row.onclick = () => selectMap(f.path, row);
        det.appendChild(row);
      }
    };
    if (det.open) fill();
    det.addEventListener('toggle', () => { if (det.open) fill(); });
    listInner.appendChild(det);
  }
}
searchBox.addEventListener('input', renderFileList);

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

let lastResult = null;

async function selectMap(path, row) {
  selected = path;
  listInner.querySelectorAll('.mapfile-row.selected').forEach(e => e.classList.remove('selected'));
  if (row) row.classList.add('selected');
  mstatus.textContent = `${path}: ${t('map3d.loading')}`;
  if (isMobile()) showPane('mapViewport');
  let r;
  try {
    const res = await fetch(`/api/map?file=${encodeURIComponent(path)}`);
    r = await res.json();
    if (r.error) throw new Error(r.error);
  } catch (e) {
    mstatus.textContent = `${t('map3d.error')}: ${e.message}`;
    return;
  }
  if (selected !== path) return;
  lastResult = r;
  const nShapes = buildMap(r);
  mstatus.textContent = `${r.file}  ` + fmt(t('map3d.summary'), {
    n: r.nodes.filter(n => n.type === 1).length, p: r.parts.length, s: nShapes });
  renderInfo(r);
}

function fmtVec(v, d = 2) { return v.map(x => (+x).toFixed(d)).join(', '); }

function renderInfo(r) {
  const H = [];
  H.push(`<div>${esc(r.file)}</div>`);
  const nodes = r.nodes.filter(n => n.type === 1);
  const shapes = r.parts.reduce((a, p) => a + p.shapes.length, 0);
  H.push(`<div>${esc(fmt(t('map3d.summary'), { n: nodes.length, p: `${r.parts.length}/${r.partCount}`, s: shapes }))}</div>`);

  H.push(`<h3>${esc(t('map3d.chunks'))}</h3><div class="table-wrap"><table>`);
  for (const c of r.chunks) {
    const secs = (c.sections || []).map(s => `${s.magic}(${s.size})`).join(' ');
    H.push(`<tr><td>${esc(c.magic)}</td><td>${c.size}</td><td>${c.entries ?? ''}</td><td>${esc(secs)}</td></tr>`);
  }
  H.push('</table></div>');

  const pr = r.params || {};
  H.push(`<h3>${esc(t('map3d.params'))}</h3>`);
  if (pr.background) {
    const [cr, cg, cb] = pr.background.map(x => Math.round(x * 255));
    H.push(`<div>${esc(t('map3d.background'))}: <span style="display:inline-block;width:12px;height:12px;vertical-align:middle;background:rgb(${cr},${cg},${cb});border:1px solid #888"></span> ${fmtVec(pr.background, 3)}</div>`);
  }
  if (pr.camera) H.push(`<div>CAMR: ${fmtVec(pr.camera)}</div>`);
  if (r.collision && r.collision.count) {
    const c = r.collision;
    H.push(`<h3>${esc(t('map3d.collision'))}</h3><div>${esc(fmt(t('map3d.collCount'), { n: c.count }))}</div>`);
    H.push(`<div>min ${fmtVec(c.bboxMin, 1)} / max ${fmtVec(c.bboxMax, 1)}</div>`);
  }

  if (r.missingTextures && r.missingTextures.length) {
    H.push(`<h3>${esc(t('map3d.missingTextures'))}</h3><div>${esc(r.missingTextures.join(', '))}</div>`);
  }
  const extra = [];
  for (const p of r.parts) for (const s of p.shapes) {
    if ((s.textureBlend || []).some((b, i) => i > 0 && b !== 'unused')) extra.push(`${p.name}/${s.name}`);
  }
  if (extra.length) H.push(`<h3>${esc(t('map3d.extraStages'))}</h3><div>${esc(extra.join(', '))}</div>`);

  H.push(`<h3>${esc(t('map3d.nodes'))}</h3><div style="color:var(--muted)">${esc(t('map3d.nodeHint'))}</div>`);
  H.push(`<div class="table-wrap"><table><tr><th>#</th><th>${esc(t('map3d.colName'))}</th><th>${esc(t('map3d.colPart'))}</th><th>${esc(t('map3d.colPos'))}</th><th>${esc(t('map3d.colRotY'))}</th><th>${esc(t('map3d.colScale'))}</th></tr>`);
  r.nodes.forEach((n, i) => {
    if (n.type !== 1) return;
    const rotY = (n.rotation[1] * 180 / Math.PI).toFixed(1);
    const sc = n.scale[0] === n.scale[1] && n.scale[1] === n.scale[2] ? (+n.scale[0]).toFixed(2) : fmtVec(n.scale);
    H.push(`<tr class="node-row" data-node="${i}"><td>${i}</td><td>${esc(n.name)}</td><td>${n.part}</td><td>${fmtVec(n.translation, 1)}</td><td>${rotY}</td><td>${sc}</td></tr>`);
  });
  H.push('</table></div>');
  H.push(`<h3>${esc(t('map3d.textures'))} (${r.textures.length})</h3><div>${esc(r.textures.join(', '))}</div>`);
  infoEl.innerHTML = H.join('');
  infoEl.querySelectorAll('tr.node-row').forEach(tr => tr.addEventListener('click', () => focusNode(+tr.dataset.node, tr)));
}

function focusNode(ni, tr) {
  infoEl.querySelectorAll('tr.node-row.selected').forEach(e => e.classList.remove('selected'));
  if (tr) tr.classList.add('selected');
  for (const hg of boxGroup.children) {
    const on = hg.userData.nodeIndex === ni;
    hg.children[0].material.color.set(on ? 0xff3366 : 0xffcc33);
    hg.visible = boxesMode || on;
  }
  boxGroup.visible = true;
  const grp = mapGroup.children.find(g => g.userData.nodeIndex === ni);
  const hg = boxGroup.children.find(g => g.userData.nodeIndex === ni);
  if (isMobile()) showPane('mapViewport');
  const target = (grp && grp.children.length) ? grp : hg;
  if (target) frameBox(new THREE.Box3().setFromObject(target));
}

// ---- toolbar -------------------------------------------------------------------
function toggle(id, get, set, after) {
  const b = document.getElementById(id);
  b.addEventListener('click', () => { set(!get()); b.classList.toggle('active', get()); after(); });
}
toggle('btnTex', () => texMode, v => { texMode = v; }, rebuildMaterials);
toggle('btnVColor', () => vcolMode, v => { vcolMode = v; }, rebuildMaterials);
toggle('btnWire', () => wireframe, v => { wireframe = v; }, rebuildMaterials);
toggle('btnBoxes', () => boxesMode, v => { boxesMode = v; }, () => {
  for (const hg of boxGroup.children) { hg.visible = boxesMode; hg.children[0].material.color.set(0xffcc33); }
  boxGroup.visible = boxesMode;
});
toggle('btnColl', () => collMode, v => { collMode = v; }, () => { collGroup.visible = collMode; });
document.getElementById('btnReset').addEventListener('click', frameAll);

initThree();
loadFiles().catch(e => { listInner.textContent = `${t('map3d.error')}: ${e.message}`; });
