# Developer-Facing Debug-Related Data

## `dq7_script_sample_list.dat`

Header (20 bytes, u32×5): `(magic, count, record_size=56, duplicate of
count, reserved=0)`. In this title `magic=15167, count=18,
record_size=56`, and the file terminates after exactly 18 records. Each
record has the structure
`[id:u32][category:u32][type:u8][UTF-8 label][zero padding]`.

The observed category values are 7 kinds: `0x1195`/`0x1260`/`0x1261`/
`0x1262`/`0x1263`/`0x1196`/`0x11ae`, which appear to be category IDs
corresponding to classifications of script opcodes (message-related,
object-manipulation-related, fade/map-transition-related, etc.). The 18
labels are limited to basic operations such as message display,
object move/toggle/rotate/collision/display/configuration, menu display,
player lock, fade effect, and map transition — it does not cover every
opcode (as the "sample" in the file name suggests).

This is presumed to be label data for a developer-facing "command browser
that invokes script opcodes by category." Whether this feature is
actually callable in the retail ROM is unverified.

## `dq7_command_cache.dat`

Has a header of the same format,
`[magic=14601][count=81][record_size=4][duplicate of count][reserved=0]`,
followed by 81 `[u16 value][u16=0xffff (terminator marker)]` pairs. Values
range from 498 to 4037 and include many sequential clusters (e.g.
1182-1185, 4001-4037). Purpose unconfirmed (likely a resource ID cache,
but not conclusively determined).

## The Siren engine's debug menu system

The following strings and class names exist in the ARM executable code,
confirming that a developer-facing debug menu system
(`DebugMenuHelper`/`DebugMenuNumber`) is built in at the engine level.

```
DEBUG, DEBUG/ASSERT, DEBUG/CAPTURE, DEBUG/SAVE, DEBUG/KEYRECORD, DEBUG/LOG
siren::canvas::DebugMenuHelper::DebugMenuHelper()
siren::canvas::DebugMenuNumber::DebugMenuNumber()
```

These appear to originate from Square Enix's "Siren" engine. Since UI
label strings are not hardcoded on the ARM code side and are designed to
be read from external data (MESS, etc.) instead, the byte sequences for
Japanese labels do not appear inside the code.

The `DEBUG2/KEYRECORD/` and `DEBUG2/KEYRECORD_WIN32/` folders directly
under the RomFS root contain `startup000.dat` through `startup012.dat`,
presumed to be key-input recording data from development.

## Battle debug items

`dq7_item_list.dat` (fixed 52-byte records) has 2 surviving battle-test
items with no acquisition route in normal play (at offsets `0x6574` and
`0x65a8`). From the content of their description text, one appears to be a
debug item with the effect of "wiping out the enemy side," and the other
"wiping out the ally side." The record structure is
`[desc_msgid:u32][???:u32][0:u32][???:u32][???:u32][???:u16?][???:u16?]...`,
and the meaning of the fields other than the description ID has not been
decoded.
