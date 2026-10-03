# Save Data (`save00N.bin`) Structure

## Overall Layout

The save file is a container structure in which `SaveDataSerialize` manages
multiple sub-objects laid out consecutively. Each sub-object commonly has a
16-byte header of "4-byte ASCII magic + version (4 bytes) + size (4 bytes) +
reserved (4 bytes)", immediately followed by the data body.

Actual offsets for the 6-member party (the unpatched base format), confirmed
by scanning an actual legitimate save file:

| Offset | Magic | Size | Contents |
|---|---|---|---|
| `0x10` | `FLAG` | 592 bytes | GameFlag (flag bit array) |
| `0x260` | `STGE` | 672 bytes | StageInfo (current location / church-return info) |
| `0x500` | `PRTY` | 1904 bytes | PartyStatus (formation, gold, bank, casino, item bag) |
| `0xc70` | `FLAG` | - | PlayerDataContainer header (a different structure from GameFlag that reuses the same magic) |
| `0xc80`~ | `DATA`×6 | 492 bytes each | PlayerData (one character each, 6 in a row) |
| `0x1810` | `OPTN` | 32 bytes | unidentified |
| `0x1830` | `FLAG` | 6496 bytes | BattleResult (monster-book/kill-count battle record data; a separate instance from GameFlag that just reuses the same magic) |
| `0x3190` | `STRY` | 176 bytes | StoryStatus (chapter number) |
| `0x3240` | `GAME` | 32 bytes | unidentified |
| `0x3260` | `WLDA` | 48 bytes | WorldAtlas (world-map current location, facing, vehicle state) |
| `0x3290` | `SCRP` | 48 bytes | unidentified (estimated to be script-related) |
| `0x32c0` | `SURE` | 3824 bytes | StreetPass-related (`DQ7SurechigaiBox` etc.) |
| `0x41b0` | `IMIN` | 3568 bytes | Imin Village-related (`IminnMenuMain` etc.) |
| `0x4fa0` | `SILS` | 48 bytes | unidentified |

When the 7-member party mod (the `matilda_7slot`-series patch) is applied,
`PlayerDataContainer`'s size field changes from `0xB98` to `0xD84`
(16+7×0x1EC), and because the `DATA` records increase to 7 entries
(492 bytes × 7), every block after it shifts uniformly by +496 bytes.

## PlayerDataContainer / PlayerData (character records)

### Container header

```
+0x00 "FLAG"           magic
+0x04 0x00010000       version
+0x08 size             total from getSerializeSize() (6 members = 0xB98, 7 members = 0xD84)
+0x0c 0                reserved
+0x10 DATA records × N (N = number of living characters, in 492-byte increments)
```

### PlayerData (one character, `DATA` record, 492 bytes = 0x1EC)

```
+0x00 "DATA"           magic
+0x04 0x00010000       version
+0x08 0x000001EC       size
+0x0c 0                reserved
+0x10~ body data        (status, equipment, string fields, etc.)
```

In memory, one character's record is laid out in 1064-byte increments, and
the 0x1EC (492) bytes starting right after skipping the first 8 bytes of
each record match almost exactly the on-disk record body (the range
corresponding to `+0x10` and onward above). String fields (equipment names,
etc.) are stored in a separate in-memory region and are packed into the
corresponding fields via `memcpy_s` at serialization time.

## GameFlag

See [gameflag_bitfield.md](../exefs/gameflag_bitfield.md) for the
detailed bitfield specification.

- Block header (16 bytes, file offset `0x10`): `FLAG` + version + size + reserved
- The data body starts at file offset `0x20`, right after the header
  (`FLAGS_REGION_BASE = 0x20`)
- type0 bits live at `0x20 + flag_id//8`, type1 bits at `0x220 + flag_id//8`
  (a separate byte array offset by 0x200 bytes from the type0 array; see the
  linked document for details)

## StageInfo

- Header (16 bytes, file offset `0x260`): `STGE` + version 0x10000 + size
  `0x29c` (668) + reserved
- The body holds the current map ID (2 bytes), x/y/z coordinates (4 bytes
  each), a church-return index (2 bytes), plus `SymbolFlag`/`FurnFlag` bit
  arrays that track NPC/furniture object visibility per map.
- The current-location/coordinate fields are meant to hold the value at the
  exact moment save processing was invoked; using a value read at a
  different time as-is can produce an invalid value.
- `StageInfo::loadChurch`/`returnChurch` look up the corresponding record in
  the `LEVELDATA/dq7_map_church.dat` table from the church-return index and
  back-calculate the actual map ID/coordinates to determine the return
  destination.

### `dq7_map_church.dat` (church table) format

```
offset 0x00: fixed value (0x5302, meaning unresolved)
offset 0x04: record count (89)
offset 0x08: stride (0x20 = 32 bytes)
offset 0x0c: duplicate record-count field
offset 0x14: record array start
```

Each record (32 bytes):

```
+0x04 (4 bytes)  unidentified
+0x08 (8 bytes)  coordinate-system value
+0x10 (2 bytes)  map ID
+0x18 (2 bytes)  facing
+0x1b (1 byte)   vehicle type
```

## PartyStatus

- Header (16 bytes, file offset `0x500`): `PRTY` + version + size + reserved
- The body (starting at file offset `0x510`) contains the party formation
  (an array of u32×6 holding living character IDs; empty slots are 0), gold,
  bank balance, casino coins, and the item bag (item ID array + count
  array).
- The formation array is "packed from the front, with empty slots as 0 at
  the tail"; even in actual legitimate save files, a state where all 6 slots
  are filled has not been observed (i.e. having no wiped-out formation slot
  appears to be impossible by design).

## StoryStatus (chapter number)

- Header (16 bytes, file offset `0x3190`): `STRY` + version 0x20000 + size
  176 + reserved
- Right after the header, at +0x14, holds the current chapter number as 1
  byte.
- `StoryStatus::setChapter(chapter)` updates the chapter number, and only
  when transitioning to `chapter==9` (a special value believed to be
  post-ending) also saves the previous chapter number to header+0x15
  (equivalent to `prevChapter`) and simultaneously sets another global flag.

## BattleResult (monster book / battle record data)

- Header (16 bytes, file offset `0x1830`): `FLAG` + version + size `0x1960`
  (6496) + reserved (shares its magic with `GameFlag` but is a separate
  instance / separate class)
- A data block dedicated to the monster book and battle records, holding
  per-monster encounter counts, gold earned, experience earned, item
  acquisition status, kill ("stamp") flags, etc. Unrelated to town NPC
  visibility or story-progress flags.

## Checksum

The signed integer stored in the first 4 bytes of the save file must match
the sum obtained by adding, as signed bytes, every byte from file offset
`0x10` through the end of the file.

```
sum = signed_byte_sum(buf[0x10:])
ok  = (stored_checksum == sum)
```

## Load-time validation logic (`SaveData::deserialize`)

When loading a save, meeting any of the following conditions causes it to
be judged "corrupted" and the load to be rejected:

| Return value | Cause |
|---|---|
| 1 | file could not be opened |
| 2 | number of bytes read does not match the file size |
| 4 | file size is 0 |
| 5 | overall checksum mismatch |
| 6 | one of the sub-objects' `deserialize()` returned an error |
| 0 | success |

One of the main causes of return value 6 is header validation of
`PlayerDataContainer`:

```
magic does not match "FLAG"              -> error 1
version is not in the 0x10000 family     -> error 2
size does not match the current .code's getSerializeSize() -> error 3
```

In other words, the `PlayerDataContainer` size field inside a save file must
match exactly "how many character slots the loading `.code` build has" (6
members = `0xB98`, with the 7-member patch applied = `0xD84`). `GameFlag`'s
own header has no equivalent magic/version/size validation implemented.

## Related file (implementation reference in `webapp/`)

- `compute_checksum()` in `webapp/save_editor.py` (`CHECKSUM_START=0x10`)
