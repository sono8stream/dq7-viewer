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
//   fragBlend  {mode, src, dst, ...} GfxFragOpBlend (bcmdl._frag_blend)
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
      'map3d.coll_floor': '床',
      'map3d.coll_wall': '壁',
      'map3d.coll_exit': '出口',
      'map3d.coll_event': 'イベント床',
      'map3d.coll_special': '番号付きの壁',
      'map3d.collHint': '下の「コリジョン」ボタンで表示を切り替え',
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
      'map3d.genGroup': '生成マップ (generated_maps)',
      'map3d.modeMaps': 'マップ',
      'map3d.modeParts': '部品',
      'map3d.partSearchPlaceholder': '部品名で絞り込み（例: tubo, wd0, kb）...',
      'map3d.partsBuilding': '部品の索引を作成中... {done} / {total} パック（初回のみ、数分）',
      'map3d.partsCount': '{shown} / {total} 部品',
      'map3d.partsMore': 'ほか {n} 件。名前で絞り込んでください',
      'map3d.partUses': '{n} 回配置',
      'map3d.partPacks': 'この部品を置いているパック（{n}）',
      'map3d.partPackHint': 'パック名: その部品を表示 / 「マップ」: マップ全体を開く',
      'map3d.openMap': 'マップ',
      'map3d.partSize': '大きさ (x, y, z)',
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
      'map3d.coll_floor': 'floor',
      'map3d.coll_wall': 'wall',
      'map3d.coll_exit': 'exit',
      'map3d.coll_event': 'event floor',
      'map3d.coll_special': 'numbered wall',
      'map3d.collHint': 'toggle with the "Collision" button below',
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
      'map3d.genGroup': 'Generated maps (generated_maps)',
      'map3d.modeMaps': 'Maps',
      'map3d.modeParts': 'Parts',
      'map3d.partSearchPlaceholder': 'Filter by part name (e.g. tubo, wd0, kb)...',
      'map3d.partsBuilding': 'Building the parts index... {done} / {total} packs (first time only, a few minutes)',
      'map3d.partsCount': '{shown} / {total} parts',
      'map3d.partsMore': '{n} more - narrow the filter',
      'map3d.partUses': 'placed {n}x',
      'map3d.partPacks': 'Packs placing this part ({n})',
      'map3d.partPackHint': 'pack name: show the part from it / "map": open the whole map',
      'map3d.openMap': 'map',
      'map3d.partSize': 'Size (x, y, z)',
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
  updateBillboards();
  renderer.render(scene, camera);
}

// ---- billboard bones -----------------------------------------------------------
// Vertices bound to a bone whose GfxBone BillboardMode (+0xD4) is not Off turn
// to the camera at draw time (map trees: the leaf cards). Same basis as
// SPICA.Rendering's Mesh: Z = toward the camera position for the Viewpoint
// modes (3/5/7) or the view axis (2/4/6); Y = the model's up (World/YAxial)
// or the bone's own Euler-rotated up on the screen (Screen 4/5); X = Y x Z,
// then Y = Z x X. The geometry holds the vertices in bone space, scaled by
// the bone's scale (see splitBillboards); each frame every instance gets
// [X Y Z] * node scale at the bone's position.
let billboards = [];   // {mesh, mode, pivot: Vector3 (model), upView: Vector3|null, nodes: [Matrix4]}
const _bbP = new THREE.Vector3(), _bbX = new THREE.Vector3(), _bbY = new THREE.Vector3(), _bbZ = new THREE.Vector3();
const _bbR = new THREE.Vector3(), _bbU = new THREE.Vector3(), _bbB = new THREE.Vector3(), _bbS = new THREE.Vector3();
const _bbM = new THREE.Matrix4();
function updateBillboards() {
  if (!billboards.length) return;
  camera.updateMatrixWorld();
  _bbR.setFromMatrixColumn(camera.matrixWorld, 0).normalize();
  _bbU.setFromMatrixColumn(camera.matrixWorld, 1).normalize();
  _bbB.setFromMatrixColumn(camera.matrixWorld, 2).normalize();   // view +Z (toward the viewer)
  for (const bb of billboards) {
    bb.nodes.forEach((nm, k) => {
      _bbP.copy(bb.pivot).applyMatrix4(nm);
      if (bb.mode === 3 || bb.mode === 5 || bb.mode === 7) _bbZ.copy(camera.position).sub(_bbP).normalize();
      else _bbZ.copy(_bbB);
      if (bb.upView) _bbY.set(0, 0, 0).addScaledVector(_bbR, bb.upView.x).addScaledVector(_bbU, bb.upView.y).addScaledVector(_bbB, bb.upView.z);
      else _bbY.setFromMatrixColumn(nm, 1).normalize();
      _bbX.crossVectors(_bbY, _bbZ);
      if (_bbX.lengthSq() < 1e-12) _bbX.crossVectors(_bbU, _bbZ);   // looking along the up axis (from straight above)
      _bbX.normalize();
      _bbY.crossVectors(_bbZ, _bbX).normalize();
      _bbS.setFromMatrixScale(nm);
      const sc = (_bbS.x + _bbS.y + _bbS.z) / 3;
      _bbM.makeBasis(_bbX.multiplyScalar(sc), _bbY.multiplyScalar(sc), _bbZ.multiplyScalar(sc)).setPosition(_bbP);
      bb.mesh.setMatrixAt(k, _bbM);
    });
    bb.mesh.instanceMatrix.needsUpdate = true;
  }
}

// Split a shape into its non-billboard part and one sub-shape per billboard
// bone, the latter moved to bone space: local = inverse(bind world) * p,
// times the bone's scale (column norms of the bind world 3x3).
function splitBillboards(s) {
  const bbb = s.billboardBones;
  if (!bbb || !s.skinIndex || !s.indices) return null;
  const nv = s.positions.length / 3;
  const boneOf = new Int32Array(nv);
  for (let i = 0; i < nv; i++) boneOf[i] = s.skinIndex[i * 4];
  const subs = new Map();   // bone -> triangle list
  const rest = [];
  for (let t = 0; t < s.indices.length; t += 3) {
    const a = s.indices[t], b = s.indices[t + 1], c = s.indices[t + 2];
    const k = String(boneOf[a]);
    if (bbb[k] && boneOf[b] === boneOf[a] && boneOf[c] === boneOf[a]) {
      if (!subs.has(k)) subs.set(k, []);
      subs.get(k).push(a, b, c);
    } else rest.push(a, b, c);
  }
  const pick = (tris, xform) => {
    const map = new Map(), out = { ...s, positions: [], indices: [], uvs: s.uvs ? [] : undefined,
      uvs1: s.uvs1 ? [] : undefined, uvs2: s.uvs2 ? [] : undefined, colors: s.colors ? [] : undefined };
    for (const v of tris) {
      if (!map.has(v)) {
        map.set(v, map.size);
        const p = xform(s.positions[v * 3], s.positions[v * 3 + 1], s.positions[v * 3 + 2]);
        out.positions.push(p[0], p[1], p[2]);
        for (const key of ['uvs', 'uvs1', 'uvs2']) if (out[key]) out[key].push(s[key][v * 2], s[key][v * 2 + 1]);
        if (out.colors) out.colors.push(s.colors[v * 4], s.colors[v * 4 + 1], s.colors[v * 4 + 2], s.colors[v * 4 + 3]);
      }
      out.indices.push(map.get(v));
    }
    return out;
  };
  const parts = { rest: rest.length ? pick(rest, (x, y, z) => [x, y, z]) : null, bones: [] };
  for (const [k, tris] of subs) {
    const m = bbb[k].world;   // row-major 3x4: x' = x*m0 + y*m1 + z*m2 + m3 ...
    const A = new THREE.Matrix3().set(m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]);
    const sc = [Math.hypot(m[0], m[4], m[8]), Math.hypot(m[1], m[5], m[9]), Math.hypot(m[2], m[6], m[10])];
    const inv = A.clone().invert();
    const v = new THREE.Vector3();
    const sub = pick(tris, (x, y, z) => {
      v.set(x - m[3], y - m[7], z - m[11]).applyMatrix3(inv);
      return [v.x * sc[0], v.y * sc[1], v.z * sc[2]];
    });
    let upView = null;
    if (bbb[k].mode === 4 || bbb[k].mode === 5) {
      // SPICA: BoneMtx = Rx * Ry * Rz (row vectors) -> its Y row
      const r = bbb[k].rotation || [0, 0, 0];
      const e = new THREE.Euler(r[0], r[1], r[2], 'ZYX');
      upView = new THREE.Vector3(0, 1, 0).applyEuler(e);
    }
    parts.bones.push({ shape: sub, mode: bbb[k].mode, pivot: new THREE.Vector3(m[3], m[7], m[11]), upView });
  }
  return parts;
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

// GfxFragOpBlend factors / equations (bcmdl._frag_blend) -> three.js
const _BF = {
  zero: THREE.ZeroFactor, one: THREE.OneFactor, srcColor: THREE.SrcColorFactor,
  oneMinusSrcColor: THREE.OneMinusSrcColorFactor, dstColor: THREE.DstColorFactor,
  oneMinusDstColor: THREE.OneMinusDstColorFactor, srcAlpha: THREE.SrcAlphaFactor,
  oneMinusSrcAlpha: THREE.OneMinusSrcAlphaFactor, dstAlpha: THREE.DstAlphaFactor,
  oneMinusDstAlpha: THREE.OneMinusDstAlphaFactor, srcAlphaSaturate: THREE.SrcAlphaSaturateFactor,
};
const _BE = {
  add: THREE.AddEquation, subtract: THREE.SubtractEquation,
  reverseSubtract: THREE.ReverseSubtractEquation, min: THREE.MinEquation, max: THREE.MaxEquation,
};

// One material per part shape, shared by every node instancing that part.
function makeMaterial(s) {
  const at = s.alphaTest;
  const useVC = vcolMode && s.vertexColor === 'modulate' && !!s.colors;
  const m = new THREE.MeshBasicMaterial({
    color: texMode ? 0xffffff : 0xb8c4d0,
    vertexColors: useVC,
    side: _SIDE[s.side] ?? THREE.DoubleSide,
    wireframe,
    // GfxAlphaTest: discard below reference (Greater/Gequal).
    alphaTest: (texMode && at && at.enabled) ? Math.max(at.reference / 255, 0.01) : 0,
  });
  // GfxFragOpBlend (bcmdl._frag_blend): frame-buffer blending as the
  // material sets it - water, ground shadows (SrcAlpha / 1-SrcAlpha), glows
  // (SrcAlpha / One). Blended surfaces are sorted and don't write depth.
  const fb = s.fragBlend;
  if (texMode && fb && (fb.mode === 'blend' || fb.mode === 'blendSeparate')
      && _BF[fb.src] !== undefined && _BF[fb.dst] !== undefined) {
    m.transparent = true;
    m.depthWrite = false;
    m.blending = THREE.CustomBlending;
    m.blendSrc = _BF[fb.src];
    m.blendDst = _BF[fb.dst];
    m.blendEquation = _BE[fb.colorEq] ?? THREE.AddEquation;
    if (fb.mode === 'blendSeparate') {
      m.blendSrcAlpha = _BF[fb.alphaSrc] ?? null;
      m.blendDstAlpha = _BF[fb.alphaDst] ?? null;
      m.blendEquationAlpha = _BE[fb.alphaEq] ?? null;
    }
  }
  return m;
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
  boxNodes = null;
}

// PLGN record -> class for colouring (docs/formats/models/map_pack.md COLL):
// +0x04 u16 kind (0 wall, 1/2 floor, 3 event floor, 4 numbered wall),
// +0x0c u16 1 = exit (DQMapManager::setupExitInfo, exit id at +0x0a)
const COLL_CLASSES = [
  { key: 'floor', color: 0x33ff66 },
  { key: 'wall', color: 0xff9933 },
  { key: 'exit', color: 0xff3355 },
  { key: 'event', color: 0x3399ff },
  { key: 'special', color: 0xcc66ff },
];
function collClass(attr) {
  const kind = attr[1] & 0xffff;
  if ((attr[3] & 0xffff) === 1) return 2;
  if (kind === 1 || kind === 2) return 0;
  if (kind === 3) return 3;
  if (kind === 4) return 4;
  return 1;
}

function buildCollision(c) {
  if (!c || !c.positions || !c.positions.length) return;
  collBox = new THREE.Box3(new THREE.Vector3(...c.bboxMin), new THREE.Vector3(...c.bboxMax));
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(c.positions, 3));
  const nt = c.positions.length / 9;
  const col = new Float32Array(nt * 9);
  const tmp = new THREE.Color();
  for (let k = 0; k < nt; k++) {
    const attr = (c.attrs || [])[(c.triPoly || [])[k]] || [0, 1, 0, 0];
    tmp.setHex(COLL_CLASSES[collClass(attr)].color);
    for (let v = 0; v < 3; v++) col.set([tmp.r, tmp.g, tmp.b], k * 9 + v * 3);
  }
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  // polygon offset pulls the overlay in front of coplanar floor geometry
  collGroup.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.35, side: THREE.DoubleSide,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4,
  })));
  const lines = new THREE.LineSegments(new THREE.WireframeGeometry(g),
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7 }));
  collGroup.add(lines);
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

const INSTANCE_MIN = 8;
const _q = new THREE.Quaternion(), _e = new THREE.Euler(), _v = new THREE.Vector3(), _sv = new THREE.Vector3();
// GNOD -> local matrix. Euler order: only Y rotations occur in the data seen
// so far, so the X/Y/Z composition order is not yet confirmed.
function nodeMatrix(n) {
  _e.set(n.rotation[0], n.rotation[1], n.rotation[2], 'XYZ');
  return new THREE.Matrix4().compose(_v.set(...n.translation), _q.setFromEuler(_e), _sv.set(...n.scale));
}

// Node boxes are only built when first needed (toggle / node focus): one
// Box3Helper per node is wasted work for maps with thousands of trees.
let boxNodes = null;
function ensureBoxes() {
  if (boxGroup.children.length || !boxNodes) return;
  boxNodes.forEach((n, ni) => {
    if (n.type !== 1) return;
    const box = new THREE.Box3(new THREE.Vector3(...n.bboxMin), new THREE.Vector3(...n.bboxMax));
    const hg = new THREE.Group();
    hg.matrixAutoUpdate = false;
    hg.matrix.copy(nodeMatrix(n));
    hg.add(new THREE.Box3Helper(box, 0xffcc33));
    hg.userData.nodeIndex = ni;
    hg.visible = boxesMode;
    boxGroup.add(hg);
  });
}

function buildMap(r) {
  disposeMap();
  currentFile = r.file;
  const gen = ++buildGen;
  framed = false;

  const bg = r.params && r.params.background;
  scene.background = new THREE.Color(DEFAULT_BG);
  if (bg && bg.length >= 3) scene.background.setRGB(bg[0], bg[1], bg[2], THREE.SRGBColorSpace);

  billboards = [];
  for (const p of r.parts) {
    const list = [];
    for (const s of p.shapes) {
      if (!s.positions || s.positions.length < 9) continue;
      const split = splitBillboards(s);
      if (!split) {
        list.push({ shape: s, geometry: buildPartGeometry(s), material: makeMaterial(s), meshes: [] });
        continue;
      }
      if (split.rest) list.push({ shape: split.rest, geometry: buildPartGeometry(split.rest), material: makeMaterial(s), meshes: [] });
      for (const b of split.bones) {
        list.push({ shape: b.shape, geometry: buildPartGeometry(b.shape), material: makeMaterial(s), meshes: [], billboard: b });
      }
    }
    partShapes.set(p.index, list);
  }

  // Parts placed many times (trees: ~1800 in a generated DQ4 region, rocks,
  // shallows) are drawn as one THREE.InstancedMesh per shape - one draw call
  // instead of one per node, which keeps phones responsive. Rarely used
  // parts keep one Group per node.
  const byPart = new Map();
  r.nodes.forEach((n, ni) => {
    if (n.type !== 1) return;
    if (!byPart.has(n.part)) byPart.set(n.part, []);
    byPart.get(n.part).push(ni);
  });
  let nShapes = 0;
  for (const [part, nis] of byPart) {
    const shapes = partShapes.get(part) || [];
    for (const ps of shapes) {
      if (!ps.billboard) continue;
      // billboard sub-shapes: always instanced, matrices set each frame
      const im = new THREE.InstancedMesh(ps.geometry, ps.material, nis.length);
      im.frustumCulled = false;
      im.userData.nodeIndices = nis;
      ps.meshes.push(im);
      mapGroup.add(im);
      billboards.push({ mesh: im, mode: ps.billboard.mode, pivot: ps.billboard.pivot, upView: ps.billboard.upView,
                        nodes: nis.map(ni => nodeMatrix(r.nodes[ni])) });
      nShapes += nis.length;
    }
    if (nis.length >= INSTANCE_MIN) {
      for (const ps of shapes) {
        if (ps.billboard) continue;
        const im = new THREE.InstancedMesh(ps.geometry, ps.material, nis.length);
        nis.forEach((ni, k) => im.setMatrixAt(k, nodeMatrix(r.nodes[ni])));
        im.instanceMatrix.needsUpdate = true;
        im.computeBoundingSphere();
        im.computeBoundingBox();
        im.userData.nodeIndices = nis;
        ps.meshes.push(im);
        mapGroup.add(im);
        nShapes += nis.length;
      }
      continue;
    }
    for (const ni of nis) {
      const n = r.nodes[ni];
      const grp = new THREE.Group();
      grp.name = n.name;
      grp.matrixAutoUpdate = false;
      grp.matrix.copy(nodeMatrix(n));
      grp.userData.nodeIndex = ni;
      for (const ps of shapes) {
        if (ps.billboard) continue;
        const m = new THREE.Mesh(ps.geometry, ps.material);
        ps.meshes.push(m);
        grp.add(m);
        nShapes++;
      }
      mapGroup.add(grp);
    }
  }
  boxNodes = r.nodes;
  if (boxesMode) ensureBoxes();
  buildCollision(r.collision);
  applyTextures(gen);
  frameAll();
  return nShapes;
}

// ---- file list -----------------------------------------------------------------
let allFiles = [];
let selected = null;

function groupKey(name, f) {
  if (f && f.generated) return t('map3d.genGroup');
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

// ---- parts mode: every part placed by any pack, looked at one at a time ------------
let listMode = 'maps';
let partsIndex = null;
let partsPoll = null;
const PARTS_SHOWN = 300;

async function loadPartsIndex() {
  const res = await fetch('/api/map_parts');
  const r = await res.json();
  if (r.state === 'ready') {
    partsIndex = r.parts;
    renderFileList();
    return;
  }
  listInner.innerHTML = r.state === 'error'
    ? `<div class="empty">${esc(t('map3d.error'))}: ${esc(r.error || '')}</div>`
    : `<div class="empty">${esc(fmt(t('map3d.partsBuilding'), { done: r.done, total: r.total || '?' }))}</div>`;
  if (r.state === 'building' && listMode === 'parts') {
    clearTimeout(partsPoll);
    partsPoll = setTimeout(() => loadPartsIndex().catch(() => {}), 3000);
  }
}

function renderPartList() {
  const q = searchBox.value.trim().toLowerCase();
  const hits = partsIndex.filter(e => !q || e.name.toLowerCase().includes(q));
  statusEl.textContent = fmt(t('map3d.partsCount'), { shown: hits.length, total: partsIndex.length });
  listInner.innerHTML = '';
  for (const e of hits.slice(0, PARTS_SHOWN)) {
    const row = document.createElement('div');
    row.className = 'mapfile-row' + (selected === 'part:' + e.name ? ' selected' : '');
    row.innerHTML = `${esc(e.name)}<span class="size">${esc(fmt(t('map3d.partUses'), { n: e.uses }))}</span>`;
    row.onclick = () => selectPart(e, e.packs[0][0], row);
    listInner.appendChild(row);
  }
  if (hits.length > PARTS_SHOWN) {
    const more = document.createElement('div');
    more.className = 'empty';
    more.textContent = fmt(t('map3d.partsMore'), { n: hits.length - PARTS_SHOWN });
    listInner.appendChild(more);
  }
}

async function selectPart(e, pack, row) {
  selected = 'part:' + e.name;
  listInner.querySelectorAll('.mapfile-row.selected').forEach(x => x.classList.remove('selected'));
  if (row) row.classList.add('selected');
  mstatus.textContent = `${e.name} (${pack}): ${t('map3d.loading')}`;
  if (isMobile()) showPane('mapViewport');
  let r;
  try {
    const res = await fetch(`/api/map?file=${encodeURIComponent(pack)}&part=${encodeURIComponent(e.name)}`);
    r = await res.json();
    if (r.error) throw new Error(r.error);
  } catch (err) {
    mstatus.textContent = `${t('map3d.error')}: ${err.message}`;
    return;
  }
  if (selected !== 'part:' + e.name) return;
  lastResult = r;
  const nShapes = buildMap(r);
  mstatus.textContent = `${e.name}  ${pack}  ` + fmt(t('map3d.summary'), { n: 1, p: r.parts.length, s: nShapes });
  renderInfo(r, e);
}

function setListMode(mode) {
  listMode = mode;
  document.querySelectorAll('#mapModeBtns button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  searchBox.placeholder = t(mode === 'parts' ? 'map3d.partSearchPlaceholder' : 'map3d.searchPlaceholder');
  if (mode === 'parts' && !partsIndex) {
    loadPartsIndex().catch(err => { listInner.textContent = `${t('map3d.error')}: ${err.message}`; });
    return;
  }
  renderFileList();
}
document.querySelectorAll('#mapModeBtns button').forEach(b => b.addEventListener('click', () => setListMode(b.dataset.mode)));

function renderFileList() {
  if (listMode === 'parts') { if (partsIndex) renderPartList(); return; }
  const q = searchBox.value.trim().toLowerCase();
  const groups = new Map();
  let shown = 0;
  for (const f of allFiles) {
    if (q && !f.name.toLowerCase().includes(q)) continue;
    const k = groupKey(f.name, f);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(f);
    shown++;
  }
  statusEl.textContent = `${shown} / ${allFiles.length}`;
  listInner.innerHTML = '';
  for (const [k, files] of groups) {
    const det = document.createElement('details');
    det.className = 'mapfile-group';
    det.open = (!!q && shown <= 300) || files.some(f => f.generated);
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

function renderInfo(r, partEntry) {
  const H = [];
  H.push(`<div>${esc(r.file)}${r.part ? ' / ' + esc(r.part) : ''}</div>`);
  if (partEntry) {
    // which packs place this part: tap a pack to see its copy (same name is
    // normally the same model, but not guaranteed), or open that whole map
    H.push(`<div>${esc(t('map3d.partSize'))}: ${fmtVec(partEntry.size)}</div>`);
    H.push(`<h3>${esc(fmt(t('map3d.partPacks'), { n: partEntry.packs.length }))}</h3>`);
    H.push(`<div style="color:var(--muted)">${esc(t('map3d.partPackHint'))}</div><div class="table-wrap"><table>`);
    partEntry.packs.forEach(([path, n], i) => {
      H.push(`<tr><td><a href="#" data-part-pack="${i}">${esc(path)}</a></td><td>${n}</td>`
        + `<td><a href="#" data-open-map="${i}">${esc(t('map3d.openMap'))}</a></td></tr>`);
    });
    H.push('</table></div>');
  }
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
    const counts = COLL_CLASSES.map(() => 0);
    for (const a of c.attrs || []) counts[collClass(a)]++;
    H.push('<div>' + COLL_CLASSES.map((cl, i) => counts[i] ? `<span style="display:inline-block;width:10px;height:10px;background:#${cl.color.toString(16).padStart(6, '0')};margin:0 3px 0 8px;vertical-align:middle"></span>${esc(t('map3d.coll_' + cl.key))} ${counts[i]}` : '').join('') + '</div>');
    H.push(`<div style="color:var(--muted)">${esc(t('map3d.collHint'))}</div>`);
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
  if (partEntry) {
    infoEl.querySelectorAll('a[data-part-pack]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      selectPart(partEntry, partEntry.packs[+a.dataset.partPack][0], null);
    }));
    infoEl.querySelectorAll('a[data-open-map]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      selectMap(partEntry.packs[+a.dataset.openMap][0], null);
    }));
  }
}

function focusNode(ni, tr) {
  infoEl.querySelectorAll('tr.node-row.selected').forEach(e => e.classList.remove('selected'));
  if (tr) tr.classList.add('selected');
  ensureBoxes();
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
  if (boxesMode) ensureBoxes();
  for (const hg of boxGroup.children) { hg.visible = boxesMode; hg.children[0].material.color.set(0xffcc33); }
  boxGroup.visible = boxesMode;
});
toggle('btnColl', () => collMode, v => { collMode = v; }, () => { collGroup.visible = collMode; });
document.getElementById('btnReset').addEventListener('click', frameAll);

initThree();
loadFiles().catch(e => { listInner.textContent = `${t('map3d.error')}: ${e.message}`; });
