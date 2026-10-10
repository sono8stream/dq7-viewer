// Headless check for the マップ3D viewer (static/map3d.js).
//
// Same approach as test_model_render.mjs (no GPU available): rebuild the
// map exactly as map3d.js does - each part's shapes instanced under a
// Group carrying the GNOD translation / rotation('XYZ') / scale - frame the
// camera the same way (collision extent, else all geometry), and fire a ray
// grid through the viewport. Also asserts:
//   - every node's part-local bbox contains the part's vertices (i.e. the
//     node really instances that geometry). Skinned parts (bone-animated
//     objects, e.g. wld_n25a's tbtb01) are only warned about: their
//     bind-pose vertices can legitimately exceed the node's static bbox.
//   - every texture a shape references resolves via /api/map/texture.
//
// Usage:  node webapp/test_map_render.mjs [http://127.0.0.1:8000] [MAPDATA/x.pack.lz ...]
// Exits non-zero on any failure.

import * as THREE from 'three';

const BASE = (process.argv[2] && process.argv[2].startsWith('http'))
  ? process.argv[2] : 'http://127.0.0.1:8000';
const CLI_FILES = process.argv.slice(2).filter(a => !a.startsWith('http'));
const FILES = CLI_FILES.length ? CLI_FILES : [
  'MAPDATA/c01nout.pack.lz',
  'MAPDATA/wld_n25a.pack.lz',
  'MAPDATA/h01nout1.pack.lz',
  'MAPDATA/a_boroship_1.pack.lz',
];

const GRID = 40;
// low on purpose: a long winding dungeon (e.g. d03nf1) legitimately covers
// only ~7% of its own bounding-box framing; this only catches "nothing on
// screen" (wrong transform / framing), not composition.
const MIN_HIT_RATIO = 0.03;

let failures = 0;
const log = (...a) => console.log(...a);
const fail = (f, msg) => { failures++; console.error(`  FAIL [${f}] ${msg}`); };

function buildMap(r) {
  const root = new THREE.Group();
  const geoms = new Map();
  for (const p of r.parts) {
    geoms.set(p.index, p.shapes.filter(s => s.positions && s.positions.length >= 9).map(s => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(s.positions, 3));
      if (s.indices && s.indices.length >= 3) g.setIndex(s.indices);
      g.computeBoundingBox(); g.computeBoundingSphere();
      g.userData.skinned = !!s.skinned;
      return g;
    }));
  }
  const mat = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
  for (const n of r.nodes) {
    if (n.type !== 1) continue;
    const grp = new THREE.Group();
    grp.position.set(...n.translation);
    grp.rotation.set(n.rotation[0], n.rotation[1], n.rotation[2], 'XYZ');
    grp.scale.set(...n.scale);
    grp.userData.node = n;
    for (const g of (geoms.get(n.part) || [])) grp.add(new THREE.Mesh(g, mat));
    root.add(grp);
  }
  root.updateMatrixWorld(true);
  return root;
}

async function checkFile(file) {
  const res = await fetch(`${BASE}/api/map?file=${encodeURIComponent(file)}`);
  if (!res.ok) { fail(file, `HTTP ${res.status}`); return; }
  const r = await res.json();
  if (r.error) { fail(file, r.error); return; }
  const nodes = r.nodes.filter(n => n.type === 1);
  const shapes = r.parts.reduce((a, p) => a + p.shapes.length, 0);
  if (!nodes.length) fail(file, 'no part nodes');
  if (!shapes) fail(file, 'no shapes');

  const root = buildMap(r);

  // node bbox (part-local) must contain the part's own vertices
  let bboxBad = 0;
  const skinnedOut = new Set();
  for (const grp of root.children) {
    const n = grp.userData.node;
    const nb = new THREE.Box3(new THREE.Vector3(...n.bboxMin), new THREE.Vector3(...n.bboxMax)).expandByScalar(0.05);
    for (const m of grp.children) {
      if (nb.containsBox(m.geometry.boundingBox)) continue;
      if (m.geometry.userData.skinned) skinnedOut.add(n.name); else bboxBad++;
      break;
    }
  }
  if (bboxBad) fail(file, `${bboxBad} node(s) whose part geometry lies outside the node bbox`);
  if (skinnedOut.size) log(`  warn [${file}] skinned part(s) exceed node bbox: ${[...skinnedOut].join(', ')}`);

  // textures
  const names = new Set();
  for (const p of r.parts) for (const s of p.shapes) if (s.textures) names.add(s.textures[0]);
  let texBad = 0;
  for (const nm of names) {
    if ((r.missingTextures || []).includes(nm)) continue;   // reported as outside this pack
    const tr = await fetch(`${BASE}/api/map/texture?file=${encodeURIComponent(file)}&name=${encodeURIComponent(nm)}`);
    if (!tr.ok || !(tr.headers.get('content-type') || '').includes('png')) texBad++;
    await tr.arrayBuffer();
  }
  if (texBad) fail(file, `${texBad}/${names.size} textures failed to load`);

  // framing (same rule as map3d.js frameAll) + ray grid
  const c = r.collision;
  const box = (c && c.bboxMin) ? new THREE.Box3(new THREE.Vector3(...c.bboxMin), new THREE.Vector3(...c.bboxMax))
    : new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
  const cam = new THREE.PerspectiveCamera(45, 4 / 3, Math.max(radius / 500, 0.01), radius * 50);
  cam.position.copy(center).add(new THREE.Vector3(radius * 0.9, radius * 0.9, radius * 1.2));
  cam.lookAt(center);
  cam.updateMatrixWorld(); cam.updateProjectionMatrix();
  const rc = new THREE.Raycaster();
  let hits = 0;
  for (let y = 0; y < GRID; y++) for (let x = 0; x < GRID; x++) {
    rc.setFromCamera(new THREE.Vector2((x + 0.5) / GRID * 2 - 1, (y + 0.5) / GRID * 2 - 1), cam);
    if (rc.intersectObject(root, true).length) hits++;
  }
  const ratio = hits / (GRID * GRID);
  if (ratio < MIN_HIT_RATIO) fail(file, `map covers only ${(ratio * 100).toFixed(1)}% of the view`);
  log(`  ${file}: nodes=${nodes.length} parts=${r.parts.length} shapes=${shapes} textures=${names.size}` +
      ` missing=${(r.missingTextures || []).length} coll=${c ? c.count : '-'} coverage=${(ratio * 100).toFixed(0)}%`);
}

for (const f of FILES) {
  try { await checkFile(f); } catch (e) { fail(f, e.stack || e.message); }
}
log(failures ? `${failures} failure(s)` : 'all OK');
process.exit(failures ? 1 : 0);
