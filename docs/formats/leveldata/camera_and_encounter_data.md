# Field Camera / Encounter Data (`LEVELDATA/`) Specification

Data tables stored under the `LEVELDATA/` folder in RomFS, related to the
field camera and encounters. Only structure confirmed via real-hardware
testing and cross-referencing with existing tools is documented here
(unconfirmed parts are explicitly marked as such).

## Common container header

Many files under `LEVELDATA/` share a common 16-byte header:

```
0x00-0x03: magic/hash (4 bytes, varies with file content)
0x04-0x07: record count (int32)
0x08-0x0B: record size (int32)
0x0C-0x0F: record count (int32, same value as 0x04-0x07)
0x10-    : record array
```

## `dq7_camera_param.dat` (12 records × 36 bytes) — the actual field-exploration camera

Confirmed via real-hardware testing to be the table actually used by the
camera during field exploration (`dq7_map_camera.dat` and
`dq7_look_down_camera.dat` were confirmed on real hardware NOT to be used
by the normal field exploration camera).

```
+0x00: id (low byte is the ID, values 0-9, 100, 101)
+0x04: pos.yaw   (float, degrees)  — camera horizontal rotation angle
+0x08: pos.pitch (float, degrees)  — camera look-down angle (larger = closer to straight up)
+0x0C: pos.dist  (float)           — distance between camera and player (radial component of polar coordinates)
+0x10: target.x  (float, unverified) — look-at point offset (presumed relative to player position)
+0x14: target.y  (float, unverified)
+0x18: target.z  (float, unverified)
+0x1C: near clip (float, estimated) — setting this too large clips nearby terrain and darkens the screen
+0x20: far clip  (float, estimated) — setting this smaller narrows the far-draw distance
```

It has been confirmed via real-hardware testing that the `pos` field is
**polar coordinates (yaw angle, pitch angle, distance)**, not Cartesian
coordinates (scaling all three components equally does not change the
angular configuration; changing only the distance component changes
purely the near/far distance).

### `dq7_map_camera.dat` (220 records × 52 bytes)

Camera preset data. Has a layout of the same family as
`dq7_camera_param.dat` (id + pos.xyz + target.xyz + distance/FOV-related
values + an undecoded region), but **confirmed not to be used by the
normal real-hardware field-exploration camera** (no visible change even
with extreme value changes applied to all records at once). Purpose
unconfirmed.

## Map code → floor parameter chain

```
MAP/_list.txt (line number = map serial number)
     │  same serial number
     ▼
LEVELDATA/dq7_floor_list.dat (holds the map code name at the same index, variable-length string records)
     │  same index
     ▼
LEVELDATA/dq7_floor_param.dat (holds int32×3 at the same index, 12 bytes/record)
```

Like every LEVELDATA table, `dq7_floor_param.dat` has a 20-byte header and
its records start at file offset 0x14 (`ExcelBinaryData::getRecordDynamic`).
**Record +0x04 (u8) is the floor's BGM number** (dsno): the number
`DQSoundManager::playTownBgm` looks up in the code's BGM table
(dsno → sound of `SOUND/dq7_sound_data.bcsar`) when the map is entered.
Examples: `m01nout` 5 (`DQ7_BGM_M06_NODOKA`), `c01nout` 4 (`M05_HORN`),
`wld_n01a` 12 (`M13_FIELDS_NOW`). The code table has 34 BGM entries
(dsno 0-33; 32 and 33 are empty).

(Correction: this byte was earlier described as "the low byte of the 3rd
int32 = a `dq7_map_camera.dat` index", counting records from a 16-byte
header. It is the BGM number.)

## `dq7_encount_data.dat` (304 records × 56 bytes) — the encounter table itself

### Whole file

- 20-byte header (nrec=304, recsize=56); record i starts at file offset
  0x14 + i × 56 (`EncountData::setupData` reads it from there; the
  fields it decodes are noted below).
- Record 0 is all-zero (dummy/sentinel). The record number is the battle
  number (`Encount::brew` → `EncountData::setup(battle)`; the script battle
  commands pass it).
- 167 records hold real data. The remaining 137 are "no monster" slots.

### Record structure (offsets from the start of the record)

| off | type | content |
|---|---|---|
| +0x00 | u16 | self-index (exactly matches its position in the array) |
| +0x02 | u16×5 | arrayA: monster ID roster. 0 = empty slot, no duplicates, roughly ascending |
| +0x0c | u16×4 | arrayB: actual formation (the 4 slots that actually appear). May have duplicates; not necessarily a subset of arrayA |
| +0x14 | u16×2 | slots 11 and 12 (read like the others, after +0x18 in slot order); 0 in all records |
| +0x18 | u16 | "rare visitor" slot. A single monster that joins the formation with low probability. Its weight (block 1 below) tends to be the lowest among slots, and metal-type/stronger monsters tend to be placed here |
| +0x1a | u8 | flee (hit-and-run) judgment level threshold. If the player's level exceeds this value, enemies flee. Records with monsters have a median ≈ 33; empty records and boss battles are mostly 99 |
| +0x1b | u8 | **battle BGM number** (dsno; `EncountData::setupData` → Encount+0xc4 → `DQSoundManager::playBattleBgm`). 16 `DQ7_BGM_M17_FIGHT` (212 records), 17 `M18_STRONGERS` (bosses, 63), 30 `M35_ORUGODEMIRA` (6), 0 (23) |
| +0x1c | u8×8 | mid: weighted lottery table for the formation (enemy count/layout). `roll=rand(1..mid[7])`, the first `i` such that `roll<=mid[i]` is the template number. Template i0 = 1 enemy. Smaller values skew toward smaller formations |
| +0x24 | u8 | zone-specific tuning value (range 11-41, bell-curve distribution). Confirmed on real hardware to have no effect on encounter frequency. Purpose unconfirmed |
| +0x25 | u8 | special encounter id (`EncountSpecial::setup`, used when the formation roll picks template 12); mostly 0 |
| +0x26 | u8 | bits 0-2: three flags, bits 5-7: a 3-bit value (`setupData`); 96 (0x60) for almost all records |
| +0x27 | u8 | bits 0-2 and 3-5: two weights of a 3-way lottery made in `EncountData::setup` (with +0x28 bits 0-2) |
| +0x28 | u8 | bits 0-2: third weight of that lottery; bits 3-5: a 3-bit value (`setupData`) |
| +0x29-0x2e | 6 bytes = 12 nibbles | block 1: per-slot "appearance weight" table. Read low-nibble-first; the nibbles correspond 1:1 to `[A0,A1,A2,A3,A4, B0,B1,B2,B3, +0x18, +0x14, +0x16]` (`EncountData::setup` draws a slot with them). Empty slots always have weight 0, filled slots always have weight 1-9. Metal-type slots have a lower weight on average. +0x2e (the last two slots) is 0 in almost all records |
| +0x2f-0x34 | 6 bytes = 12 nibbles | block 2: a table with the same slot mapping as block 1 (low-nibble-first, empty slot = 0); `setupData` passes each through `btl::getAppearCount` (a count) |
| +0x35-0x37 | 3 bytes | `FF FF FF` in almost all records |

(Correction: an earlier version of this table counted records from a
16-byte header, so every offset was 4 too large — the `00 FF FF FF`
"marker at +0x00" was the end of the previous record, the "reserved" +0x18
u16×2 are slots 11-12, and the
"+0x1f always 16" constant is the battle BGM number above.)

Special value: records (12 of them) where arrayA contains 991-999 are
special codes outside the normal monster ID range (presumed to be slots
injected from the script side, e.g. StreetPass, fixed tablet battles,
Monster Park, etc.).

### Map → record mapping

```
room code string (e.g. d07pf3)
     │  looked up in dq7_encount_tile.dat
     ▼
zone ID Z (one of the 3 slots at dq7_encount_tile.dat +0x08/+0x09/+0x0a)
     │  Z → 2Z, 2Z+1
     ▼
dq7_encount_data.dat records #2Z, #2Z+1
```

The two records `(2Z, 2Z+1)` pointed to by a zone ID are used separately
for different areas within the same map (e.g. south side/north side). The
location of the table mapping which area of a map uses which record is
unconfirmed (presumed to be in a tile-attribute layer inside the map
pack).

### `dq7_encount_tile.dat` (747 records × 28 bytes)

| off | content |
|---|---|
| +0x03 | 0xFF for almost all records |
| +0x04 | u16 room-unique ID (range 0-5270. A separate value space from the `dq7_encount_data.dat` index; the zone-ID conversion above sits between them) |
| +0x08 / +0x09 / +0x0a | three 1-byte "encounter zone ID" slots. A single room can have up to 3 different zone IDs depending on condition (terrain/time of day, etc.). Range 0-151 |
| +0x0b〜 | room code string (ASCII, NUL-terminated). Example: `d07pf3` = dungeon 07, past (`p`), equivalent to floor 3 |

### `dq7_field_symbol.dat` (159 records × 20 bytes) — world-map-only roaming symbol table

```
+0x00 u8  id (= record number - 1)
+0x01-03  FF FF FF
+0x04 f32 X (world map coordinate)
+0x08 f32 Y (world map coordinate)
+0x0c u16 mapId (matches the +0x04 value of dq7_encount_tile.dat / dq7_floor_list.dat; without exception, rows for the world map `wld_*`)
+0x0e u16 symId (unique ID per symbol instance; shared across adjacent sub-regions only for the same individual)
+0x10 u32 (almost always 0)
```

This table covers **world-map symbols only**. Symbols on indoor maps such
as dungeons are not included in this table; their spawn positions are
controlled on the ExeFS (executable code) side.

### `dq7_encount_pattern.dat` (145 records × 4 bytes)

A `[id, 3-byte bitmask]` structure with a period of 3 records. The mask's
popcount has a distribution that widens as `id` increases (presumed to be
a probability curve, or a bitfield of enabled slots). Exact meaning
unconfirmed.

## On where encounter frequency is controlled

Within the range tested by changing fields on real hardware —
`dq7_encount_data.dat` (+0x1e, +0x28, the tail region),
`dq7_ai_param.dat` (174 records × 48 bytes, +0x24-0x28), and
`dq7_floor_param.dat` (+0x04; offsets of the old 16-byte-header reading) — **no field controlling the actual symbol
spawn frequency / encounter occurrence frequency on the field has been
found in RomFS-side data**. Frequency control is believed to live in the
ExeFS-side executable code.

## Appendix: `dq7_item_list.dat` (670 records × 52 bytes) — equipment effect parameters

The structure of item data, discovered while tracing the effect of
encounter-deterrent items.

| off | type | content |
|---|---|---|
| +0x00 | u16 | type/flags |
| +0x08 | u16 | name string ID |
| +0x0c | u32 | pointer to the use-effect resource/message template (consumables share a small set of resources) |
| +0x10 | u16 | buy price (0 = not for sale) |
| +0x14 | u16 | sell price |
| +0x16 | u16 | description text ID |
| +0x1a | u16 | effect ID / catalog ID (0 for plain equipment, otherwise unique per item in most cases) |
| +0x1c | u16 | effect parameter |
| +0x20 | u8 | item ID (= record number) |
| +0x22 | s16 | additive value to the parameter pointed to by `+0x2c` (weapons = attack power, armor = defense, etc.) |
| +0x24 | s16 | correction value (often equal to +0x22; for weapons can be negative, presumed to be an accuracy/critical or two-handed penalty) |
| +0x28 | u8 | additional status (various resistances, etc.) |
| +0x2c | u8 | target parameter type for the effect (confirmed on real hardware: 1=attack power, 2=defense, 3=agility, 4=wisdom. Also 5=luck-type accessory, 6=consumable, 7=other consumable, 8=important/event/uncategorized, 9=stone/special, 0=no effect. 1-4 match the order in the status menu) |
| +0x2d | u8 | equipment slot/subcategory (1=weapon, 2=body armor, 3=head, 4=leg-type, 5=accessory, 6=consumable, 7=key item, 9/11=important, 12=stone) |
| +0x33 | u8 | shop-related bitfield (buyable/sellable, etc.) |

`dq7_apprise_item.dat` (664 records × 40 bytes) is a pure
description/text-pointer table and holds no information about effect
type. The actual effects of items (encounter deterrence, etc.) are not
described in RomFS data, and are believed to be dispatched on the ExeFS
side by effect ID (`+0x1a`) or item ID.
