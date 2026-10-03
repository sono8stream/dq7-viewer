# Character Visual Asset Layout Rules

DQ7's (3DS) character-related visuals are split into separate directories
by type.

| Kind | Location | Format |
| --- | --- | --- |
| 3D model body | `CHARACTER/pXXXX_jNN.bcmdl.lz` | LZ11-compressed CGFX |
| Model texture | Embedded inside the above `.bcmdl.lz`'s CGFX (in TXOB chunks) | TXOB inside CGFX (ETC1/RGBA, etc.) |
| Animation | `CHARACTER/pXXXX_jNN.pack.lz` | LZ11-compressed PackData (contains CGFX/CANM) |
| Menu face graphic | `TEXTURE/pXXXX_jNN_face.bctex.lz` | LZ11-compressed BCTEX (standalone) |
| Job-change preview portrait | `SCREENTEX/job/p%04d_j%02d.fpt.lz` | type-0x40 compressed FPT0 container |
| Battle motion data | `LEVELDATA/dq7_btl_motion_job_*.dat` | Custom (see below for file name meaning) |
| Character → model name mapping | `LEVELDATA/dq7_chara_list.dat` | 84 bytes/record, ASCII string `pXXXX` near the start |
| Job definitions | `LEVELDATA/dq7_player_job.dat` | Custom (header: count=55, recsize=188) |

- `pXXXX` is the model asset number corresponding to the record order in
  `dq7_chara_list.dat`. The 6 main-story playable characters use small
  numbers `p0001`–`p0006`, but this is simply the catalog order of model
  assets — `p0007` onward is a mix of NPCs/monsters/etc. (the mapping
  "model number = character ID" is a coincidence that only holds for the
  first 6 entries).
- `jNN` is the job number. Permanent party members have the full set for
  21 slots, `j00`–`j20`, across `CHARACTER/*.bcmdl.lz` / `*.pack.lz` /
  `TEXTURE/*_face.bctex.lz`.
- The `job` in the file name `dq7_btl_motion_job_*.dat` is merely an
  internal development label — the content is actually battle motion data
  **per monster** (the monster's name itself is used in the file name).
  Where playable characters' per-job battle motion is stored is a separate
  system (likely included directly inside each job's `.pack.lz` animation
  pack).

## Animation clip name encoding inside `.pack.lz`

Animation clip names inside `CHARACTER/pXXXX_jNN.pack.lz` (a CGFX animation
pack) are encoded as strings that include the character number and job
number, like `pXXXX_jNN_idle`. Due to the back-reference structure of
LZ11-compressed data, when the same prefix string is shared across
multiple clip names, that prefix may be encoded as a single literal region
referenced by back-references collectively (in this case, rewriting just
that one spot changes every occurrence at once. However, there are also
cases where other, unrelated strings happen to share the same byte
sequence and back-reference it, so before rewriting you need to trace the
back-references to confirm which literal region is actually referenced by
which occurrence).

## `SCREENTEX/job/*.fpt.lz` (job-change preview portraits)

A file referenced by the job selection screen. `.fpt.lz` is not LZ11 — it's
a type-0x40 format (LZ77 + dual Huffman compression) whose leading byte's
upper nibble is `0x40`. Once decompressed, it becomes an `FPT0` container
(16 tiles of 64×64 `texNNN.dmp` + `size.dat` → reassembled into 256×256).

## `dq7_picture_character.dat` (272 bytes)

Appears to have a record-like structure of the form
`[charId][?][?][ff] [u16 x][u16 y]...` (purpose and the meaning of all
fields are unconfirmed).
