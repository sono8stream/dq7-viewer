# Format of the partytalk-series LEVELDATA Files

Scope: `LEVELDATA/dq7_partytalk_chapter1.dat` through `_chapter4.dat`,
`_chapter_ending.dat` (each has a `_index.dat`), and
`dq7_special_party.dat` (no index). This is the data for the lines party
members say when you talk to them ("Talk" with no one in front of you).

The meanings below are read from the code that uses the tables:
`PartyTalk::setFloorDataIndex`, `PartyTalk::setPartyTalkData`,
`PartyTalk::checkCondition`, `PartyTalk::setPickMessage`,
`PartyTalk::setMessageData`, `PartyTalk::getPartyTalk`,
`PartyTalk::setPartyTalkMessage` and the `PartyTalkData` helpers.

> **Correction (earlier versions of this page):** `+0x18` was listed as a
> flag id and `+0x14`/`+0x16` as floor ids. It is the other way round:
> `+0x18` is the floor id (the index key) and `+0x14`/`+0x16` are flags.
> The fields were also read as u16 only, which split the u32 line id at
> `+0x10` into a "serial number" (`+0x10`) and a "6 or 9" value (`+0x12`).

## Common header

All files follow the fixed-length-array header format (`ExcelBinaryData`,
the `getRecordDynamic` formula: `result = descriptor + 0x14 + index * stride`).

```
offset 0x00: a magic-like value (differs per file)
offset 0x04: record count (count)
offset 0x08: stride (bytes)
offset 0x0c: duplicate of count
offset 0x14: start of record array (0x14 + count*stride == file size)
```

## `_index.dat`: floor id → body table range

An 8-byte (u16×4) record: `(floor_id, start_record_idx, record_count, 0xFFFF)`.

`PartyTalk::setFloorDataIndex` (run when a map is entered) looks up the
current floor id in each table's index and keeps `[start, start + count)`.
It reads the tables `chapter1`..`chapter4`, or only `chapter_ending` when
the byte at base VA 0x543364 is 6, and nothing when it is 1.

## Body `.dat` record (chapter1-4 / ending, 36 bytes)

| offset | type | content |
|---|---|---|
| 0x00 | u32 | value of the "just now" condition (`+0x1e` high nibble) |
| 0x04 | u32 | value of condition 1 (`+0x1f` low nibble) |
| 0x08 | u32 | value of condition 2 (`+0x1f` high nibble) |
| 0x0c | u32 | value used by the pick action (`+0x20` low nibble) |
| 0x10 | u32 | message id of the first line |
| 0x14 | u16 | type-0 game flag that must be set (0 = none) |
| 0x16 | u16 | type-0 game flag that must be clear (0 = none) |
| 0x18 | u16 | floor id (the index key) |
| 0x1a | u16 | line count (below) |
| 0x1c | u8 | voice pattern parameter (used when `+0x20` high nibble ≠ 0) |
| 0x1d | u8 | speaker: character id (1 hero .. 6) |
| 0x1e | u8 | bit 0: record disabled; bits 1-3: a line slot to blank (`setPickMessage`); high nibble: "just now" condition |
| 0x1f | u8 | low nibble: condition 1 type; high nibble: condition 2 type |
| 0x20 | u8 | low nibble: pick action; high nibble: voice pattern |
| 0x21 | u8×3 | `FF FF FF` |

The speaker must be in the party and alive (or in state 4).

### "Just now" condition (`+0x1e` high nibble, value `+0x00`)

| type | true when |
|---|---|
| 0 | always |
| 1 | `+0x00` is among the lines heard since the last talk (`PartyTalkData::isPreMessageNo`). `CmdMessage1`/`CmdMessage2`/`CmdSpeakToPlayer1`/`CmdSpeakToPlayer2` and their `WaitClosing` variants reset the list and add every line they show (up to 16); a map change clears it |
| 2 | `+0x00` equals the item last obtained (`PartyTalkData::setPreItem`: `CmdSetItem`, `TaskSearch`) |
| 3 | `+0x00` equals the item last used (`PartyTalkData::setUseItem`) |
| 4 | `+0x00` is in the list filled by `PartyTalkData::setAddPlayer` |
| 5 | `+0x00` equals the value `TaskSearch` stores at `PartyTalk+0x18c` |
| 6 / 8 | a global byte (+0xed / +0xf0) is non-zero |
| 9 / 10 | `PartyTalk+0x146` is non-zero (set by `setExitNo` on arrival) |

### Condition types (`+0x1f`, `PartyTalk::checkCondition`)

| type | true when |
|---|---|
| 1 / 2 | type-0 flag `value` set / clear |
| 3 / 4 | type-1 flag set / clear |
| 5 / 6 | type-2 flag set / clear |
| 7 / 8 | no one holds item `value` / someone (or the bag) holds it |
| 9 / 10 | character `value` is in the party and alive / dead |
| 11 | `PlayerParty::getInitPlayerIndex(value) == 0` |
| 12 | the exit the map was entered by equals `value` |

### Line count (`+0x1a`) and pick action (`+0x20` low nibble)

`n = +0x1a % 1000`.
- Pick action 7 (yes/no): hundreds = lines, tens = lines after "yes",
  ones = lines after "no" (0: the "yes" lines are shown for "no" too).
- Otherwise: tens = lines, ones = extra lines. With tens = 0 the ones digit
  is the line count. The extra lines are shown when the pick action says so:

| pick action | effect |
|---|---|
| 1-6 | on pick: set / clear a type-0 / 1 / 2 flag (`+0x0c`) |
| 7 | yes/no (above) |
| 8 / 9 | extra lines if type-0 flag `+0x0c` is set / clear |
| 10 / 11 | extra lines if item `+0x0c` is held / not held |
| 12 | extra lines if character `+0x0c` is in the party and alive |
| 13 | a different message mode (`setMessageData` sets mode 5) |

Lines are consecutive message ids from `+0x10`. Each line is a message whose
text starts with `#<speaker id>\r\n` followed by the speaker's name macro.

### Choosing a record

`PartyTalk::setPartyTalkData` (on every talk) collects the matching records
of the floor into arrays of **30** per table and into the floor list at
`PartyTalk+0x90` (30 entries of 6 bytes, shared by all tables; nothing
checks the bound). `PartyTalk::getPartyTalk` keeps the records heard the
fewest times (count kept per record, up to 3), prefers those with a
"just now" condition, and picks one at random, avoiding the previous one.

## `dq7_special_party.dat`: a different format

`magic=0x4607, count=137, stride=12` (u16×6). Its record length and field
composition differ from the chapter-series files.

- idx0 (the leading u16) matches the record's serial number (0,1,2,...136),
  and this value is implicitly used as the message ID itself.
- The absence of an `_index.dat` is presumed (unverified) to be because
  this is accessed by the record number being specified directly from the
  script side.
- The remaining 5 u16 fields (idx1-idx5) are undecoded.
