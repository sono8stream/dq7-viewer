# Image Container Formats

## Supported image container list

| Kind | Format | Location |
| --- | --- | --- |
| `*.bctex(.lz)` | CGFX (TXOB in the Textures dict; a single file can hold multiple images) | `TEXTURE/` (faces), `RISEUP/`, `CASINO/` |
| `*.bcmdl(.lz)` | TXOB embedded in a CGFX model | `CHARACTER/` `MONSTER/` `BATTLE/` `WEAPON/` `GOODS/`, etc. |
| `*.dmp` | `DMP\0`/`DMP\3` + 4-char format + WxH + bufWxH, followed by 8x8-swizzled pixels | `LAYOUTTEX/` (icons), `WORLDATLAS/` (world map tiles), `MENUTEX/` |
| `LAYOUTTEX/*.fpt` | FPT0 archive. Decode each contained `texNNN.dmp` individually | `LAYOUTTEX/texture.fpt` `system.fpt` |

- `TEXTURE/pXXXX_jNN_face.bctex.lz` is not a single "face" image — it's an
  atlas of a dozen or so expression parts such as eyes and mouth.
- DMP pixels use the same 8x8 Morton swizzle as TXOB. Read using
  `bufW/bufH` (power-of-2 padded) and crop to `WxH`.

## DMP header

```
off 0: magic "DMP\0" or "DMP\3"
off 4: format identifier (4 chars)
off 8: W (u16?), H
off ?: bufW, bufH (actual buffer size, padded to a power of 2)
```
(See the implementation `webapp/ctr_texture.py` for exact field sizes.)

## RGBA8 channel order

On the 3DS, RGBA8 is little-endian ABGR in memory, i.e. the byte sequence
`[A, B, G, R]`. The correct decoding is:

```
out.R = raw[io+3]; out.G = raw[io+2]; out.B = raw[io+1]; out.A = raw[io+0]
```

The RGB8 branch uses the same byte order (`R = raw[io+2]` is the high
byte).

## `.fpt.lz` (type-0x40 compression) format

The `.lz` extension doesn't necessarily mean LZ11/LZ10. The decompressor
branches on the upper nibble of the leading byte (observed values:
0x10/0x20/0x30/0x40/0x50/0x80). `.fpt.lz` files under `SCREENTEX/` are
type-0x40 (LZ77 + dual static Huffman, deflate-like).

### Header

```
off 0 : u8   type       upper nibble 0x40 (lower nibble is part of the actual data)
off 1 : u24  decompressed size (LE). if 0, the following u32 is the true size and the payload starts at +4
--- Huffman table 1 (literal/length tree) ---
        u16 LE  count
        (count*4 + 4 - 2) bytes of 9-bit big-endian symbol sequence
        stored into node slots 1, 2, 3, … (max 1023)
--- Huffman table 2 (distance tree) ---
        u8   count
        (count*4 + 4 - 1) bytes of 5-bit BE symbol sequence. slots 1..63
--- Body ---
        MSB-first bitstream
```

### Decoding the Huffman trees

Tree 1 (halfword): bits 0..6 = child base index, bit 7 = "the bit=1 child
is a leaf," bit 8 = "the bit=0 child is a leaf." Read 1 bit `b`:
`child = (base & ~1) + b + 2*(node&0x7F) + 2`.
A leaf value `< 0x100` → literal byte. `>= 0x100` → a match, with length =
`(leaf & 0xFF) + 3` (3..258, no extra length bits).

Tree 2 has the same shape (3-bit child field, flag bits 3/4). A leaf value
`S` represents a distance: `S==0` → distance 1, otherwise read `n = S-1`
extra bits: `distance = (1<<n) + <n bits> + 1`. The match's copy source is
`output position - distance` (overlapping copy allowed, copied 1 byte at a
time).

Implementation: `decompress_fpt_lz(bytes) -> bytes` in `webapp/fpt_lz.py`.

### Contents after decompression: FPT0 container

After decompression, you get an `FPT0` (same magic and same entry table
structure as the MESS text FPT0). For `SCREENTEX/job`:

```
header: file_count, temp_count
entries (0x20 byte spacing, name[0x10] + [u32 hash][u32 offset][u32 size][u32 0]):
  tex000.dmp .. texNN.dmp   each 0x4010 bytes = "DMP\3" + 64x64 RGBA8888
  size.dat                   "W,H\r\n" (width/height in px of the original image)
data_start = 0x10 + file_count*0x20 + temp_count*0x40
```

The original W×H image recorded in `size.dat` is split into 64×64 tiles in
a 4×4 grid (for the `SCREENTEX/job` example). The `texNNN` tiles are laid
out in row-major order from the top-left. Other directories use the same
"`texNNN.dmp` grid + `size.dat`" structure.

## Implementation notes

If "duplicating an asset still crashes the screen," the type of asset
duplicated (model/face texture/job-change preview image, etc.) may be
wrong. The actual file path that the screen tries to open can be
identified by checking format strings in the ARM code (near where it
builds a file path `sprintf`-style).
