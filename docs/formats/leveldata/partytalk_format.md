# Format of the partytalk-series LEVELDATA Files

Scope: `LEVELDATA/dq7_partytalk_chapter1.dat` through `_chapter4.dat`,
`_chapter_ending.dat` (each has a `_index.dat`), and
`dq7_special_party.dat` (no index). This is the data for conversations
heard by talking to party members while walking around town.

## Common header

All files follow the fixed-length-array header format (`ExcelBinaryData`,
the `getRecordDynamic` formula: `result = descriptor + 0x14 + index * stride`).

```
offset 0x00: a magic-like value (differs per file, purpose undecoded)
offset 0x04: record count (count)
offset 0x08: stride (bytes)
offset 0x0c: duplicate of count
offset 0x14: start of record array (0x14 + count*stride == file size)
```

## `_index.dat`: flag_id → body table range lookup

An 8-byte (u16×4) record: `(flag_id, start_record_idx, record_count, 0xFFFF)`.
The trailing `0xFFFF` is a fixed padding/terminator marker.

The `+0x18` offset field (the flag_id field, below) of each record in the
body table matches the index's `flag_id`. The body table is laid out
contiguously, grouped in ascending order of flag_id, and `_index.dat` is
an index giving the start/count of each group.

## Body `.dat` record structure (common to chapter1-4/ending, 36 bytes, u16×18)

| field | offset | content | confidence |
|---|---|---|---|
| idx0 | 0x00 | message ID | confirmed |
| idx1-idx7 | 0x02-0x0F | always 0 (reserved region) | - |
| idx8 | 0x10 | a value that looks like a record serial number (not a message ID) | unconfirmed |
| idx9 | 0x12 | only the two values `6` or `9` observed | unconfirmed (possibly a table type/category) |
| idx10 | 0x14 | floor_id | confirmed (that it is a floor_id itself) |
| idx11 | 0x16 | floor_id (often pointing at a different map) | confirmed (that it is a floor_id value). Its relationship to idx10 (range vs. independent condition) is unconfirmed |
| idx12 | 0x18 | flag_id (matches the `_index.dat` key) | confirmed |
| idx13 | 0x1A | small integers (1-4, 11-14, 21, 22, 31, 110-122, 191, 211, 212, etc.) | unconfirmed |
| idx14 | 0x1C | mostly multiples of 256, occasionally a remainder | unconfirmed (possibly a bitfield) |
| idx15 | 0x1E | many values (frequently combinations of powers of 2) | unconfirmed (possibly a bitfield) |
| idx16 | 0x20 | always `65280` (0xFF00) | padding/sentinel |
| idx17 | 0x22 | always `65535` (0xFFFF) | padding/sentinel |

`idx14`/`idx15` are likely fields that bit-OR together several boolean
conditions. `idx13` appears to have some regularity in its ones and tens
digits, but it is unconfirmed whether it's a composite code such as
"character number × variant number."

## `dq7_special_party.dat`: a different format

`magic=0x4607, count=137, stride=12` (u16×6). Its record length and field
composition differ from the chapter-series files.

- idx0 (the leading u16) matches the record's serial number (0,1,2,...136),
  and this value is implicitly used as the message ID itself (unlike the
  chapter series, there is no explicit msgid field).
- The absence of an `_index.dat` is presumed (unverified) to be because
  this is accessed by the record number being specified directly from the
  script side, rather than via a flag_id range search.
- The remaining 5 u16 fields (idx1-idx5) have value ranges exceeding the
  table's own record count, so they are not self-references; they may be
  flag_id candidates/bitmask conditions of the same kind as idx13-idx15 in
  the chapter series, but this is unconfirmed.

## Unverified / unresolved points

- Whether the value range of idx12 (flag_id) fits within the bit count of
  the save's GameFlag (it may be a separate value space).
- Separating whether the two floor_ids, idx10/idx11, are a "range" or
  "independent conditions."
- The true nature of idx13/idx14/idx15 (possibly discoverable by analyzing
  the related classes on the ExeFS side).
- The true nature of idx1-idx5 in `dq7_special_party.dat`, and its
  relationship to the chapter series.
- This specification was derived from static analysis and data
  cross-referencing only; no real-hardware behavioral verification has
  been performed.
