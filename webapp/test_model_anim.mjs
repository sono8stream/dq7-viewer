// Headless check for CANM animation playback (no GPU needed).
//
// Mirrors model.js's buildSkinSkeleton()/applyAnimFrame() logic with three's
// pure-JS classes: builds the THREE.Bone hierarchy from /api/model's
// skeleton (localPos/localQuat/localScale), then manually applies the same
// weighted skinning math three's SkinnedMesh does in its vertex shader
// (finalPos = sum_i weight_i * boneMatrix_i * boneInverse_i * vertex) at
// frame 0 and at a mid-clip frame, using the server's 4-influence
// skinIndex/skinWeight per vertex, to confirm: (1) frame 0 reproduces the
// server's baked bind-pose position (round-trip sanity - if this fails, the
// Bone hierarchy doesn't match the server's bind pose, or the weights don't
// sum to 1), and (2) at least one bone-driven vertex actually moves at the
// mid-clip frame (if this fails, tracks aren't being applied).
//
// Usage: node webapp/test_model_anim.mjs [http://127.0.0.1:8000] [file clip ...]
// Exits non-zero on any failure.

import * as THREE from 'three';

const BASE = (process.argv[2] && process.argv[2].startsWith('http'))
  ? process.argv[2] : 'http://127.0.0.1:8000';
const rest = process.argv.slice(2).filter(a => !a.startsWith('http'));
const CASES = rest.length
  ? [[rest[0], rest[1]]]
  : [
      ['CHARACTER/p0003_j00.bcmdl.lz', 'p0003_j00_idle'],
      ['CHARACTER/p0003_j00.bcmdl.lz', 'p0003_j00_run'],
    ];

let failures = 0;
const log = (...a) => console.log(...a);
const fail = (f, msg) => { failures++; console.error(`  FAIL [${f}] ${msg}`); };

function buildSkinSkeleton(bones) {
  const threeBones = new Map();
  for (const b of bones) {
    const bone = new THREE.Bone();
    bone.name = b.name;
    bone.position.set(...b.localPos);
    bone.quaternion.set(...b.localQuat);
    bone.scale.set(...b.localScale);
    threeBones.set(b.index, bone);
  }
  const root = new THREE.Group();
  for (const b of bones) {
    const bone = threeBones.get(b.index);
    const parent = threeBones.get(b.parent);
    (parent || root).add(bone);
  }
  const staticBone = new THREE.Bone();
  root.add(staticBone);
  root.updateMatrixWorld(true);
  const flat = [...threeBones.values(), staticBone];
  const boneIdxToSkinIdx = new Map();
  for (const [idx, bone] of threeBones) boneIdxToSkinIdx.set(idx, flat.indexOf(bone));
  const staticSkinIdx = flat.indexOf(staticBone);
  const skeleton = new THREE.Skeleton(flat);
  return { root, skeleton, boneIdxToSkinIdx, staticSkinIdx };
}

// Same math as THREE.SkinnedMesh's vertex shader: sum of up to 4 weighted
// (boneMatrixWorld * boneInverse) transforms.
function skinVertex(skeleton, boneIdxToSkinIdx, staticSkinIdx, skinIndex4, skinWeight4, v) {
  const boneInv = skeleton.boneInverses;
  const acc = new THREE.Vector3();
  const tmp = new THREE.Matrix4();
  for (let k = 0; k < 4; k++) {
    const w = skinWeight4[k];
    if (w <= 0) continue;
    const skinIdx = boneIdxToSkinIdx.has(skinIndex4[k]) ? boneIdxToSkinIdx.get(skinIndex4[k]) : staticSkinIdx;
    const bone = skeleton.bones[skinIdx];
    tmp.multiplyMatrices(bone.matrixWorld, boneInv[skinIdx]);
    acc.addScaledVector(v.clone().applyMatrix4(tmp), w);
  }
  return acc;
}

async function checkCase(file, clip) {
  const tag = `${file} ${clip}`;
  const mres = await fetch(`${BASE}/api/model?file=${encodeURIComponent(file)}`);
  const model = await mres.json();
  if (model.error) { fail(tag, `model api error: ${model.error}`); return; }
  const bones = model.skeleton || [];
  if (!bones.length) { fail(tag, 'no skeleton'); return; }

  const skinnedShapes = (model.geometry?.shapes || []).filter(s => s.ok && s.skinned && s.skinIndex);
  if (!skinnedShapes.length) { fail(tag, 'no skinned shapes with skinIndex/skinWeight'); return; }

  const { skeleton, boneIdxToSkinIdx, staticSkinIdx } = buildSkinSkeleton(bones);

  const ares = await fetch(`${BASE}/api/model/anim?file=${encodeURIComponent(file)}&name=${encodeURIComponent(clip)}`);
  const anim = await ares.json();
  if (anim.error) { fail(tag, `anim api error: ${anim.error}`); return; }
  if (!Object.keys(anim.tracks).length) { fail(tag, 'clip decoded to zero bone tracks'); return; }

  const skinBoneByName = new Map();
  for (const bone of skeleton.bones) if (bone.name) skinBoneByName.set(bone.name, bone);

  // sanity: frame-0 skin reproduces the server's baked bind-pose vertex
  // exactly (bones untouched == bind pose), for every skinned shape (not
  // just rigid single-influence ones - this is where a smooth multi-bone
  // blend with wrong weights/indices would show up as a big error even
  // though nothing has been animated yet).
  let maxErr0 = 0, multiInfluenceChecked = 0;
  for (const s of skinnedShapes) {
    const n = s.positions.length / 3;
    for (let vi = 0; vi < Math.min(60, n); vi++) {
      const skinIndex4 = s.skinIndex.slice(vi * 4, vi * 4 + 4);
      const skinWeight4 = s.skinWeight.slice(vi * 4, vi * 4 + 4);
      if (skinWeight4.filter(w => w > 0).length > 1) multiInfluenceChecked++;
      const v = new THREE.Vector3(s.positions[vi * 3], s.positions[vi * 3 + 1], s.positions[vi * 3 + 2]);
      const skinned = skinVertex(skeleton, boneIdxToSkinIdx, staticSkinIdx, skinIndex4, skinWeight4, v);
      maxErr0 = Math.max(maxErr0, skinned.distanceTo(v));
    }
  }
  if (maxErr0 > 1e-4)
    fail(tag, `frame-0 (bind pose) skin mismatch: max vertex delta ${maxErr0.toFixed(6)} (should be ~0)`);

  // apply a mid-clip frame's rotation/translation tracks directly to bones
  const frames = anim.frames;
  const nsamples = Math.round(frames) + 1;
  const mid = Math.floor(nsamples / 2);
  let animatedBones = 0;
  for (const [boneName, tr] of Object.entries(anim.tracks)) {
    const bone = skinBoneByName.get(boneName);
    if (!bone) { fail(tag, `track bone "${boneName}" not found in skeleton`); continue; }
    if (tr.rotation) { bone.quaternion.fromArray(tr.rotation[mid]); animatedBones++; }
    if (tr.translation) { bone.position.fromArray(tr.translation[mid]); animatedBones++; }
  }
  if (!animatedBones) { fail(tag, 'no bone had a rotation or translation track to apply'); return; }
  for (const b of skeleton.bones) b.updateMatrixWorld(true);

  let moved = 0, checkedTotal = 0;
  for (const s of skinnedShapes) {
    const n = s.positions.length / 3;
    for (let vi = 0; vi < n; vi++) {
      const skinIndex4 = s.skinIndex.slice(vi * 4, vi * 4 + 4);
      const skinWeight4 = s.skinWeight.slice(vi * 4, vi * 4 + 4);
      if (!skinWeight4.some(w => w > 0)) continue;
      checkedTotal++;
      const v = new THREE.Vector3(s.positions[vi * 3], s.positions[vi * 3 + 1], s.positions[vi * 3 + 2]);
      const skinned = skinVertex(skeleton, boneIdxToSkinIdx, staticSkinIdx, skinIndex4, skinWeight4, v);
      if (skinned.distanceTo(v) > 1e-3) moved++;
    }
  }
  log(`  ${tag}`);
  log(`    bones=${bones.length} skinnedShapes=${skinnedShapes.length} tracks=${Object.keys(anim.tracks).length} frames=${frames} multiInfluenceVerts(sampled)=${multiInfluenceChecked}`);
  log(`    frame0 bind-pose max delta=${maxErr0.toExponential(2)}  mid-frame moved vertices=${moved}/${checkedTotal}`);
  if (checkedTotal === 0) fail(tag, 'no bone-driven vertices to check (all weights 0)');
  else if (moved === 0) fail(tag, 'mid-clip frame moved 0 vertices - animation had no visible effect');
}

log(`model animation check against ${BASE}`);
for (const [file, clip] of CASES) {
  try { await checkCase(file, clip); }
  catch (e) { fail(`${file} ${clip}`, `${e.name}: ${e.message}`); }
}

if (failures) { console.error(`\n${failures} failure(s)`); process.exit(1); }
console.log('\nAll model animation checks passed.');
