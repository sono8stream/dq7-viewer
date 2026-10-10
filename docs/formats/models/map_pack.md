# Map Model Pack (`MAP/MAPDATA/*.pack.lz`) Specification

Field/town/dungeon maps are stored as one LZ11-compressed "map pack" per map
code (`MAP/MAPDATA/<mapcode>.pack.lz`, 2222 files, plus `MAP/z01n2f7.pack.lz`).
A pack holds every 3D part of the map, the placement of those parts, the
collision mesh, a few scene parameters and the shared textures. This
document records only structure confirmed against the actual files;
unconfirmed points are marked as such. The webapp's `mappack.py` implements
this layout and the "Map 3D" page renders it.

## Generic chunk container

Every chunk in a pack uses the same container header (all little-endian):

| Offset | Type | Contents |
| --- | --- | --- |
| `+0x00` | char[16] | tag, NUL-padded (`MODEL`, `FldData`, `FILE`, `COLL`, `PARM`, `WNOD`) |
| `+0x10` | u32 | entry count |
| `+0x14` | u32 | data base: entry offsets are relative to *container start + this* |
| `+0x18` | u32 | size of the table area = data base − `0x20` |
| `+0x20` | `{u32 offset, u32 size}[count]` | entry table |

An entry with size 0 is empty. For the top-level container the last entry
ends exactly at the end of the (decompressed) file.

## Top level (`MODEL`, 6 entries)

| # | Tag | Contents |
| --- | --- | --- |
| 0 | `WNOD` | placement nodes (one `GNOD` record per entry) |
| 1 | `MODEL` | nested container: one `FldData` per part |
| 2 | `FILE` | part name tables (`NRML` / `CMMN` / `LODM`) |
| 3 | `COLL` | collision (container of sections, see below) |
| 4 | `PARM` | scene parameters (`BACK` / `CAMR` / `FOG `) |
| 5 | `CGFX` | a CGFX file holding only a `Textures` dict, shared by every part |

Entry 3 is empty (size 0) for packs with no collision (e.g. single animated
objects such as `a_*.pack.lz`).

## `FldData` (one part)

A container with 3 entries:

| # | Contents |
| --- | --- |
| 0 | CGFX with a `Models` dict holding one model, named after the part |
| 1 | CGFX with `Models` + `SkeletalAnims` (may be a tiny placeholder) |
| 2 | CGFX with `MaterialAnims` (e.g. scrolling water), or empty |

### Texture references

The part CGFX normally has no `Textures` dict of its own (the one exception
is `MAP/z01n2f7.pack.lz`, whose part carries its single texture itself).
Each material's texture
mapper points at an inline `GfxTextureReference` object (`TXOB` with type
word `0x20000004`): after the 0x18-byte `GfxObject` header, `+0x18` is a
self-relative pointer to the `Path` string, which is the name of a texture
in the pack's shared `CGFX` (top-level entry 5) or, for the exception above,
in the part's own dict. Across all 2223 packs (78970 shapes) every texture
reference resolves inside its own pack.

### Vertex format and material combiner

Part shapes carry `position`, `color` and `uv0` (float32), no normals; the
lighting is baked into the vertex color (RGBA, 0..1). Every map material
sampled (648 materials in two large maps) has TexEnv stage 0 =
`Modulate(PrimaryColor, Texture0)` with the remaining stages
`Replace(Previous)`, i.e. *texel × vertex color*. Alpha test and face
culling are per material as for any CGFX model.

## `WNOD` / `GNOD` (placement)

`WNOD` is a container; each entry is one `GNOD` record. The word at `+0x08`
is a version that sets the length of the name field:

| Version (`+0x08`) | Name length | Record size | Where |
| --- | --- | --- | --- |
| `0x00010500` | 32 | 0xB0 | all 71213 nodes of `MAP/MAPDATA/*.pack.lz` |
| `0x00010400` | 16 | 0xA0 | only `MAP/z01n2f7.pack.lz` (2 nodes) |

Layout for version `0x00010500` (for `0x00010400` every field after the
name is 0x10 earlier):

| Offset | Type | Contents |
| --- | --- | --- |
| `+0x00` | char[4] | `GNOD` |
| `+0x04` | u32 | node type: `0` = root, `1` = part instance |
| `+0x08` | u32 | version (see above) |
| `+0x0C` | i32 | part index (= `FldData` index in the nested `MODEL`), `-1` for the root |
| `+0x10` | char[32] | name (equals the part's model name and its `NRML` name) |
| `+0x30` | vec4 | translation (w = 1) |
| `+0x40` | vec4 | rotation in radians (x, y, z; only y rotations observed) |
| `+0x50` | vec4 | scale |
| `+0x60` | vec4 | bounding box min, part-local |
| `+0x70` | vec4 | bounding box max, part-local |
| `+0x80` | 0x30 bytes | type/part-specific parameters (not decoded) |

Part geometry is in part-local coordinates: for unskinned parts the node's
bounding box is exactly the part's vertex extent. The world placement is
`translation · rotation · scale · vertex`. The Euler composition order is
unconfirmed because only y rotations occur. Nodes are flat (all directly
under the root); no parent field has been found.

The root node's bounding box spans the whole map including backdrop parts.

## `FILE` (part name tables)

A container of 3 sections, each starting with a 4-character tag and a u32
record count at `+0x08`:

- `NRML`: 0x30-byte records from `+0x10`, name at `+0x00`. `NRML[i]` is
  `FldData` *i*. GNOD nodes reference only these parts (part index < NRML
  count).
- `CMMN`: animated common objects (doors etc., names like `a_wdoor02_1`)
  whose `FldData` follow the NRML ones. They are not placed by `WNOD`.
  Record layout not decoded.
- `LODM`: present, empty in the files checked.

## `COLL` (collision)

A container of sections. Present in 1795 of the 2223 packs. Every `COLL`
has `PLGN`, `GRDS` and `NULL`; most also have `TINF`, `ROOT` and `CELL`;
`AREA` and `PATD` occur in one pack each. Only `PLGN` is decoded:

| Offset | Type | Contents |
| --- | --- | --- |
| `+0x00` | char[4] | `PLGN` |
| `+0x04` | u32 | `0x40` |
| `+0x10` | u32 | polygon count *n* |
| `+0x20` | record[*n*] | 0x80 bytes each |

Polygon record:

| Offset | Type | Contents |
| --- | --- | --- |
| `+0x00` | u32 | `1` = quad, `0` = triangle (4th vertex zero-filled) |
| `+0x04` | u32[3] | attributes (not decoded) |
| `+0x10` | vec4[4] | vertices in perimeter order (w = 0) |
| `+0x50` | vec4 | face normal |
| `+0x60` | vec4 | bounding box min (w = 1) |
| `+0x70` | vec4 | bounding box max (w = 1) |

The bounding box equals the min/max of the 3 or 4 vertices for every record
checked (9970 records in 60 randomly chosen packs). Collision is in world
coordinates (no node transform).

## `PARM` (scene parameters)

A container of 3 sections, each a 16-byte tag followed by data:

| Tag | Data |
| --- | --- |
| `BACK` | vec4 RGBA clear color (0..1) |
| `CAMR` | 4 floats (meaning not decoded) |
| `FOG ` | not decoded (all zero in the files checked) |

## Unresolved points

- Meaning of the `GNOD` `+0x80` parameters, `CMMN` record layout and how
  CMMN objects are placed.
- `COLL` sections other than `PLGN`, and the `PLGN` attribute words.
- `PARM` `CAMR` and `FOG ` fields.
- Skinned parts (bone-animated objects) whose bind-pose vertices exceed the
  node's bounding box.
