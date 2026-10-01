# `CANM` (Skeletal Animation) Format

The binary structure of skeletal animation clips with magic `CANM`, stored
in the `SkeletalAnims` dictionary inside `CHARACTER/*.pack.lz` (an
LZ11-compressed CGFX pack).

## Top-level structure

What each entry in the `SkeletalAnims` dict points to:

```
+0x00  4CC "CANM"
+0x04  u32 revision (0x07000001)
+0x08  i32 self-rel ref -> clip name string (matches the dict key)
+0x0c  i32 self-rel ref -> type name string (fixed to "SkeletalAnimation")
+0x10  u32 = 1
+0x14  float  total frame count
+0x18  u32 = 24
+0x1c  u32 = 12
+0x20  u32 = 0 (reserved)
+0x24  u32 = 0 (reserved)
+0x28  'DICT' header (readable directly with the existing DICT parser)
       → key = bone name. Matches the skeleton's actual bone names
```

## Two bone entry formats

The storage format of a bone entry (`bo`) splits into two kinds based on
the `GfxPrimitiveType` value at `+0x08`:

### `PrimitiveType==8` (`GfxAnimQuatTransform`, raw sample array)

```
+0x00  u32 flags
+0x04  i32 self-rel ref -> bone name string
+0x08  u32 = 8
+0x0c  u32 = 12
+0x10  i32 self-rel ref -> sample array body
```

Sample array body:

```
+0x00  0 (padding)
+0x04  float  frame count
+0x08  0
+0x0c  0
+0x10~ repeats every 20 bytes:
  [0(pad), qx(float), qy(float), qz(float), qw(float)]  -- quaternion, raw sample per frame
```

The sample count is `round(frameCount) + 1` (includes a closing frame at
the end for looping). For a Translation channel, it's 16 bytes/frame
(`[x,y,z,pad]`; distinguished from rotation by checking the quaternion
norm).

If the `IsConstant` bit is set, only a single sample is stored for the
entire clip, and that one value is duplicated across all frames during
playback.

### `PrimitiveType==5` (`GfxAnimTransform`, Euler + Hermite compressed curve)

A different layout from the raw sample array: Scale/Rotation/Translation
are each held as independent compressed curves (Hermite/StepLinear
quantized keyframes, interpolated from sparse keys) per X/Y/Z axis.

```
Bone entry Flags word: holds Constant/Inexistent bits for each of the
  Scale/Rotation/Translation axes (bit layout follows the reference
  implementation's GfxAnimTransformFlags)

Each channel: a 2-stage reference, header -> CurveFlags -> self-relative
  pointer to the key array (GfxFloatKeyFrameGroup format)
```

There are 8 quantization formats (`Hermite128/64/48`,
`UnifiedHermite96/48/32`, `StepLinear64/32`). Only `Hermite128` has been
confirmed in actual data.

The `IsXConstant` bit in the bone Flags word and the actual `IsConstant`
value in the channel header can disagree. When determining whether a
channel is constant, prioritize the per-channel header; use the bone
Flags word only to determine whether the channel exists (Inexistent).

The Euler→quaternion composition formula uses a composition order that
differs from the common XYZ/ZYX conventions — it's unique to this game
(evaluate the per-axis values, then compose them in the game's own order).

## Distinguishing scale tracks from translation tracks

For the 16 bytes/frame sample array, if all 3 axis values fall within
±0.3 of 1.0, it is judged to be a scale track (close to a constant
identity transform); otherwise it's judged a translation track. This
cannot be distinguished from byte shape alone — it requires judging from
the value range.

## Range of the final bone

For the last bone in a clip, since there is no offset for a "next bone,"
its data range must be clamped to the file length (hard-coding a fixed
length causes out-of-bounds reads for small files).

## Handling of smooth skinning

A "smooth skinning" shape, where a single vertex is influenced by multiple
bones, is stored as a separate submesh kind from rigid skinning, where
each vertex is tied to a single bone.
