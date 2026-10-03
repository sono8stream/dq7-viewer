# Character Status Data File Specification

Scope: binary tables under RomFS's `LEVELDATA/`, related to the status of
playable characters, guests, and NPCs.

## File list

| File | Size | Header | Record count/size | Content |
|---|---|---|---|---|
| `dq7_player_level1.dat` – `_level6.dat` | 4020 bytes each | nrec=100, rsize=40 | 100×40 bytes | Per-level status growth table for the 6 main-story playable characters (record index = level, 0 = dummy, 1-99) |
| `dq7_character_init_data.dat` | 7932 bytes | nrec=46, rsize=172 | 46×172 bytes | Initialization data for all characters (the main 6, guests, and special NPCs) |
| `dq7_chara_list.dat` | 77888 bytes | nrec=927, rsize=84 | 927×84 bytes | 3D-model-related numeric list for all characters/NPCs (contains no status data) |
| `dq7_player_job.dat` | 10360 bytes | nrec=55, rsize=188 | 55×188 bytes | Definitions for the 55 jobs |
| `dq7_job_level.dat` | 84 bytes | nrec=8, rsize=8 | 8×8 bytes | Thresholds for the 8 job proficiency ranks |

## `dq7_player_levelN.dat` record structure (40 bytes)

```
+0x00  u16  tag (purpose unconfirmed)
+0x02  u16  0xFFFF marker (record 0 is all-zero)
+0x04  u32  cumulative EXP to reach this level
+0x08  u16  STR-equivalent stat
+0x0a  u16  AGI-equivalent stat
+0x0c  u16  LUCK-equivalent stat
+0x0e  u16  WIS-equivalent stat
+0x10  u16  max HP
+0x12  u16  max MP
+0x14〜0x27  unused (zero padding)
```

- No value equivalent to defense is stored (this title derives defense via
  a different formula).
- The correspondence between file number (1-6) and character ID (1-6) is
  **confirmed** by a direct, record-by-record byte comparison against the
  `+0x32`〜`+0x3c` fields of the separate file
  `dq7_character_init_data.dat` (see below).

## `dq7_character_init_data.dat` record structure (172 bytes, 46 records, index = character ID space)

```
+0x00  u16 0x0000 + u16 0xFFFF marker
+0x04  u32  initial EXP
+0x08/+0x0c/+0x10  float×3  initial position X/Y/Z (estimated)
+0x14/+0x18        float×2  purpose unknown (sparsely non-zero)
+0x1c/+0x20/+0x24  float×3  orientation/scale (estimated)
+0x28/+0x2c        float×2  purpose unknown
+0x30  u16 self_index (always matches the record's own index)
+0x32  u16  STR-equivalent stat
+0x34  u16  AGI-equivalent stat
+0x36  u16  LUCK-equivalent stat
+0x38  u16  WIS-equivalent stat
+0x3c  u16  HP
       u16  unk4 (almost always 0)
+0x40〜0x48  purpose unknown (almost entirely zero)
+0x4c  u32  gender (271=male, 272=female, 273=other/non-human)
+0x50〜0x68  almost entirely zero
+0x6c  u32  value that looks like a record-creation sequence number (presumed informational only)
+0x70  u32  purpose unknown
+0x74  u32  initial level
+0x78..  ASCII "pNNNN"/"bNNNN" model name string (the 1 byte immediately before it is the model number as a decimal value)
+0x90  u32 (only the upper u16 is used)  code indicating character category (exact meaning and propagation path unconfirmed)
+0x94〜0xa8  unused (all zero)
```

- `+0x32`/`+0x34`/`+0x36`/`+0x38`/`+0x3c` (STR/AGI/LUCK/WIS/HP) have been
  confirmed, via real-data comparison, to **completely match, field for
  field**, the level-1 record of `dq7_player_levelN.dat` for the 4
  main-story playable characters. In other words, the corresponding
  fields in this table hold the same values as "that character's status
  at level 1."
- The `+0x90` field takes the following observed values (meaning and
  downstream propagation path unconfirmed): `0x08` (a single record
  only) / `0x10` (4 records) / `0x310` (1 record, with an additional bit
  set) / `0x1c` (a group with real data such as placement coordinates) /
  `0x20` (a group where position/orientation etc. are all zero) / `0x28`
  (another group, where the HP field has an individual value).
- `+0x74` (initial level) and `+0x04` (initial EXP) have been confirmed,
  by byte-matching against real new-save data, to be the values that are
  copied in bulk — including for characters not yet in the party — into
  the Charactors slots for the main-story playable roster (character IDs
  1-6) when the game creates a new save.
- Records whose `+0x90` field belongs to the group "accompanied by real
  data such as position/orientation" have individual fixed values for
  STR/AGI/LUCK/HP. The field equivalent to WIS is uniformly 0 for these
  records. HP is, for most records in this group, a common high fixed
  value (999), while a different group (treated as placeholders with
  unset coordinates, etc.) has all fields including HP at 0. Yet another
  group (special characters) has individually crafted HP values (in the
  range of roughly 300-3000).

## `dq7_chara_list.dat` record structure (84 bytes, 927 records)

A listing of all characters and all NPCs, not party-exclusive. Cross
comparison confirmed that it contains no status-like fields and is
centered on 3D-model-related numeric values (float groups presumed to be
bounding-box dimensions/scale).

```
+0x00  u16 asset_tag (roughly sequential per record) + u16 0xFFFF marker
+0x08..0x44  float×16  3D-model-related dimension/scale values (exact assignment unconfirmed)
+0x4c..  ASCII "pNNNN"/"bNNNN" model name (not at a fixed offset — the safe extraction method is to search the region for the "p0" string, since the leading padding length varies per record)
```

## Function path for status generation (ExeFS, ARM, file offsets based on the base game)

- `PlayerDataContainer::initialize` (`0x12ce18`) calls
  `PlayerData::setup(this=slot, arg2=id, jobId=id)` for all character IDs
  1-45.
- `PlayerDataContainer::deserialize` (`0x23e43c`) overwrites the
  post-`setup()` state with values from the save's Charactors block, for
  character IDs 1-6 only.
- `PlayerData::setup` (`0x223ab4`) branches on whether the given ID is 1-6
  to decide whether additional initialization happens, while copying
  fields from the corresponding record of `dq7_character_init_data.dat`
  into `this`, and then, using the HP/MP multiplier fields (`+0x3d`/`+0x3e`)
  of a separate table (indexed by job ID, descriptor `0x3ef540`/`0x679994`),
  passes the computation `final value = floor(base value × multiplier ÷ 10)`
  to `HaveStatus::setHpMax` (`0x123bf0`) / `setMpMax` (`0x123b98`).

## Corresponding APIs in the web viewer

- `parse_player_stats()` / `/api/player_stats`
- `parse_character_init_data()` / `/api/character_init_data`
- `parse_chara_list()` / `/api/chara_list`

## Unconfirmed / unresolved points

- The meaning of the `+0x00` tag field in `dq7_player_levelN.dat`.
- The full path by which the `+0x90` field of
  `dq7_character_init_data.dat` propagates into the "playable/AI" judgment.
- The exact individual assignment of the float×16 in `dq7_chara_list.dat`
  (precise correspondence to min/max/scale, etc.).
- Details of the job-correction fields in `dq7_player_job.dat`
  (188 bytes × 55).
- The meaning of `PlayerData::setup`'s `arg2` argument, and the exact code
  location where `+0x24`/`+0x2a` (the final storage fields for HP/MP base
  values) are written.
