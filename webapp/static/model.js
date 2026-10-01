// DQ7 3Dモデルビュアー (スクリプト/FPT/フロア/セーブ と同列の独立ページ)。
// dq8-tools/viewer の UI を参考に、Three.js で .bcmdl(CGFX) を表示する。
//
// 現状: CGFX の構造インベントリ(dict/チャンク数/シェイプ/テクスチャ/
// アニメ名)は表示できる。ジオメトリのデコード(量子化int16頂点 +
// インデックスバッファ)は webapp/bcmdl.py で first-pass 実装中で、
// パースできたシェイプのみ描画する。docs/bcmdl_model_viewer.md 参照。

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const statusEl = document.getElementById('status');
const listInner = document.getElementById('mfileListInner');
const searchBox = document.getElementById('mfileSearch');
const infoEl = document.getElementById('minfo');
const mstatus = document.getElementById('mstatus');
const canvas = document.getElementById('mcanvas');
const mobileTabs = document.getElementById('mobileTabs');

const isMobile = () => window.matchMedia('(max-width: 760px)').matches;
function showPane(name) {
  document.querySelectorAll('#modelLayout .pane').forEach(p => p.classList.remove('mobile-active'));
  document.getElementById(name).classList.add('mobile-active');
  mobileTabs.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.pane === name));
  // the 3D pane is display:none on mobile until selected; the WebGL canvas
  // then has real dimensions for the first time - force a resize/reframe.
  if (name === 'mviewport') { resize(); if (modelGroup && modelGroup.children.length) frameObject(); }
}
mobileTabs.querySelectorAll('button').forEach(b => b.addEventListener('click', () => showPane(b.dataset.pane)));

// ---- Three.js scene ---------------------------------------------------------
let renderer, scene, camera, controls, modelGroup, grid, boneGroup;
let wireframe = false, normalsMode = false;

function initThree() {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d0f17);
  camera = new THREE.PerspectiveCamera(45, 1, 0.01, 5000);
  camera.position.set(3, 3, 5);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dir = new THREE.DirectionalLight(0xffffff, 0.9);
  dir.position.set(4, 8, 6);
  scene.add(dir);
  const dir2 = new THREE.DirectionalLight(0xbbccff, 0.4);
  dir2.position.set(-5, -2, -4);
  scene.add(dir2);
  grid = new THREE.GridHelper(10, 20, 0x335, 0x223);
  scene.add(grid);
  modelGroup = new THREE.Group();
  scene.add(modelGroup);
  boneGroup = new THREE.Group();
  boneGroup.visible = bonesMode;
  scene.add(boneGroup);
  resize();
  window.addEventListener('resize', resize);
  animate();
  mstatus.textContent = 'モデル未選択';
  window.__modelViewerReady = true;
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
  resize();                      // picks up the pane becoming visible / any layout change
  controls.update();
  if (currentAnim) applyAnimFrame();
  // Setting bone.quaternion/position only dirties the LOCAL matrix - the
  // scene graph's matrixWorld chain (which skinning AND the debug skeleton
  // both read) isn't recomputed until the next render pass. renderer.render()
  // below does that for the actual mesh skinning, but updateSkeletonDebug()
  // needs it done BEFORE that call or it draws last frame's pose - so force
  // it here (skinRoot only has ~20-30 bones, this is cheap).
  if (skinRoot) skinRoot.updateMatrixWorld(true);
  updateSkeletonDebug();
  renderer.render(scene, camera);
}

function clearModel() {
  for (const c of [...modelGroup.children]) {
    if (c === skinRoot) continue;   // skinRoot's own lifecycle is buildSkinSkeleton()'s
    for (const om of (c.userData?.overlays || [])) {
      om.geometry?.dispose(); om.material?.dispose();
    }
    modelGroup.remove(c);
    c.geometry?.dispose();
    c.material?.dispose();
  }
}

function frameObject() {
  let box = new THREE.Box3().setFromObject(modelGroup);
  if (box.isEmpty() && boneGroup.children.length) box = new THREE.Box3().setFromObject(boneGroup);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(radius * 2.2, radius * 1.6, radius * 2.6));
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.updateProjectionMatrix();
  grid.scale.setScalar(radius / 5);
}

let texMode = true;
let layersMode = true;               // draw extra material stages as overlays
let bonesMode = false;
let currentFile = null;
const texCache = new Map();          // "<file>|<name>|<wrap>" -> Promise<THREE.Texture>
const _texLoader = new THREE.TextureLoader();

// wrap: 'repeat' for a base map that legitimately tiles (UVs outside 0..1),
// 'clamp' for decal/overlay stages so out-of-range UVs sample the (transparent)
// edge instead of tiling the decal across the whole surface.
function loadTexture(file, name, wrap = 'repeat') {
  const key = `${file}|${name}|${wrap}`;
  if (!texCache.has(key)) {
    const url = `/api/model/texture?file=${encodeURIComponent(file)}&name=${encodeURIComponent(name)}`;
    texCache.set(key, _texLoader.loadAsync(url).then(t => {
      t.colorSpace = THREE.SRGBColorSpace;
      const w = wrap === 'clamp' ? THREE.ClampToEdgeWrapping : THREE.RepeatWrapping;
      t.wrapS = t.wrapT = w;
      t.flipY = flipTexY;
      // These textures are small (32..128px) pixel art with cutout alpha
      // (rivets/vents/hair-strand edges: hard-ish edges but with graduated
      // 4/5-bit alpha near them, not pure 0/255). THREE's default trilinear
      // mipmapping averages that edge alpha across neighboring texels as the
      // model gets smaller/farther on screen, so alphaTest (0.25/0.35, see
      // matTextured/matOverlayBlend) discards texels that are fully opaque at
      // full resolution - e.g. the helmet's rivet embossing on p0001_j01
      // partially "disappearing" depending on view distance/angle. Nearest
      // filtering + no mipmaps keeps every texel's real alpha regardless of
      // screen size, fixing that and keeping the pixel art crisp besides.
      t.magFilter = THREE.NearestFilter;
      t.minFilter = THREE.NearestFilter;
      t.generateMipmaps = false;
      t.needsUpdate = true;
      return t;
    }).catch(() => null));
  }
  return texCache.get(key);
}

const matNormal = () => new THREE.MeshNormalMaterial({ wireframe });
const matSolid = () => new THREE.MeshStandardMaterial({
  color: 0x9ab0c8, roughness: 0.75, metalness: 0.0,
  wireframe, flatShading: true, side: THREE.DoubleSide,
});
// The base-texture alpha cutoff is READ FROM THE MODEL, not guessed: each
// material carries a real PICA200 GfxAlphaTest (enabled/function/reference)
// that bcmdl.py decodes straight out of the MTOB's raw command bytes (see
// `_alpha_test()` in bcmdl.py and docs/bcmdl_model_viewer.md, "AlphaTest構造体
// を読む根本修正"). A shape whose material has AlphaTest.Enabled == false
// (e.g. CHARACTER/p0001_j01's `yoroi` armor/helmet, p0001_j06's `fuku` torso)
// never cutout-discards on real hardware - its alpha channel is consumed by
// some other, unmodeled combiner input (specular etc.), not live
// transparency - so it must render fully opaque regardless of what the alpha
// channel looks like. A shape whose material HAS it enabled (e.g.
// `FaceMaterial`'s eye/mouth cutouts: Function=Greater, Reference=128) uses
// that reference value (0..255 -> 0..1) as THREE's alphaTest threshold; three
// only supports a ">= threshold keeps" test, which is a good approximation of
// every Function DQ7 actually uses (Greater/Gequal).
//
// This replaces two previous hacks that both grew out of NOT reading this
// field: a single hardcoded alphaTest constant for every material (too
// permissive for FaceMaterial's real ~50% cutout, too strict for
// non-cutout materials whenever their alpha channel happened to dip low -
// see the p0001_j01 helmet rivet history below), and a UV-sampling heuristic
// (`opaqueBase`, still used as a fallback in bcmdl.py when the AlphaTest
// command pair can't be found) that only guessed opaqueness indirectly.
//
// Separately: DQ7's cutout textures (helmet rivets/vents, hair strand edges,
// ...) have soft anti-aliased borders quantized to RGBA4/5551's few alpha
// levels (0, 17, 34, ... 255), not a hard 0/255 edge - loadTexture()'s
// NearestFilter/no-mipmaps avoids blurring those further (see comment there).
// Which side(s) to actually render is ALSO read from the model, not assumed:
// GfxRasterization.FaceCullingCommand is a fixed PICA200 command pair (like
// AlphaTest) that bcmdl.py decodes into `side: 'front'|'back'|'double'` (see
// `_cull_mode()` in bcmdl.py). Investigating CHARACTER/p0006_j09's reported
// color/layering weirdness turned up that every shape was being forced to
// `THREE.DoubleSide` regardless: its `body`/`huku`/`FaceMaterial` are real
// single-sided meshes (cull back faces, draw front only), while
// `bodyryomen`/`hukuyomen`/`kami`/`kami2`/`acse` are genuinely meant to be
// double-sided (thin flap/hair-strand geometry - not a mistake). Forcing
// DoubleSide on the single-sided ones draws their normally-hidden backfaces
// too, which can peek through or z-fight with neighboring geometry at some
// angles - see docs/bcmdl_model_viewer.md, 2026-09-21 "CullMode構造体を読む修正".
const _THREE_SIDE = { front: THREE.FrontSide, back: THREE.BackSide, double: THREE.DoubleSide };
const sideFor = (side) => _THREE_SIDE[side] ?? THREE.DoubleSide;

function matTextured(map, ref, side) {
  return new THREE.MeshBasicMaterial({
    map, wireframe, side: sideFor(side),
    transparent: true, alphaTest: typeof ref === 'number' ? ref : 0.02,
  });
}
// AlphaTest.Enabled === false: the material never cutout-discards on real
// hardware, so alpha must be ignored entirely (no alphaTest, no blending) -
// see matTextured's comment above.
const matTexturedOpaque = (map, side) => new THREE.MeshBasicMaterial({
  map, wireframe, side: sideFor(side),
});
// Extra material stages (face eyes/mouth, clothing emblems, armor sheen,
// ...) are drawn as separate overlay meshes sharing the base geometry but
// with that stage's own UV set. WHICH of these three to use for a given
// stage is read directly from the model - see `textureBlend` below, not
// guessed from the texture's own pixels.
//   'blend'    -> real decal (Interpolate combiner: lerp(base, this,
//                 this.alpha)) - alpha-blended, masked by the texture's own
//                 alpha (eyes/mouth/emblems).
//   'multiply' -> tint/shading map (Modulate combiner: base * this) ->
//                 THREE.MultiplyBlending, ignoring alpha entirely (Modulate
//                 always contributes, regardless of coverage).
//   'add'      -> highlight/glow map (Add/AddSigned/MultAdd/AddMult
//                 combiner families, all of which sum something onto the
//                 base) -> THREE.AdditiveBlending, approximating the net
//                 brightening effect.
const matOverlayBlend = (map, stage) => new THREE.MeshBasicMaterial({
  map, wireframe, side: THREE.DoubleSide,
  transparent: true, alphaTest: 0.25,
  depthWrite: false, polygonOffset: true,
  polygonOffsetFactor: -1, polygonOffsetUnits: -2 * stage,
});
const matOverlayMultiply = (map, stage) => new THREE.MeshBasicMaterial({
  map, wireframe, side: THREE.DoubleSide,
  transparent: true, blending: THREE.MultiplyBlending,
  depthWrite: false, polygonOffset: true,
  polygonOffsetFactor: -1, polygonOffsetUnits: -2 * stage,
});
const matOverlayAdd = (map, stage) => new THREE.MeshBasicMaterial({
  map, wireframe, side: THREE.DoubleSide,
  transparent: true, blending: THREE.AdditiveBlending,
  depthWrite: false, polygonOffset: true,
  polygonOffsetFactor: -1, polygonOffsetUnits: -2 * stage,
});
const _OVERLAY_MAT_FOR_BLEND = {
  blend: matOverlayBlend, multiply: matOverlayMultiply, add: matOverlayAdd,
};

// 3DS models sample textures with v=0 at the bottom, so the PNG (top-left
// origin) always needs a vertical flip. This has held for every DQ7 model, so
// it's a constant now (the old "UV上下反転" toolbar toggle was never needed).
const flipTexY = true;

// What stage i>=1 actually IS - a real decal, a multiply-tint/shading map,
// an additive highlight map, or not sampled by the pixel combiner at all -
// is decided SERVER-SIDE by bcmdl.py's `textureBlend[i]` ('blend' |
// 'multiply' | 'add' | 'unused'), read directly from the material's real
// GfxTexEnv combiner stages (`_tex_env_mapper_roles()` in bcmdl.py): which
// PICATextureCombinerSource(Texture0/1/2) each active stage's color/alpha
// inputs reference, and which PICATextureCombinerMode combines them. This
// is NOT inferred from the texture's own pixel content (an earlier version
// guessed "real decal vs shading map" from how opaque the texture looked,
// which happened to separate a sample of files but wasn't reading anything
// the model actually specifies - see docs/bcmdl_model_viewer.md, 2026-09-21
// "TexEnvコンバイナ構造を読む根本修正" for why that was replaced). A stage
// marked 'unused' genuinely isn't part of this material's combiner output
// (e.g. CHARACTER/p0006_j09's/p0006_j17's "b"/"c" secondary textures feed a
// separate compiled shader program as a normal/shading map input instead -
// PICA200's fixed-function TexEnv combiner and a SHDR program are
// independent mechanisms) and must not be drawn at all, not approximated.

function buildMeshes(shapes, file) {
  clearModel();
  currentFile = file;
  const genToken = ++_buildGen;

  // Build geometry synchronously so the model shows immediately (solid), then
  // stream textures in as each PNG arrives - no up-front await on all of them.
  let built = 0;
  for (const s of shapes) {
    if (!s.ok || !s.positions || s.positions.length < 9) continue;
    const nv = s.positions.length / 3;

    // Each material texture stage has its OWN uv CHANNEL (bcmdl.py's
    // `textureUV[i]`, decoded from the material's real GfxTextureCoord.
    // SourceCoordIndex - see docs/bcmdl_model_viewer.md, 2026-09-21
    // "TextureCoordのSourceCoordIndexを読む修正"). Stage i does NOT
    // necessarily read uv{i}: e.g. CHARACTER/p0006_j09's `huku` (clothes)
    // stage 0 (its OWN base texture, `p0006_j09huku`) actually samples uv1 -
    // uv0 for that shape is a near-degenerate ~9%-tall sliver of the
    // texture. Falls back to the old positional uv{i} guess only if the
    // server didn't supply `textureUV` (should not normally happen).
    const stages = (s.textures && s.textures.length) ? s.textures : (s.texture ? [s.texture] : []);
    const texUV = s.textureUV || stages.map((_, i) => i);
    const uvArrays = [s.uvs, s.uvs1, s.uvs2];
    const uvSets = stages.map((_, i) => {
      const arr = uvArrays[texUV[i] ?? i];
      return (arr && arr.length === nv * 2) ? arr : null;
    });

    const g = new THREE.BufferGeometry();
    const posAttr = new THREE.Float32BufferAttribute(s.positions, 3);
    g.setAttribute('position', posAttr);
    let nrmAttr = null;
    if (s.normals && s.normals.length === s.positions.length) {
      nrmAttr = new THREE.Float32BufferAttribute(s.normals, 3);
      g.setAttribute('normal', nrmAttr);
    }
    // The BASE geometry's 'uv' attribute is stage 0's uv (matTextured/
    // matTexturedOpaque's map reads it) - use the real channel, not s.uvs.
    if (uvSets[0]) {
      g.setAttribute('uv', new THREE.Float32BufferAttribute(uvSets[0], 2));
    }
    if (s.indices && s.indices.length >= 3) g.setIndex(s.indices);
    if (!g.getAttribute('normal')) { g.computeVertexNormals(); nrmAttr = g.getAttribute('normal'); }

    let mesh;
    if (s.skinned && s.skinIndex && skinSkeleton) {
      const skinIndex = new Uint16Array(nv * 4);
      for (let i = 0; i < skinIndex.length; i++) skinIndex[i] = skinIndexFor(s.skinIndex[i]);
      g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndex, 4));
      g.setAttribute('skinWeight', new THREE.Float32BufferAttribute(s.skinWeight, 4));
      mesh = new THREE.SkinnedMesh(g, normalsMode ? matNormal() : matSolid());
      mesh.bind(skinSkeleton);
    } else {
      mesh = new THREE.Mesh(g, normalsMode ? matNormal() : matSolid());
    }
    mesh.name = s.name || `shape${built}`;
    mesh.userData.stages = stages;
    // alphaTest: {enabled, function, functionName, reference} decoded from
    // the material's real GfxAlphaTest, or undefined if bcmdl.py couldn't
    // find it (falls back to the opaqueBase heuristic flag). See matTextured.
    mesh.userData.alphaTest = s.alphaTest || null;
    mesh.userData.opaqueBase = !!s.opaqueBase;
    // 'front' | 'back' | 'double', decoded from the material's real
    // GfxRasterization.FaceCulling - see matTextured's comment above.
    mesh.userData.side = s.side || null;
    // If a stage's real uv channel wasn't supplied, don't guess a fallback -
    // a decal drawn through the wrong uv set can tile across the whole
    // surface and hide it (this is what made the hero's forehead vanish).
    // null => skip that stage.
    mesh.userData.uvSets = uvSets;
    // textureBlend[i]: 'base'/'blend'/'multiply'/'add'/'unused', decoded
    // from the material's real TexEnv combiner - see the comment above
    // `matOverlayBlend` for why.
    mesh.userData.textureBlend = s.textureBlend || stages.map((_, i) => (i === 0 ? 'base' : 'blend'));
    mesh.userData.overlays = [];
    modelGroup.add(mesh);
    built++;

    if (texMode && !normalsMode) applyShapeTextures(mesh, genToken);
  }
  return built;
}
let _buildGen = 0;

// Attach stage 0 as the base map and stages 1.. as overlay meshes. Async: each
// stage's material appears when its texture PNG resolves.
function applyShapeTextures(mesh, genToken) {
  const stages = mesh.userData.stages || [];
  const uvSets = mesh.userData.uvSets || [];
  const textureBlend = mesh.userData.textureBlend || [];
  let kicked = 0;
  stages.forEach((texName, i) => {
    if (!texName) return;
    const blend = textureBlend[i];
    if (i > 0 && (!layersMode || !uvSets[i] || blend === 'unused' || !blend))
      return;   // disabled / no distinct uv set / not sampled by the combiner
    kicked++;
    loadTexture(currentFile, texName, i === 0 ? 'repeat' : 'clamp').then(t => {
      if (genToken !== _buildGen || !t) return;
      if (i === 0) {
        if (!mesh.geometry.getAttribute('uv')) return;
        const prev = mesh.material;
        const at = mesh.userData.alphaTest;
        const side = mesh.userData.side;
        if (at ? !at.enabled : mesh.userData.opaqueBase) {
          mesh.material = matTexturedOpaque(t, side);
        } else {
          mesh.material = matTextured(t, at ? at.reference / 255 : undefined, side);
        }
        mesh.material.wireframe = wireframe;
        if (prev) prev.dispose();
      } else {
        const uv = uvSets[i];
        if (!uv) return;
        const bg = new THREE.BufferGeometry();
        bg.setAttribute('position', mesh.geometry.getAttribute('position'));
        if (mesh.geometry.getAttribute('normal')) bg.setAttribute('normal', mesh.geometry.getAttribute('normal'));
        bg.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
        if (mesh.geometry.index) bg.setIndex(mesh.geometry.index);
        // A skinned base mesh deforms per-vertex in the shader - its own
        // matrixWorld never moves, so a plain child Mesh would stay in bind
        // pose while the face/decal it's supposed to sit on animates away.
        // Give the overlay the same skin attributes + skeleton so it deforms
        // identically to the base mesh underneath it.
        const makeOverlayMat = _OVERLAY_MAT_FOR_BLEND[blend] || matOverlayBlend;
        let om;
        if (mesh.isSkinnedMesh) {
          bg.setAttribute('skinIndex', mesh.geometry.getAttribute('skinIndex'));
          bg.setAttribute('skinWeight', mesh.geometry.getAttribute('skinWeight'));
          om = new THREE.SkinnedMesh(bg, makeOverlayMat(t, i));
          om.bind(skinSkeleton);
        } else {
          om = new THREE.Mesh(bg, makeOverlayMat(t, i));
        }
        om.material.wireframe = wireframe;
        om.userData.isOverlay = true;
        om.renderOrder = i;
        mesh.add(om);
        mesh.userData.overlays.push(om);
      }
    });
  });
  return kicked;
}

// ---- skeleton (bind pose debug lines, + a real THREE.Skeleton for skinning) ---
function clearSkeleton() {
  for (const c of [...boneGroup.children]) {
    boneGroup.remove(c);
    c.geometry?.dispose();
    c.material?.dispose();
  }
}

// boneDebugList/-Attr let updateSkeletonDebug() re-read LIVE bone positions
// each frame from skinBonesByName (the same THREE.Bone objects animation
// drives - see buildSkinSkeleton()), instead of the bind-pose `b.pos` this
// used to bake in once. Without this the debug skeleton visibly froze in
// bind pose while the mesh itself animated.
let boneDebugList = null;       // [{name, parentName}]
let boneDebugSegAttr = null;    // Float32BufferAttribute, 2 points/bone-with-parent
let boneDebugJointAttr = null;  // Float32BufferAttribute, 1 point/bone

function buildSkeleton(bones) {
  clearSkeleton();
  boneDebugList = null;
  boneDebugSegAttr = null;
  boneDebugJointAttr = null;
  if (!bones || !bones.length) return 0;
  const byIndex = new Map(bones.map(b => [b.index, b]));
  boneDebugList = bones.map(b => ({ name: b.name, parentName: byIndex.get(b.parent)?.name || null }));
  const nSegs = boneDebugList.filter(b => b.parentName).length;

  if (nSegs) {
    boneDebugSegAttr = new THREE.Float32BufferAttribute(new Float32Array(nSegs * 6), 3);
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', boneDebugSegAttr);
    boneGroup.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
      color: 0xffcc33, depthTest: false, transparent: true, opacity: 0.9,
    })));
  }
  boneDebugJointAttr = new THREE.Float32BufferAttribute(new Float32Array(bones.length * 3), 3);
  const jg = new THREE.BufferGeometry();
  jg.setAttribute('position', boneDebugJointAttr);
  const jpts = new THREE.Points(jg, new THREE.PointsMaterial({
    color: 0xff5544, size: 6, sizeAttenuation: false, depthTest: false,
  }));
  boneGroup.add(jpts);
  boneGroup.renderOrder = 999;
  boneGroup.traverse(o => { o.renderOrder = 999; });
  updateSkeletonDebug();   // fill in the initial (bind pose) positions now
  return bones.length;
}

const _dbgV = new THREE.Vector3();
function updateSkeletonDebug() {
  if (!boneDebugList || !skinBonesByName || !boneGroup.visible) return;
  const joints = boneDebugJointAttr.array;
  const segs = boneDebugSegAttr ? boneDebugSegAttr.array : null;
  let si = 0;
  for (let i = 0; i < boneDebugList.length; i++) {
    const { name, parentName } = boneDebugList[i];
    const bone = skinBonesByName.get(name);
    if (!bone) continue;
    _dbgV.setFromMatrixPosition(bone.matrixWorld);
    joints[i * 3] = _dbgV.x; joints[i * 3 + 1] = _dbgV.y; joints[i * 3 + 2] = _dbgV.z;
    if (parentName && segs) {
      const pbone = skinBonesByName.get(parentName);
      if (pbone) {
        const cx = _dbgV.x, cy = _dbgV.y, cz = _dbgV.z;
        _dbgV.setFromMatrixPosition(pbone.matrixWorld);
        segs[si * 6] = _dbgV.x; segs[si * 6 + 1] = _dbgV.y; segs[si * 6 + 2] = _dbgV.z;
        segs[si * 6 + 3] = cx; segs[si * 6 + 4] = cy; segs[si * 6 + 5] = cz;
        si++;
      }
    }
  }
  boneDebugJointAttr.needsUpdate = true;
  if (boneDebugSegAttr) boneDebugSegAttr.needsUpdate = true;
}

// ---- skinning + animation playback ---------------------------------------
//
// bcmdl.py's geometry() bakes each vertex into bind-pose MODEL space by
// multiplying it by its bone's bind-pose world matrix server-side (see
// bcmdl.py _one_shape / _skeleton). That is exactly the space THREE.SkinnedMesh
// expects: skinning computes finalPos = boneMatrixWorld * boneInverse *
// vertexPos, and boneInverse is the inverse of the bone's world matrix AT
// BIND TIME - so as long as we build the THREE.Bone hierarchy from the same
// bind-pose transforms (skeleton[].localPos/localQuat/localScale) BEFORE
// computing boneInverses, an untouched (non-animated) bone reproduces the
// server's baked position exactly, and animating a bone's quaternion/position
// moves only the vertices assigned to it (or its children).
//
// Each vertex gets up to 4 (boneIndex, weight) slots from the server (rigid
// parts use 1 real slot at weight 1.0, smooth-skinned parts a real blend of
// 2-4 bones decoded from the CGFX boneIndex/boneWeight vertex attributes -
// see bcmdl.py _one_shape's `influences()`). Unused slots are weight 0 with
// an arbitrary index, so a synthetic extra "static" bone (never touched)
// only matters as a defensive fallback if a slot's index can't be mapped.
// See docs/canm_skeletal_animation_investigation.md for the CANM track format.

let skinSkeleton = null;     // THREE.Skeleton | null
let skinBonesByName = null;  // Map<name, THREE.Bone>
let skinRoot = null;         // THREE.Group holding the bone hierarchy
let boneIdxToSkinIdx = null; // Map<server boneIdx, skinSkeleton.bones[] index>
let staticSkinIdx = -1;      // skinIdx of the never-animated sentinel bone
let currentAnim = null;      // {frames, tracks} from /api/model/anim
let animPlaying = false;
let animElapsed = 0;         // seconds of anim-time played so far (frozen while paused)
let animLastTick = 0;        // performance.now() of the last applyAnimFrame() while playing
const ANIM_FPS = 30;         // DQ7's field logic runs at 30fps; clip frame
                              // counts (e.g. 60 = 2s idle loop) match that.

function buildSkinSkeleton(bones) {
  if (skinRoot) { modelGroup.remove(skinRoot); skinRoot = null; }
  skinSkeleton = null;
  skinBonesByName = new Map();
  boneIdxToSkinIdx = new Map();
  staticSkinIdx = -1;
  if (!bones || !bones.length) return null;

  const threeBones = new Map();   // server index -> THREE.Bone
  for (const b of bones) {
    const bone = new THREE.Bone();
    bone.name = b.name;
    bone.position.set(...b.localPos);
    bone.quaternion.set(...b.localQuat);
    bone.scale.set(...b.localScale);
    bone.userData.bindPos = bone.position.clone();
    bone.userData.bindQuat = bone.quaternion.clone();
    threeBones.set(b.index, bone);
    skinBonesByName.set(b.name, bone);
  }
  skinRoot = new THREE.Group();
  skinRoot.name = '__skinRoot';
  for (const b of bones) {
    const bone = threeBones.get(b.index);
    const parent = threeBones.get(b.parent);
    (parent || skinRoot).add(bone);
  }
  // sentinel bone for boneIdx===-1 vertices (no resolvable rigid bone, or a
  // smooth-skinned submesh we don't decode): identity transform, never
  // animated, so boneMatrix*boneInverse stays the identity and the vertex
  // keeps the position it was baked with server-side.
  const staticBone = new THREE.Bone();
  staticBone.name = '__static';
  skinRoot.add(staticBone);
  modelGroup.add(skinRoot);
  skinRoot.updateMatrixWorld(true);

  const flat = [...threeBones.values(), staticBone];
  for (const [idx, bone] of threeBones) boneIdxToSkinIdx.set(idx, flat.indexOf(bone));
  staticSkinIdx = flat.indexOf(staticBone);
  skinSkeleton = new THREE.Skeleton(flat);
  return skinSkeleton;
}

function skinIndexFor(boneIdx) {
  if (boneIdx < 0 || !boneIdxToSkinIdx.has(boneIdx)) return staticSkinIdx;
  return boneIdxToSkinIdx.get(boneIdx);
}

// ---- animation UI -----------------------------------------------------
const animSelect = document.getElementById('animSelect');
const btnPlay = document.getElementById('btnPlay');

function populateAnimList(animList) {
  if (!animSelect) return;
  animSelect.innerHTML = '<option value="">(アニメなし)</option>';
  for (const a of (animList || [])) {
    const opt = document.createElement('option');
    opt.value = a.name;
    opt.textContent = `${a.name} (${Math.round(a.frames)}f)`;
    animSelect.appendChild(opt);
  }
  animSelect.disabled = !(animList && animList.length);
  if (btnPlay) btnPlay.disabled = true;
}

async function loadAnim(name) {
  currentAnim = null;
  animPlaying = false;
  if (btnPlay) { btnPlay.disabled = !name; btnPlay.textContent = '再生'; }
  resetBonesToBindPose();
  if (!name || !currentFile) return;
  try {
    const res = await fetch(`/api/model/anim?file=${encodeURIComponent(currentFile)}&name=${encodeURIComponent(name)}`);
    const data = await res.json();
    if (data.error) { mstatus.textContent = `アニメ読み込み失敗: ${data.error}`; return; }
    currentAnim = data;
    animPlaying = true;
    animElapsed = 0;
    animLastTick = performance.now();
    if (btnPlay) btnPlay.textContent = '一時停止';
    // Some clips (confirmed on multiple characters, e.g. some jobs' "idle"/
    // "run"/"dash") genuinely decode to zero sampled bone tracks - every
    // bone stays at its bind pose for the whole clip, so playback looks
    // frozen. This is NOT necessarily a parser bug (see
    // docs/bcmdl_model_viewer.md, 2026-09-21 "動かないアニメクリップの扱い"
    // for what's confirmed vs still unexplained) - say so explicitly instead
    // of silently doing nothing, so it doesn't read as "the viewer is broken".
    const trackNames = Object.keys(data.tracks || {});
    if (trackNames.length === 0) {
      mstatus.textContent = `${name}: このクリップは動くボーンが0件でした(静止ポーズの可能性。他のクリップ名も試してみてください)`;
      return;
    }
    // Some tracks reference bone names this particular model's OWN skeleton
    // doesn't have at all (e.g. "cap"/"mant"/"L_sode" - hat/cape/sleeve
    // bones). Confirmed NOT a parsing bug: the model's declared bone count
    // matches exactly what bcmdl.py reads (see docs/bcmdl_model_viewer.md,
    // 2026-09-21 "「ボーンが見つからない」問題の再調査"), and this repo's
    // own docs/keifa_job_animation_investigation.md already documented that
    // job animation packs are literal byte-for-byte clones across a job
    // family sharing one richer "template" skeleton - so a clip can
    // legitimately carry tracks for optional accessory bones (hat, cape,
    // sleeves, tail, ...) that only some jobs' meshes actually have. Report
    // it rather than silently dropping those tracks, so it reads as "this
    // model doesn't have that part" instead of "the viewer lost some bones".
    const unmatched = trackNames.filter(n => !skinBonesByName || !skinBonesByName.has(n));
    if (unmatched.length) {
      const shown = unmatched.slice(0, 4).join(', ') + (unmatched.length > 4 ? ` 他${unmatched.length - 4}件` : '');
      mstatus.textContent = `${name}: 再生中(${unmatched.length}個のボーントラックはこのモデルに無いパーツ用: ${shown})`;
    }
  } catch (e) {
    mstatus.textContent = `アニメ読み込み失敗: ${e.message || e}`;
  }
}

function resetBonesToBindPose() {
  if (!skinBonesByName) return;
  for (const bone of skinBonesByName.values()) {
    if (bone.userData.bindPos) {
      bone.position.copy(bone.userData.bindPos);
      bone.quaternion.copy(bone.userData.bindQuat);
    }
  }
}

function lerp(a, b, t) { return a + (b - a) * t; }

function sampleVec3Track(samples, t0, t1, f) {
  return [
    lerp(samples[t0][0], samples[t1][0], f),
    lerp(samples[t0][1], samples[t1][1], f),
    lerp(samples[t0][2], samples[t1][2], f),
  ];
}

const _qa = new THREE.Quaternion(), _qb = new THREE.Quaternion();
function applyAnimFrame() {
  if (!currentAnim || !skinBonesByName) return;
  const now = performance.now();
  if (animPlaying) {
    animElapsed += (now - animLastTick) / 1000;
    animLastTick = now;
  }
  const frames = currentAnim.frames;
  const nsamples = Math.round(frames) + 1;    // see bcmdl.read_animation
  // frames==0 (a single held pose, e.g. p0492_idle) has nsamples==1 and no
  // "wrap around a cycle" to compute - `x % 0` is NaN in JS, which used to
  // silently skip every bone below (tr.rotation[NaN] is undefined) and
  // left the pose looking like nothing had loaded. Just show sample 0.
  let t0 = 0, t1 = 0, f = 0;
  if (frames > 0) {
    const pos = (animElapsed * ANIM_FPS) % frames;
    t0 = Math.floor(pos) % nsamples;
    t1 = (t0 + 1) % nsamples;
    f = pos - Math.floor(pos);
  }
  for (const [boneName, tr] of Object.entries(currentAnim.tracks)) {
    const bone = skinBonesByName.get(boneName);
    if (!bone) continue;
    if (tr.rotation && tr.rotation[t0] && tr.rotation[t1]) {
      _qa.fromArray(tr.rotation[t0]);
      _qb.fromArray(tr.rotation[t1]);
      bone.quaternion.copy(_qa).slerp(_qb, f);
    }
    if (tr.translation && tr.translation[t0] && tr.translation[t1]) {
      const [x, y, z] = sampleVec3Track(tr.translation, t0, t1, f);
      bone.position.set(x, y, z);
    }
  }
}

if (animSelect) animSelect.addEventListener('change', () => loadAnim(animSelect.value));
if (btnPlay) btnPlay.addEventListener('click', () => {
  if (!currentAnim) return;
  animPlaying = !animPlaying;
  if (animPlaying) animLastTick = performance.now();
  btnPlay.textContent = animPlaying ? '一時停止' : '再生';
});

function clearOverlays() {
  for (const m of modelGroup.children) {
    for (const om of (m.userData.overlays || [])) {
      m.remove(om); om.geometry.dispose(); om.material.dispose();
    }
    m.userData.overlays = [];
  }
}

async function applyMaterialMode() {
  const genToken = _buildGen;
  clearOverlays();
  for (const m of modelGroup.children) {
    if (!m.geometry) continue;   // skinRoot (bone hierarchy Group) has no geometry -
                                  // used to throw here and silently abort the whole
                                  // loop before reaching later meshes (e.g. the face,
                                  // whose eye/mouth decals then never got rebuilt
                                  // after toggling 重ねテクスチャ off then on)
    const hadUv = m.geometry.getAttribute('uv');
    const prev = m.material;
    if (normalsMode) {
      m.material = matNormal();
    } else if (texMode && (m.userData.stages || []).length && hadUv) {
      m.material = matSolid();                 // until textures resolve
      applyShapeTextures(m, genToken);
    } else {
      m.material = matSolid();
    }
    m.material.wireframe = wireframe;
    if (prev && prev !== m.material) prev.dispose();
  }
}

// ---- data / UI ------------------------------------------------------------
let allFiles = [];
let selected = null;

async function loadFiles() {
  const res = await fetch('/api/model_files');
  allFiles = await res.json();
  renderFileList();
}

// Flat, display-order list of the currently filtered/visible files (same
// order as the grouped <details> list below) - lets the viewport's prev/
// next buttons step through models without caring about the directory
// grouping or search filter, and without needing DOM order lookups.
let visibleFiles = [];

function renderFileList() {
  const q = searchBox.value.trim().toLowerCase();
  const byDir = {};
  for (const f of allFiles) {
    if (q && !f.name.toLowerCase().includes(q)) continue;
    (byDir[f.dir] = byDir[f.dir] || []).push(f);
  }
  statusEl.textContent = `${Object.values(byDir).reduce((a, v) => a + v.length, 0)} / ${allFiles.length}`;
  listInner.innerHTML = '';
  visibleFiles = [];
  for (const dir of Object.keys(byDir)) {
    const det = document.createElement('details');
    det.className = 'mfile-dir';
    det.open = !!q || dir === 'MONSTER';
    const sm = document.createElement('summary');
    sm.textContent = `${dir} (${byDir[dir].length})`;
    det.appendChild(sm);
    for (const f of byDir[dir]) {
      visibleFiles.push(f);
      const row = document.createElement('div');
      row.className = 'mfile-row' + (selected === f.path ? ' selected' : '');
      row.dataset.path = f.path;
      row.innerHTML = `${f.name}<span class="kind">${f.kind}</span>`;
      row.onclick = () => selectModel(f.path, row);
      det.appendChild(row);
    }
    listInner.appendChild(det);
  }
  updatePrevNextButtons();
}
searchBox.addEventListener('input', renderFileList);

// ---- prev/next model navigation (viewport toolbar) ------------------------
const btnPrevModel = document.getElementById('btnPrevModel');
const btnNextModel = document.getElementById('btnNextModel');

function updatePrevNextButtons() {
  const idx = visibleFiles.findIndex(f => f.path === selected);
  if (btnPrevModel) btnPrevModel.disabled = !(idx > 0);
  if (btnNextModel) btnNextModel.disabled = !(idx >= 0 && idx < visibleFiles.length - 1);
}

function stepModel(delta) {
  const idx = visibleFiles.findIndex(f => f.path === selected);
  const next = idx + delta;
  if (next < 0 || next >= visibleFiles.length) return;
  const f = visibleFiles[next];
  const row = listInner.querySelector(`[data-path="${CSS.escape(f.path)}"]`);
  // Reveal the row's <details> group and scroll it into view so the file
  // list stays in sync with what prev/next is stepping through, even when
  // stepping across a directory boundary the user hadn't expanded.
  const det = row && row.closest('details.mfile-dir');
  if (det) det.open = true;
  if (row) row.scrollIntoView({ block: 'nearest' });
  selectModel(f.path, row);
}
if (btnPrevModel) btnPrevModel.onclick = () => stepModel(-1);
if (btnNextModel) btnNextModel.onclick = () => stepModel(1);

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function renderInfo(r) {
  const st = r.structure || {};
  const g = r.geometry || {};
  const L = [];
  L.push(`${r.file}`);
  L.push(`CGFX rev ${st.revision}  ${st.size} bytes`);
  L.push('');
  L.push(`ジオメトリ: ${g.ok_count}/${g.total_shapes} シェイプ`);
  for (const s of (g.shapes || [])) {
    L.push(s.ok
      ? `  [OK] ${s.name || '(no name)'} v=${s.vcount} i=${s.icount}${s.texture ? '  tex=' + s.texture : ''}${s.skinned ? '  skinned' : ''}`
      : `  [--] ${s.name || '(no name)'} ${s.reason}`);
  }
  if (g.errors && g.errors.length) {
    L.push('  errors:');
    for (const e of g.errors.slice(0, 6)) L.push(`   ${e}`);
  }
  L.push('');
  L.push('チャンク: ' + JSON.stringify(st.chunk_counts || {}));
  if (r.materials && r.materials.length) {
    L.push('\nマテリアル:');
    for (const m of r.materials) {
      const at = m.alphaTest;
      const atStr = at ? (at.enabled ? `alphaTest ${at.functionName} ref=${at.reference}` : 'alphaTest disabled(opaque)') : 'alphaTest unknown';
      const sideStr = `side=${m.side || 'unknown'}`;
      const uvStr = m.coordIdx ? `uv=[${m.coordIdx.slice(0, (m.textures || []).length).join(',')}]` : 'uv=unknown';
      const blendStr = m.textureBlend ? `combine=[${m.textureBlend.join(',')}]` : 'combine=unknown';
      L.push(`  ${m.name} -> [${(m.textures || []).join(', ')}] (${atStr}, ${sideStr}, ${uvStr}, ${blendStr})`);
    }
  }
  if (r.skeleton && r.skeleton.length) {
    L.push(`\nスケルトン (${r.skeleton.length} ボーン, バインドポーズ):`);
    L.push('  ' + r.skeleton.slice(0, 40).map(b => b.name).join(', ') +
      (r.skeleton.length > 40 ? ' …' : ''));
  }
  if (r.animList && r.animList.length) {
    L.push(`\nアニメーション (${r.animList.length}, 下のツールバーで再生。骨格の一部のみ推定デコード):`);
    for (const a of r.animList.slice(0, 60)) L.push(`  ${a.name} (${Math.round(a.frames)}f)`);
    if (r.animList.length > 60) L.push(`  … 他 ${r.animList.length - 60}`);
  }
  for (const [k, v] of Object.entries(st.dicts || {})) {
    if (k === 'Textures' || k === 'Materials' || k === 'Models') continue;
    L.push(`\n${k} (${v.length}):\n  ` + v.slice(0, 40).join('\n  '));
  }

  let html = `<pre style="margin:0;white-space:pre-wrap">${esc(L.join('\n'))}</pre>`;
  const texs = r.textures || [];
  if (texs.length) {
    html += `<div style="margin-top:10px;font-size:11px;color:var(--muted)">テクスチャ (${texs.length})</div>`;
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:4px">';
    for (const t of texs) {
      const cap = `${esc(t.name)}<br>${t.width}x${t.height} ${esc(t.format || '?')}`;
      if (t.ok) {
        const u = `/api/model/texture?file=${encodeURIComponent(r.file)}&name=${encodeURIComponent(t.name)}`;
        html += `<figure style="margin:0;width:76px;font-size:9.5px;text-align:center">
          <img src="${u}" style="width:72px;height:72px;object-fit:contain;background:#222;image-rendering:pixelated;border:1px solid var(--border)">
          <figcaption style="color:var(--muted);line-height:1.2">${cap}</figcaption></figure>`;
      } else {
        html += `<figure style="margin:0;width:76px;font-size:9.5px;text-align:center">
          <div style="width:72px;height:72px;background:#222;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;color:#a55">×</div>
          <figcaption style="color:var(--muted);line-height:1.2">${cap}</figcaption></figure>`;
      }
    }
    html += '</div>';
  }
  infoEl.innerHTML = html;
}

async function selectModel(path, rowEl) {
  selected = path;
  document.querySelectorAll('.mfile-row.selected').forEach(x => x.classList.remove('selected'));
  if (rowEl) rowEl.classList.add('selected');
  updatePrevNextButtons();
  mstatus.textContent = '読み込み中...';
  infoEl.textContent = '読み込み中...';
  if (isMobile()) showPane('mviewport');
  let r;
  try {
    const res = await fetch(`/api/model?file=${encodeURIComponent(path)}`);
    r = await res.json();
  } catch (e) {
    mstatus.textContent = `失敗: ${e.message || e}`;
    return;
  }
  if (r.error) {
    mstatus.textContent = `エラー: ${r.error}`;
    infoEl.textContent = `エラー: ${r.error}`;
    return;
  }
  renderInfo(r);
  currentAnim = null;
  animPlaying = false;
  buildSkinSkeleton(r.skeleton);
  const built = await buildMeshes((r.geometry && r.geometry.shapes) || [], path);
  const nbones = buildSkeleton(r.skeleton);
  populateAnimList(r.animList);
  if (built > 0) {
    frameObject();
    mstatus.textContent = `${path.split('/').pop()} — ${built} メッシュ` +
      (nbones ? ` / ${nbones} ボーン` : '');
  } else {
    clearModel();
    if (nbones) frameObject();
    mstatus.textContent = `${path.split('/').pop()} — ジオメトリ未デコード(構造は右パネル)` +
      (nbones ? ` / ${nbones} ボーン` : '');
  }
}

document.getElementById('btnWire').onclick = () => {
  wireframe = !wireframe;
  modelGroup.traverse(o => { if (o.material) o.material.wireframe = wireframe; });
};
document.getElementById('btnNormals').onclick = () => { normalsMode = !normalsMode; applyMaterialMode(); };
document.getElementById('btnReset').onclick = () => frameObject();

const btnTex = document.getElementById('btnTex');
if (btnTex) btnTex.onclick = () => {
  texMode = !texMode;
  btnTex.classList.toggle('active', texMode);
  applyMaterialMode();
};
const btnLayers = document.getElementById('btnLayers');
if (btnLayers) btnLayers.onclick = () => {
  layersMode = !layersMode;
  btnLayers.classList.toggle('active', layersMode);
  applyMaterialMode();
};
const btnBones = document.getElementById('btnBones');
if (btnBones) btnBones.onclick = () => {
  bonesMode = !bonesMode;
  btnBones.classList.toggle('active', bonesMode);
  boneGroup.visible = bonesMode;
};

initThree();
loadFiles();
