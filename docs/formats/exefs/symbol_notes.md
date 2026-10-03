# Notes on field-symbol related data structures

## `dq7_monster_param.dat`

601 records × 136 bytes. Record index = monster ID (confirmed by an ASCII
string of the monster's own ID appearing at the end of each record).

Several float fields exist near the start; the meanings confirmed so far:

- `+0x0c`: battle-camera distance/field-of-view parameter (not a model
  scale — lowering the value brings the camera closer, making the enemy
  fill more of the screen)
- `+0x08`, `+0x10`, `+0x14`, `+0x40`, `+0x44`: a group of float fields
  related to the model's display scale during battle (individual
  contributions not yet separated)
- `+0x2c`/`+0x30`: always a pair of equal values; confirmed not to be a
  visual scale

This table has no field controlling the visible size of symbols displayed
on the field (map). The size of field symbols appears to depend on the
scale of the symbol's own model/skeleton.

## `dq7_field_symbol.dat`

159 records × 20 bytes. **An anchor coordinate table used only for roaming
symbols on the world map (`wld_pNNx`/`wld_nNNx`)**; symbol spawn positions
on dungeon/field maps are not controlled by this table.

```
+0x00 u16  id (0xFF00 | sequence number)
+0x02 u16  0xFFFF marker
+0x04 f32  X coordinate (world-map tile coordinate system)
+0x08 f32  Y coordinate
+0x0c u16  mapId (matches +0x04 of dq7_encount_tile.dat; only when the value is a wld_* map)
+0x0e u16  symId (unique symbol instance ID; shared only by instances spanning adjacent sub-regions)
+0x10..   0
```

The correspondence "mapId = 5000 + the floor_list's grp value" is a
convenient observation that holds only for world-map locations, and cannot
be applied to ordinary dungeon/town maps.

## `.pack.lz` scene-graph structure for dungeon/valley maps

`MAP/MAPDATA/*.pack.lz` is LZ11-compressed (header `11 <u24 decompressed
size LE>`). After decompression, it is a CGFX scene-graph container
starting with `"MODEL"`, followed after the header by a `WNOD` (world node
table) → numerous `GNOD` (named nodes).

Main fields of a `GNOD` record (0xB0 stride):

```
+0x30 f32 posX
+0x38 f32 posZ
+0x44 f32 rotY
+0x50-0x58 scale
+0x60-0x7c AABB
```

The coordinate system is a separate local coordinate system
(observed range roughly -40 to +55) distinct from the gameplay tile
coordinate system (0-176).

Example node composition: `<name>` (the terrain body), `<name>msk1`
(mask mesh = walkable/collision area, one per map), `<name>ent` (entrance
geometry), `<name>wt1` (water), `<name>iwa` (rocks), decorative objects
(bushes etc., placed multiple times), `d_kaidan01`/`u_kaidan01` (stairs =
inter-map link nodes).

**This scene graph does not contain a raw tile-grid array or a symbol-
spawn-coordinate array.** Collision is mesh-based (`msk1`); maps are
composed as 3D mesh scenes rather than 2D tiles. The data that determines
symbol spawn positions, detection/pursuit radius, and dimensions is not
found in any RomFS-side table, and appears to be computed at runtime on the
ExeFS side (ARM code).
