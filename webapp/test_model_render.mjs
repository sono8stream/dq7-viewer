// Headless render check for the モデル viewer.
//
// The device can't build headless-gl (no NDK), so instead of a GPU draw
// this reproduces model.js's geometry build + camera framing with three's
// pure-JS classes and fires a grid of rays from the framed camera through
// the viewport. If a healthy fraction of rays hit the mesh, the model
// would be visible on screen. Also asserts the geometry invariants the
// renderer relies on.
//
// Usage:  node webapp/test_model_render.mjs [http://127.0.0.1:8000] [file ...]
// Exits non-zero on any failure.

import * as THREE from 'three';

const BASE = (process.argv[2] && process.argv[2].startsWith('http'))
  ? process.argv[2] : 'http://127.0.0.1:8000';
const CLI_FILES = process.argv.slice(2).filter(a => !a.startsWith('http'));
const FILES = CLI_FILES.length ? CLI_FILES : [
  'MONSTER/e001.bcmdl.lz',
  'MONSTER/e002.bcmdl.lz',
  'MONSTER/e050.bcmdl.lz',
  'CHARACTER/p0001_j00.bcmdl.lz',
];

const GRID = 48;            // ray grid resolution (GRID x GRID)
const MIN_HIT_RATIO = 0.04; // model must cover at least this fraction of rays
const MAX_HIT_RATIO = 0.98; // ...and not (near-)fill the whole viewport

let failures = 0;
const log = (...a) => console.log(...a);
const fail = (f, msg) => { failures++; console.error(`  FAIL [${f}] ${msg}`); };

// --- mirror of model.js buildMeshes(): shapes -> array of THREE.Mesh -----
function buildMeshes(shapes) {
  const meshes = [];
  for (const s of shapes) {
    if (!s.ok || !s.positions || s.positions.length < 9) continue;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(s.positions, 3));
    if (s.normals && s.normals.length === s.positions.length)
      g.setAttribute('normal', new THREE.Float32BufferAttribute(s.normals, 3));
    if (s.indices && s.indices.length >= 3) g.setIndex(s.indices);
    if (!g.getAttribute('normal')) g.computeVertexNormals();
    meshes.push(new THREE.Mesh(g, new THREE.MeshBasicMaterial()));
  }
  return meshes;
}

// --- mirror of model.js frameObject(): position the camera -------------
function frameCamera(group) {
  const box = new THREE.Box3().setFromObject(group);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
  const cam = new THREE.PerspectiveCamera(45, 1, radius / 100, radius * 100);
  cam.position.copy(center).add(new THREE.Vector3(radius * 2.2, radius * 1.6, radius * 2.6));
  cam.lookAt(center);
  cam.updateMatrixWorld(true);
  return { cam, box, size, center, radius };
}

async function checkFile(file) {
  const res = await fetch(`${BASE}/api/model?file=${encodeURIComponent(file)}`);
  if (!res.ok) { fail(file, `HTTP ${res.status}`); return; }
  const data = await res.json();
  if (data.error) { fail(file, `api error: ${data.error}`); return; }

  const shapes = (data.geometry && data.geometry.shapes) || [];
  const okShapes = shapes.filter(s => s.ok);
  if (!okShapes.length) { fail(file, 'no decoded shapes'); return; }

  // textures: every shape should resolve to a texture name, and each
  // embedded TXOB should decode to a real PNG via /api/model/texture
  const texNames = new Set((data.textures || []).map(t => t.name));
  const untextured = okShapes.filter(s => !s.texture).length;
  if (data.textures && data.textures.length && untextured === okShapes.length)
    fail(file, `model has ${data.textures.length} textures but no shape resolved one`);
  let multiTex = 0;
  for (const s of okShapes) {
    if (s.texture && !texNames.has(s.texture))
      fail(file, `shape ${s.name || s.offset} references unknown texture ${s.texture}`);
    for (const tn of (s.textures || []))
      if (!texNames.has(tn))
        fail(file, `shape ${s.name || s.offset} stage texture ${tn} unknown`);
    if ((s.textures || []).length > 1) {
      multiTex++;
      // extra stages need their own UV set (uv1/uv2) to composite
      if (!s.uvs1)
        fail(file, `shape ${s.name || s.offset} has ${s.textures.length} texture stages but no uvs1`);
    }
  }
  let texChecked = 0;
  for (const t of (data.textures || [])) {
    if (!t.ok) continue;
    const tr = await fetch(`${BASE}/api/model/texture?file=${encodeURIComponent(file)}&name=${encodeURIComponent(t.name)}`);
    const buf = Buffer.from(await tr.arrayBuffer());
    const isPng = buf.length > 8 && buf[0] === 0x89 && buf[1] === 0x50 &&
      buf[2] === 0x4e && buf[3] === 0x47;
    if (!tr.ok || !isPng)
      fail(file, `texture ${t.name} (${t.format}) did not decode to PNG (http ${tr.status}, ${buf.length}B)`);
    else texChecked++;
  }

  // geometry invariants the renderer depends on
  for (const s of okShapes) {
    if (s.positions.length % 3 !== 0)
      fail(file, `${s.name || s.offset}: positions not multiple of 3`);
    const vc = s.positions.length / 3;
    if (s.indices.length % 3 !== 0)
      fail(file, `${s.name || s.offset}: index count ${s.indices.length} not multiple of 3`);
    if (s.indices.some(i => i < 0 || i >= vc))
      fail(file, `${s.name || s.offset}: index out of range 0..${vc - 1}`);
    if (s.positions.some(v => !Number.isFinite(v)))
      fail(file, `${s.name || s.offset}: non-finite position`);
  }

  // per-shape centroids: a skinned part sitting at (0,0,0) while the rest
  // of the model is elsewhere means its bone transform wasn't applied
  // (the "face floating at the origin" bug).
  const cents = okShapes.map(s => {
    const p = s.positions; let x = 0, y = 0, z = 0;
    for (let i = 0; i < p.length; i += 3) { x += p[i]; y += p[i + 1]; z += p[i + 2]; }
    const n = p.length / 3;
    return { s, c: new THREE.Vector3(x / n, y / n, z / n) };
  });
  const modelC = cents.reduce((a, { c }) => a.add(c), new THREE.Vector3()).multiplyScalar(1 / cents.length);
  for (const { s, c } of cents) {
    if (s.skinned && c.length() < 0.02 && modelC.length() > 0.3)
      fail(file, `skinned shape ${s.name || s.offset} centroid ~origin (${c.x.toFixed(2)},${c.y.toFixed(2)},${c.z.toFixed(2)}) while model center is (${modelC.x.toFixed(2)},${modelC.y.toFixed(2)},${modelC.z.toFixed(2)}) - bone transform not applied`);
  }

  const group = new THREE.Group();
  buildMeshes(okShapes).forEach(m => group.add(m));
  group.updateMatrixWorld(true);

  const { cam, box, size, radius } = frameCamera(group);
  if (box.isEmpty() || !Number.isFinite(radius))
    { fail(file, 'empty / non-finite bounding box'); return; }
  const posAxes = [size.x, size.y, size.z].filter(v => v > 1e-4).length;
  if (posAxes < 2)
    fail(file, `degenerate bbox extent (${size.x.toFixed(3)},${size.y.toFixed(3)},${size.z.toFixed(3)})`);

  // fire a GRID x GRID ray grid through the viewport
  const rc = new THREE.Raycaster();
  const meshes = group.children;
  let hits = 0;
  let minU = 1, maxU = -1, minV = 1, maxV = -1;
  for (let iy = 0; iy < GRID; iy++) {
    for (let ix = 0; ix < GRID; ix++) {
      const ndc = new THREE.Vector2(
        (ix + 0.5) / GRID * 2 - 1,
        -((iy + 0.5) / GRID * 2 - 1));
      rc.setFromCamera(ndc, cam);
      const xs = rc.intersectObjects(meshes, false);
      if (xs.length) {
        hits++;
        minU = Math.min(minU, ndc.x); maxU = Math.max(maxU, ndc.x);
        minV = Math.min(minV, ndc.y); maxV = Math.max(maxV, ndc.y);
      }
    }
  }
  const ratio = hits / (GRID * GRID);
  const spanU = maxU - minU, spanV = maxV - minV;

  const triTotal = okShapes.reduce((a, s) =>
    a + (s.indices.length >= 3 ? s.indices.length : s.positions.length) / 3, 0);

  log(`  ${file}`);
  log(`    shapes=${okShapes.length}  tris=${triTotal}  bbox=(${size.x.toFixed(2)},${size.y.toFixed(2)},${size.z.toFixed(2)})`);
  log(`    ray hit ratio=${(ratio * 100).toFixed(1)}%  silhouette span=${(spanU).toFixed(2)}x${(spanV).toFixed(2)} NDC`);
  log(`    textures: ${texChecked} decoded to PNG, ${untextured}/${okShapes.length} shapes untextured, ${multiTex} multi-stage`);

  if (ratio < MIN_HIT_RATIO)
    fail(file, `only ${(ratio * 100).toFixed(1)}% of rays hit the model (< ${MIN_HIT_RATIO * 100}%) - would look blank`);
  if (ratio > MAX_HIT_RATIO)
    fail(file, `${(ratio * 100).toFixed(1)}% of rays hit (> ${MAX_HIT_RATIO * 100}%) - camera framing likely wrong`);
  if (spanU < 0.2 || spanV < 0.2)
    fail(file, `silhouette too small (${spanU.toFixed(2)}x${spanV.toFixed(2)} NDC) - model not properly framed`);
}

log(`model render check against ${BASE}`);
for (const f of FILES) {
  try { await checkFile(f); }
  catch (e) { fail(f, `${e.name}: ${e.message}`); }
}

if (failures) { console.error(`\n${failures} failure(s)`); process.exit(1); }
console.log('\nAll model render checks passed.');
