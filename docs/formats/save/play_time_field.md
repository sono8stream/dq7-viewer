# Play Time Field

At save file offset `0x3250` there is a u32 (4 bytes, little-endian) field
representing play time.

## Format

- The unit is a frame count at 30fps.
- Conversion formula: `hours = raw / 30 / 3600`, `minutes = raw / 30 / 60 % 60`.
- The upper bound is `0x66FEBF8` (107,998,200 frames ≈ 999.98 hours), and it
  is clamped to this value inside `GameStatus::addPlayTime` (the ARM-code
  side, single-increment routine). The lower bound is 0.

## Runtime-side correspondence

At runtime, the `+0x18` field of the `GameStatus` object holds this counter.
The details of how `GameStatus::serialize`/`deserialize` map this value to
`0x3250` in the save (ordering relative to other fields, the meaning of the
`+0x10` shift by device type) are unconfirmed; only verification via actual
data comparison has been done.

## Verification method

This offset was confirmed to be the play-time field by reading `0x3250` as
a u32 across multiple save files, converting it to hours:minutes at 30fps,
and checking that the converted value matches each save's actual play time.
