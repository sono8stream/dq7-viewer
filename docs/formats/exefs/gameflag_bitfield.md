# `GameFlag` bitfield structure

The `GameFlag` class holds the bit arrays used for flags, referenced from
the script side's `IF_FLAG` (opcode `0x00000003`) / `SET_FLAG` (opcode
`0x00010004`).

## Three independent bit arrays selected by the `type` argument

The first argument `type` of `GameFlag::check(this, type, flag_id)` /
`GameFlag::set(this, type, flag_id, value)` selects one of three
independent bit arrays within the same `this` instance. `param0` of the
script argument `[param0, flag_id, value]` for `IF_FLAG`/`SET_FLAG` is this
`type` itself.

| type | Bit array offset (relative to `this`) | On-disk (save file) equivalent |
|---|---|---|
| 0 | `this+0x218` | `0x20 + flag_id//8` (file offset from the start of the `GameFlag` block) |
| 1 | `this+0x418` | `0x220 + flag_id//8` (a separate byte range, offset by 0x200 bytes from type 0's) |
| 2 | `this+0x008` | Not saved at all (see below) |

Bit-position formula (common to all 3 types): `bit = flag_id & 0x1f`,
`word = flag_id >> 5` (treated in memory as a bit array in 32-bit word
units).

`GameFlag::set` accepts the special value `type==3`, which performs "write
to both type 0 and type 1 simultaneously." `GameFlag::check`, on the other
hand, has no branch for `type==3`; passing `type=3` to `check` always
returns false.

## type=2 is a session-only temporary flag

`GameFlag::serialize` (file offset `0x243c0c`) copies the range from
`this+0x208` to `0x250` (592 bytes) directly into the save data. This
range is `this+0x208` through `this+0x458`; both the type-0 bucket
(`+0x218`) and the type-1 bucket (`+0x418`) fall within this range and are
persisted, but the type-2 bucket (`+0x008`) lies before this range and is
therefore never included in the save file.

`GameFlag::initialize` (file offset `0x243b38`) zero-clears the bit arrays
at startup via `GameFlag::clear(this, 3)`, then memsets `this+0x208`
through `+0x458` again. As a result, **type-2 flags are always reset to 0
on every startup — they are a session-only temporary flag.**

## On the scope of the flag_id space

- Large flag_id values (in the thousands) for type 0 are, in many cases,
  independently `SET_FLAG`'d by only a single corresponding SCRIPT file,
  and appear to be operated as globally unique story-progression flags.
- Small flag_id values (1-2 digits) for type 1 are independently used by
  many (several dozen to 100+) different SCRIPT files. For this reason,
  type-1 flag_ids likely do not carry a globally unique meaning, and are
  more likely map-local temporary variables used only within each map's
  own script scope (the same ID across different maps does not necessarily
  mean the same thing).

## Related classes/functions (file offset, relative to `code.decompressed.bin`)

- `GameFlag::check` : `0x18f998`
- `GameFlag::set` : `0x18b00c`
- `GameFlag::serialize` : `0x243c0c`
- `GameFlag::initialize` : `0x243b38`
