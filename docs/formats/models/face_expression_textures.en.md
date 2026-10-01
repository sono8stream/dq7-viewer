# Facial Expression (Blink / Lip-Sync) Texture Storage Format

The `_kao` (plain base face) / `_e0` (eyes) / `_m0` (mouth) textures
embedded in `CHARACTER/pXXXX_jNN.bcmdl.lz` are each a single static image
with no variant frames.

The variant images used for blinking and lip-syncing during dialogue are
stored in a separate file: **`TEXTURE/pXXXX_jNN_face.bctex.lz`**.

## File contents

`pXXXX_jNN_face.bctex.lz` exists for each character × job combination, and
each file holds the following textures (RGBA5551, 32x32):

```
pXXXX_jNN_m0 ... pXXXX_jNN_m7   (mouth parts, up to 8. some indices may be missing)
pXXXX_jNN_e0 ... pXXXX_jNN_e8   (eye parts, up to 9. some indices may be missing)
```

Index 0 (`m0`/`e0`) is the same image as the default expression embedded
in the `.bcmdl.lz` body.

## Format

`.bctex.lz` is a format holding only the Textures of a CGFX (BCRES),
LZ11-compressed. It can be read with the same decoding procedure as the
TXOB chunk of the common CGFX structure (see
[`bcmdl_format.en.md`](bcmdl_format.en.md)).

## Unresolved

- Which scene each index (m0-m7, e0-e8) is used in (normal blinking,
  dialogue lip-sync, a specific expression event, etc.) needs to be
  traced from the script-side expression-change opcodes, and has not been
  investigated.
- Some characters have missing indices; whether this is unused space or
  repurposed for another use is unconfirmed.
