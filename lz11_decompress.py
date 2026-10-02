"""
LZ11 decompressor for RomFS `*.pack.lz` files (e.g. `MAP/MAPDATA/*.pack.lz`).

Discovered 2026-08-30 while investigating why a script-object added via
the webapp's "オブジェクトを追加(コピー)" feature didn't show up in-game
(see docs/script_object_insertion.md's "実機検証の結果" section): the
map's own same-named pack file (`m01nk1f1.pack.lz`) was checked as a
candidate "NPC placement/count table", so it had to be decompressed
first. Its header starts with byte 0x11, the standard Nintendo "LZ11"
compression type used across many DS/3DS titles (distinct from the BLZ
"backward LZ77" format `exefs_extract.py` implements for ExeFS .code -
that one is NOT interchangeable with this one).

Format:
  byte0 = 0x11 (compression type)
  bytes1..3 = decompressed size, 24-bit little-endian
  if that 24-bit size == 0: next 4 bytes are the real size, 32-bit LE
  then a stream of blocks: 1 flag byte (MSB-first, 1 bit per token),
  followed by up to 8 tokens per flag byte - each token is either a
  literal byte (flag bit 0) or a back-reference (flag bit 1) encoded in
  2/3/4 bytes depending on its top nibble (this is what distinguishes
  LZ11 from the simpler fixed-3-byte-token LZ10/LZSS variant).

Verified empirically: decompressing `MAP/MAPDATA/m01nk1f1.pack.lz`
(324,692 compressed bytes) produces exactly 972,800 bytes (matching the
header's declared size) starting with a well-formed CGFX container
('MODEL'/'CGFX'/'GNOD'/'SOBJ'/'MTOB'/... chunk tags, standard 3DS model
format) - i.e. this pack format is a 3D model/scene asset bundle, NOT a
gameplay data table (see docs/script_object_insertion.md for why this
matters to the NPC-placement investigation).

Usage:
  python3 lz11_decompress.py <in.pack.lz> [out.bin]
"""

import struct
import sys


def decompress_lz11(data: bytes) -> bytes:
    if not data or data[0] != 0x11:
        raise ValueError(f'not LZ11 data (expected magic 0x11, got {data[0]:#x} if any)')
    size = data[1] | (data[2] << 8) | (data[3] << 16)
    pos = 4
    if size == 0:
        size = struct.unpack_from('<I', data, 4)[0]
        pos = 8

    out = bytearray()
    n = len(data)
    while len(out) < size and pos < n:
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b0 = data[pos]
                top = b0 >> 4
                if top == 0:
                    length = ((b0 & 0xF) << 4 | (data[pos + 1] >> 4)) + 0x11
                    disp = ((data[pos + 1] & 0xF) << 8 | data[pos + 2]) + 1
                    pos += 3
                elif top == 1:
                    length = ((b0 & 0xF) << 12 | (data[pos + 1] << 4) | (data[pos + 2] >> 4)) + 0x111
                    disp = ((data[pos + 2] & 0xF) << 8 | data[pos + 3]) + 1
                    pos += 4
                else:
                    length = top + 1
                    disp = ((b0 & 0xF) << 8 | data[pos + 1]) + 1
                    pos += 2
                for _ in range(length):
                    out.append(out[-disp])
            else:
                out.append(data[pos])
                pos += 1
    return bytes(out)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], 'rb') as f:
        data = f.read()
    out = decompress_lz11(data)
    print(f'compressed={len(data)} decompressed={len(out)}')
    print(out[:64])
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'wb') as f:
            f.write(out)
        print(f'wrote {sys.argv[2]}')


if __name__ == '__main__':
    main()
