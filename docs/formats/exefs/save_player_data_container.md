# Save data: `PlayerDataContainer` and the NCCH/ExeFS container structure

## `PlayerDataContainer` (the character array in the save)

`PlayerDataContainer::serialize`/`deserialize` (inside ExeFS `.code`) writes
to/reads from the save file a fixed number of entries from the start of the
in-memory `PlayerData` array (one record fixed at 1064 bytes).

```arm
mov r4, 1
loop:
  ; r0 = base + r4*1064 + 8   (one in-memory struct record = 1064 bytes)
  bl PlayerData::serialize
  add r4, r4, 1
  cmp r4, 7        ; loop continuation condition; unmodified code runs r4=1..6, i.e. 6 times
  add r5, r5, 0x1ec  ; advance the save-side output pointer by one record (0x1EC = 492 bytes)
  blt loop
```

- `getSerializeSize` returns the total container size as a fixed value
  (16-byte header + record count × 0x1EC; `0xB98` for 6 people)
- `PlayerDataContainer::initialize` always sets up 46 people's worth
  (corresponding to index 1-45 of `dq7_character_init_data.dat`) in the
  in-memory array at startup. **The in-memory array already has capacity
  for at least 46 people; the count is narrowed down only at the
  save-writing stage.**

### Character record self-describing header (16 bytes, common to every record)

Each character record in the save has a self-describing sub-header at its
head, in the same format as the container header:

```
+0x00  "DATA" (4-byte magic)
+0x04  u32: 0x00010000 (version)
+0x08  u32: 0x000001EC (=492, this record's own size)
+0x0C  u32: 0 (reserved/padding)
+0x10  u8:  character number (1-indexed sequence number; 1 for record 0)
+0x11  u8:  consistently 5 across known records (meaning unconfirmed)
+0x12  u16: fixed at 0
+0x14  the character's own fields (exp, etc.) begin here
```

The container as a whole (`PlayerDataContainer`) also has a header with the
same "FLAG" magic format, forming the same kind of nested structure (a
header wrapping the whole container, plus an individual header per
element — a doubly self-describing structure).

### The formation coordinate array inside `PlayerManager::addPlayer`

The processing that shifts party standing positions (coordinates/rotation)
performs an upper-bound comparison against a runtime variable referencing
the current headcount (`PlayerManager object +0x120`).

```arm
cmp r0, 6      ; r0 = current party headcount
bge ...        ; skip this coordinate-shift processing if 6 or more
...
cmp r4, 6      ; the same loop's termination condition
```

This array is a separate coordinate buffer for the party-formation UI,
distinct from `PlayerDataContainer`'s save array. In practice, adding a 7th
member did not reveal any bug caused by this upper bound; the array itself
likely has more headroom than the save's count limit (details unconfirmed).

### `PlayerManager::setPartyControl`: determining player-controllable vs. AI

Processing that builds, per party member, an action node (behavior tree,
constructed per node type via `fcn.0018fae4`) representing whether the
character is "player-controllable" or an "AI-controlled support character."
The branch uses a 1-byte value representing the character's category
(ASCII `'w'`/`'e'`/`'f'`/`'x'`, `0x82`, etc.), obtained via a generic
table-lookup helper (the same pattern function as `PlayerData::getJob()`:
`result = *(array) + 0x14 + index * stride`). Whether the referenced table
is `dq7_player_job.dat` itself or a separate field in the character
initialization data is unconfirmed.

`dq7_player_job.dat` is a job-definition table of 55 records × 188 bytes.

## NCCH / ExeFS container format (verified against real data)

### NCCH header (offsets relative to the `NCCH` magic)

- `+0xA0` ExeFS offset (media units, ×0x200)
- `+0xA4` ExeFS size (media units)
- `+0xA8` ExeFS hash region size (media units)
- `+0xB0`/`+0xB4` RomFS offset/size
- `+0xC0`-`+0xE0` ExeFS superblock hash (SHA256, 0x20 bytes)
- `+0xE0`-`+0x100` RomFS superblock hash

Bit 0 of ExHeader `+0x200+0xD` is the `CompressExefsCode` flag (whether
`.code` is BLZ-compressed).

### ExeFS header (0x200 bytes)

- `+0x00`-`+0xA0`: 10 entries × 16 bytes (name[8] + offset[4] + size[4])
- `+0xC0`-`+0x200`: 10 × 32-byte SHA256 hashes

**Hashes are stored as "entry index `i`'s content → fixed slot `9-i` out of
10"** (not a position relative to the number of files, but a fixed layout
that always fills from the end). For example, with a 4-file configuration
(`.code`=idx0, `banner`=idx1, `icon`=idx2, `logo`=idx3), the hashes go into
slots 9, 8, 7, 6, and slots 0-5 are all zero.

Each file's data offset is aligned to 0x200-byte units. All offset/size
values are unsigned u32 in media-unit (×0x200) terms.
