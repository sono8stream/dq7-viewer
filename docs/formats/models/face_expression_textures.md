# Facial Expression (Blink / Lip-Sync) Texture Storage Format

The `_kao` (plain base face) / `_e0` (eyes) / `_m0` (mouth) textures
embedded in `CHARACTER/pXXXX_jNN.bcmdl.lz` are each a single static image
with no variant frames.

The variant images used for blinking and lip-syncing during dialogue are
stored in a separate file: **`TEXTURE/pXXXX_jNN_face.bctex.lz`**.

## File contents

`pXXXX_jNN_face.bctex.lz` exists for each character × job combination
(party members), and NPC models have `TEXTURE/pXXXX_face.bctex.lz` (no job
part). Each file holds textures like:

```
pXXXX_jNN_m0 ... pXXXX_jNN_m7   (mouth parts, up to 8. some indices may be missing)
pXXXX_jNN_e0 ... pXXXX_jNN_e8   (eye parts, up to 9. some indices may be missing)
```

Index 0 (`m0`/`e0`) is the same image as the default expression embedded
in the `.bcmdl.lz` body.

**Correction:** the textures are not always RGBA5551 32x32. Across all 307
face files: 32x32 RGBA5551 (2179 textures), 64x32 RGBA5551 (168),
32x32 ETC1A4 (157), 16x16 ETC1A4 (34), 64x32 RGBA4 (24), 16x16 RGBA5551 (17)
and a few 32x32 / 64x64 RGBA4, 64x64 ETC1A4 / RGBA5551.

Common sets of slots: e0-e2 + m0-m2, m6 (123 files); e0-e2 only (63);
e0-e3, e6-e8 + m0-m7 (44). The name prefix does not always match the file
name (the 20 copies of Kiefer's j00 still say `p0003_j00_*`, and a few NPC
files have a stray prefix such as `p102_*`) - harmless, see below.

## How the game swaps them

From the ExeFS code (base-ROM virtual addresses):

- `CharacterObject::setupFaceAnimation` (`0x1177c8`) builds the path with
  `"TEXTURE/p%04d_j%02d_face.bctex.lz"` (party slots < 7) or
  `"TEXTURE/p%04d_face.bctex.lz"`, loads it, and finds the model's material
  named **`FaceMaterial`**.
- It then files every texture of the face file by the **last two
  characters of its name**: `e`+digit → eye slot <digit>, `m`+digit → mouth
  slot <digit>. The prefix is never compared, which is why the Kiefer copies
  with `p0003_j00_*` names still work. A later texture overwrites a slot;
  empty slots fall back to slot 0.
- `CharacterObject::execute` (calls at `0x119458` / `0x1194a4`) calls
  `CharacterObject::changeTexture(this, faceTextureIndex, mapper, ...)`
  (`0x115f70`), which replaces the texture of FaceMaterial's texture
  mapper `mapper`: eyes use the mapper stored at `[this+0x7d0]` (= 1),
  the mouth `[this+0x7d4]` (= 2, or 1 when the character has no eyes),
  both set from the character record's flags (`+0x50` bit 1, `+0x51`).
- In all 307 models with a face file, FaceMaterial's eye stage holds a
  texture named `<x>_e0` and the mouth stage `<x>_m0`: eye 1 + mouth 2
  (234 models), eye 1 only (72), mouth 1 only (1).

What the slots look like (e.g. NPC p0122): `e1` eyes closed, `e2` narrowed
eyes, `m1` / `m2` / `m6` open mouths of different sizes.

## Viewer

The model page shows **Eyes** / **Mouth** selectors in the 3D toolbar when
the model has a face file: picking a slot swaps the texture of FaceMaterial's
eye / mouth stage, the same stages the game uses (taken from the model's
`<x>_e0` / `<x>_m0` texture names, since the viewer has no character
record). The info panel lists every slot as thumbnails.
API: `/api/model` returns `face: {file, eyes: [{slot, name}], mouths: [...]}`
and `faceStages: {eye, mouth}` on the FaceMaterial shape;
`/api/model/face_texture?file=<model>&name=<texture>` serves one variant.

## Format

`.bctex.lz` is a format holding only the Textures of a CGFX (BCRES),
LZ11-compressed. It can be read with the same decoding procedure as the
TXOB chunk of the common CGFX structure (see
[`bcmdl_format.md`](bcmdl_format.md)).

## Unresolved

- Which scene each index (m0-m7, e0-e8) is used in beyond blinking
  (`CharacterEyeAnimation`) and lip-sync (`CharacterLipAnimation`) - e.g.
  script expression-change opcodes - has not been traced.
- Some characters have missing indices; whether this is unused space or
  repurposed for another use is unconfirmed.
