# 3D Model Format CGFX (BCRES) / `.bcmdl` Specification

DQ7's (3DS) 3D models use the standard Nintendo 3DS intermediate format CGFX
(extension `.bcmdl`, some `.pack`/`.shp`, all stored as LZ11-compressed
`.lz` files). This document records only the structure confirmed by
analysis of the actual binary (unconfirmed/estimated points are marked as
such).

## File placement

| Location | Extension | Contents |
| --- | --- | --- |
| `CHARACTER/` | `pXXXX_jNN.bcmdl.lz` | LZ11-compressed CGFX (model body) |
| `CHARACTER/` | `pXXXX_jNN.pack.lz` | LZ11-compressed `PackData` container. Contains CGFX (mainly skeletal animation) + CANM |
| `MONSTER/` | `eNNN.bcmdl.lz` | LZ11-compressed CGFX (model body) |
| `MONSTER/` | `eNNN.pack.lz` | LZ11-compressed `PackData`. Contents are CGFX (SkeletalAnims) + CANM |
| `GOODS/` | — | Equipment (hats, etc.) models. Sometimes managed in a separate file from the body mesh |
| `SHAPE/` | `*.shp.lz` | LZ11-compressed `PackData` (small shapes, uninvestigated) |

- LZ11 is standard LZ11 compression with header byte0 = `0x11`.
- `PackData` container: magic `'PackData'` / `+0x10` u32 entryCount / `+0x14`
  u32 tableOfs. From tableOfs, an array of `{u32 absOffset, u32 size}`. One
  entry is `'CGFX'`.

## CGFX (BCRES) top-level structure

All little-endian. "offset"-type fields are in principle **self-relative**
(add the value to the field's absolute position; a value of 0 = null).

```
0x00 'CGFX'  u16 bom(0xFEFF)  u16 headerLen(0x14)  u32 revision  u32 nBlocks
0x14 'DATA'  u32 len
0x1c onward: 15 pairs of (u32 count, i32 selfRelPtr) — pointers to each DICT
     in order: Models, Textures, LUTS, Materials, Shaders, Cameras, Lights, Fogs,
     Scenes, SkeletalAnims, MaterialAnims, VisAnims, CameraAnims, LightAnims, Emitters
```

### DICT

```
'DICT' u32 byteLen  u32 count
followed by (count+1) nodes, each 16 bytes:
  u32 refBit  u16 idxLeft  u16 idxRight  i32 nameSelfRel  i32 dataSelfRel
```
Node[0] is the root of the Patricia trie and holds no data. `dataSelfRel`
points to each object.

### Common serialization rules

- Pointers are self-relative (field position + value read; a value of 0 =
  null).
- A reference field (class type) = `[u32 ptr]`. A list reference =
  `[i32 count][u32 ptr]` (count first, then ptr). A string = `[u32 ptr]`
  only.
- Each object has a TypeChoice discriminator `u32` at its head:
  - `0x40000012` = GfxModel
  - `0x40000092` = GfxModelSkeletal
  - `0x10000001` = GfxShape
  - `0x40000002` = InterleavedVertexBuffer
  - `0x40000001` = GfxAttribute
  - `0x80000000` = FixedVertexAttribute
- Immediately after the TypeChoice discriminator comes `[u32 magic][u32 revision]`
  (for a GfxObject).
- `bool` is 4 bytes (one word) on disk.

### Common GfxObject header

Each object has `u32 flags` immediately followed by a 4CC magic (`CMDL`,
`SOBJ`, `MTOB`, `TXOB`, `SHDR`, etc.), then `u32 revision`, `i32 nameSelfRel`,
`u32 userDataCount`, `i32 userDataSelfRel`. The header ends at
`+0x18` from the discriminator position.

## CMDL (model)

```
+0x24  animGroupCount, +0x28 animGroupDict(selfRel) -> DICT
+0x2c  scale[3] / rot[3] / trans[3] (f32)
+0x50  localMtx 4x3 / worldMtx 4x3
...    meshCount,  i32 meshArraySelfRel  -> i32 array -> SOBJ(Mesh)
...    shapeCount, i32 shapeArraySelfRel -> i32 array -> SOBJ(Shape)
```

**GfxModel (offsets relative to the TypeChoice discriminator)**:
```
+0xc4  shapes.count
+0xc8  shapes.ref (self-relative ptr array -> GfxShape)
```

**GfxModelSkeletal**: `+0xE0` is a reference to the skeleton (see below).

## SOBJ (Shape) / GfxShape

```
+0x2c  subMeshes
+0x38  vertexBuffers
+0x1c  boundingBox
+0x34  vertexBufferCount, +0x38 i32 selfRel -> i32 array -> VertexBuffer objects
```
`vertexBuffers` elements are of 2 kinds:
- `InterleavedVertexBuffer` (typeFlag `0x40000002`)
- `FixedVertexAttribute` (typeFlag `0x80000000`; holds a fixed value, used
  e.g. for boneIndex)

Shape has a `PositionOffset` (`+0x20`) which is added to the final vertex
position.

### InterleavedVertexBuffer

```
+0x00  typeFlag 0x40000002
+0x14  i32 selfRel -> vertex stream body
+0x18  u32 byte length of the stream
+0x24  stride
+0x28  attrCount, +0x30.. selfRel array -> attribute descriptors (GfxAttribute)
```

### GfxAttribute (attribute descriptor)

```
+0x00  typeFlag 0x40000001
+0x04  usage (0=position, 1=normal, 4=uv0, 5=uv1, 8=boneWeight; boneIndex goes through a separate FixedVertexAttribute)
+0x24  format (GL enum: 0x1406=FLOAT, 0x1401=UBYTE, 0x1402=SHORT, 0x1403=USHORT)
+0x28  elements (componentCount; position=3, uv=2, boneWeight=4)
+0x2c  scale (f32)
+0x30  offset
```
Final value = raw × scale.

### GfxSubMesh / per-vertex bone influence (skinning)

```
GfxSubMesh:
  +0x00  boneIndices (list; array of global bone indices this submesh references)
  +0x08  skinning (0/1=rigid-type, 2=smooth)
  +0x0c  faces -> GfxFace
GfxFace:
  +0x00  faceDescriptors -> GfxFaceDescriptor
GfxFaceDescriptor:
  +0x00  format (0x1403=u16 indices, otherwise=u8 indices)
  +0x08  idx.len
  +0x0c  idx.ref (index buffer body)
```

Per-vertex bone influence (up to 4) is expressed in one of two patterns:
1. A `boneIndex` vertex attribute (byte, a local index into the submesh's
   `boneIndices` array) paired with a `boneWeight` attribute.
2. When there is no `boneIndex` attribute, each component order of
   `boneWeight` corresponds directly (positional correspondence) to the
   order of the `boneIndices` array.

The sum of weights is always ≈1.0.

## Skeleton / bind pose

- `GfxModelSkeletal` (typeId `0x40000092`)'s `+0xE0` is the skeleton
  reference (`GfxSkeleton`, typeId `0x02000000`). The Bones dict is at
  `+0x1C` relative to the skeleton.
- Bone record: stride `0xE0`. `+0x08` Index, `+0x0C` ParentIndex, `+0x44`
  LocalTransform (Matrix3x4), `+0x74` WorldTransform (Matrix3x4).
  **`WorldTransform` ships as all-zero and is unusable.** The world matrix
  must be composed yourself from `LocalTransform` and `ParentIndex` by
  walking the parent chain.
- `Matrix3x4` on disk is 12 f32 values in the order
  `M11,M21,M31,M41, M12,M22,M32,M42, M13,M23,M33,M43` (row-major 3x4
  affine; translation is the 4th column of each row). `x' = x*f0 + y*f1 + z*f2 + f3`
  etc.
- Skinning application rules (per submesh):
  - `skinning != 2` (rigid/single bone): transform position/normal using
    the world matrix of the representative bone
    (`boneIndices[ the vertex's boneIndex attribute[0] ]`; index 0 if there
    is no attribute).
  - `skinning == 2` (smooth): blend the world matrices of multiple bones
    using the influence (index, weight) pairs above.

## Textures (TXOB)

```
+0x18  H (height)
+0x1C  W (width)
+0x34  HwFormat (PICA200 texture format ID)
+0x38  Image ref -> ImageData
         ImageData: +0x08 raw.len / +0x0C raw.ref (raw pixel data)
```

### Format and channel order

Formats confirmed in use in DQ7: RGBA5551 (most common) / RGB565 / ETC1 /
ETC1A4 / RGBA4, with a small number of L8/HiLo8/RGB8/LA8.

- 8x8 Morton swizzle layout.
- For RGB565 / RGBA5551 / RGBA4, each bitfield has **R in the high bits**
  (the standard GL order equivalent to `GL_UNSIGNED_SHORT_5_6_5`=0x8363 /
  `..._5_5_5_1`=0x8034).
- ETC1 / ETC1A4 use 4x4 block compression (standard ETC1 rules).
- Only mip0 is a target for decoding (higher mips may require separate
  generation).

### Material (MTOB) texture references

- The model's Materials dict: `model+0xBC count` / `+0xC0 ref` -> array of
  MTOB.
- Fixed reference offsets within an MTOB to texture name strings: `+0x33c`
  (primary/stage 0), `+0x3c8`, `+0x454` (additional stages, up to 3 stages).
- Shape→Material resolution: `GfxMesh`'s `+0x18 ShapeIndex` /
  `+0x1C MaterialIndex`.

### UV channel mapping (`GfxTextureCoord.SourceCoordIndex`)

Which vertex UV attribute (uv0/uv1/uv2) a material's texture stage actually
uses is **not necessarily** the same as the stage number. The actual
mapping is specified by the `GfxTextureCoord.SourceCoordIndex` field within
the material.

Offset derivation (accumulated from field declaration order, relative to
the TypeChoice discriminator position):
```
End of GfxObject header                     : +0x18
Flags/TexCoordConfig/Translucency (3xu32)   : +0x24
Colors (GfxMaterialColor, 11xVector4 + 11xRGBA + CommandCache = 0xE0) : +0x104
Rasterization (GfxRasterization, 0x14)      : +0x118
FragmentOperation (GfxFragOp, 0x50)         : +0x168 (UsedTextureCoordsCount)
TextureCoords[3] start                      : +0x16C
  each GfxTextureCoord is a fixed 0x58 bytes
  SourceCoordIndex = +0x16C + k*0x58 (k is the stage number, 0..2)
```
The value is 0/1/2 (the UV channel number used).

## PICA200 raw command structures (AlphaTest / CullMode / TexEnv)

Some MTOB fields serialize PICA200 GPU commands in an almost raw form.
Scanning the material record byte-by-byte for a fixed command header
constant lets you extract the values without computing positions.

### AlphaTest

A raw dump of 2 words (u32×2):
```
word0 = Param  (bit0=Enabled, bits4-6=Function(PICATestFunc), bits8-15=Reference 0-255)
word1 = header = 0x000F0104 (fixed constant. GPUREG_FRAGOP_ALPHA_TEST(0x0104) | mask(0xf)<<16)
```
Since `word1` is a fixed value common to all MTOBs, scanning for this value
at 4-byte intervals gives you AlphaTest's Param in the preceding word.

Confirmed Function values: `Always` (when disabled), `Greater` (keeps
values at or above the threshold). Materials using other PICATestFunc
values such as `Notequal`/`Lequal` have not been observed in actual game
data.

### CullMode (single-sided / double-sided rendering)

A raw dump of 2 words, scannable the same way using the fixed header
constant `0x00010040` (`GPUREG_FACECULLING_CONFIG(0x0040) | mask(1)<<16`).
Values: `0`=double-sided (Never), `1`=front-face culling (back faces only),
`2`=back-face culling (front faces only; normal single-sided rendering).

### TexEnv (texture combiner)

A material has up to 6 stages of texture combiner settings. Each stage is
serialized as a 6-word Consecutive command block:
```
word0 = Source      (3 slots each for Color/Alpha: Constant/Texture0-2/Previous/FragPrimary/FragSecondary, etc.)
word1 = header       = GPUREG_TEXENV<N>_SOURCE(0xC0 + N*8) | mask(0xf)<<16 | extraParams(4)<<20 | Consecutive(1)<<31
word2 = Operand
word3 = Combiner     (PICATextureCombinerMode for Color/Alpha respectively: Modulate/Interpolate/Add/AddSigned/MultAdd, etc.)
word4 = Color        (constant color RGBA)
word5 = Scale
```
Since `word1`'s header is a fixed constant determined by the stage number N
(0-5, in steps of 8), the same scanning technique as AlphaTest can be used.

- Stage 0 (mapper 0) always renders as the base mesh texture.
- Whether stage 1 or later appears as `Texture1`/`Texture2` in either the
  Color or Alpha source determines whether that texture actually
  contributes to the fixed-function combiner (a texture that never appears
  is likely input dedicated to a separate shader (SHDR), such as a
  non-fixed-function path like a normal map).
- When it does appear, the combiner mode corresponds to: `Interpolate`→
  alpha blending, `Modulate`→multiplicative compositing,
  `Add`/`AddSigned`/`MultAdd` etc.→additive compositing.

**Each mode reads a different number of the 3 source slots** (per-slot
semantics confirmed against SPICA's GLSL emitter): `Replace` reads only
slot 0 (1 input); `Modulate`/`Add`/`AddSigned`/`Subtract`/`DotProduct3Rgb`/
`DotProduct3Rgba` read slots 0-1 (2 inputs); `Interpolate`/`MultAdd`/
`AddMult` read all 3 slots (3 inputs). A slot beyond a mode's input count
still holds a value in the raw word (e.g. a leftover texture ID), but it is
never evaluated — checking "does `Texture1`/`Texture2`'s ID appear anywhere
in the 3 source nibbles" without first truncating to the mode's real input
count will misattribute that unused slot's texture to the wrong stage/role.
(Confirmed on `MONSTER/e001.bcmdl.lz`'s `Material`: stage 0 is
`Modulate(Texture2, Texture0)`, a 2-input mode, with `Texture1`'s ID sitting
in the stage's unused 3rd color-source slot; `Texture1`'s only real use is
stage 1's `MultAdd(Previous, FragmentPrimaryColor, Texture1)`, a 3-input
mode where it's genuinely the additive 3rd term.)

## CANM (skeletal animation)

Skeletal animation is stored not in `.bcmdl` but in the `SkeletalAnims`
dict of the adjacent `.pack`.

### Bone entry discrimination

A CANM bone entry's format branches on the `GfxPrimitiveType` at `+0x08`:
- `8` = `GfxAnimQuatTransform`: raw array format, one sample per frame.
- `5` = `GfxAnimTransform`: independent Hermite/StepLinear quantized
  compressed curve (Euler angle) format for each of the X/Y/Z axes.

### GfxAnimQuatTransform

- The `Inexistent` bit of the bone Flags word determines whether each
  channel (Rotation/Translation/Scale) exists.
- The 3 pointers at `bo+0x0c` / `+0x10` / `+0x14` directly point to the
  Rotation/Translation/Scale channels.
- Each channel has an `IsConstant` flag (stored in the channel's own
  header). When `IsConstant=1`, only a single fixed value is stored for
  the entire clip.

### GfxAnimTransform

A series of quantized keyframes, independently Hermite-interpolated or
StepLinear-interpolated for each of the X/Y/Z axes. Stored as Euler
angles; the Euler→quaternion composition order is specific to this game
(a non-standard composition order different from the usual XYZ/ZYX
conventions — see the implementation for the exact coefficient
derivation). A Scale channel may actually be a genuine Scale track even
when its values are near identity scale (1.0), so distinguishing it from
Translation by shape (byte length/value range) alone can be inconclusive.

## Frame count 0 (fixed pose) clips

A clip with `frames=0` represents the same pose for all frames using a
single fixed value (a QuatTransform channel with `IsConstant=1`).

## Known open issues

- For some CHARACTER models (roughly 213 out of 536 that have a `.pack`),
  the bone data region for certain animation clips (e.g. `_idle`) does not
  match any known header pattern (`GfxAnimTransform` nor
  `GfxAnimQuatTransform`), resulting in zero tracks. The cause, and
  whether another format exists, is unresolved.
- Due to the shared-skeleton mechanism, a single animation clip's bone
  tracks can include bone names that do not exist in the skeleton of the
  model it's being played on (e.g. for job-dependent decorative parts like
  hats and capes). This is a design choice of DQ7's asset reuse, not a
  bug (not missing data — these are "bones that simply don't exist in that
  particular model").
