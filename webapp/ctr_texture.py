"""
CTR (3DS) texture decoder -> RGBA (top-left origin).

Ported from SPICA (dq8-tools/_ref/SPICA .../PICA/Converters/
TextureConverter.cs + TextureCompression.cs). Handles the PICA200 texture
formats DQ7's CGFX (.bcmdl) TXOB chunks use: RGBA8/RGB8/RGBA5551/RGB565/
RGBA4/LA8/HiLo8/L8/A8/LA4/L4/A4 (8x8 Morton-swizzled tiles) and ETC1 /
ETC1A4 (4x4 block compression).

Public:
    FMT_NAMES : index -> name (PICATextureFormat order)
    decode(raw, width, height, fmt_id) -> bytes  (len width*height*4, RGBA)
    to_png(raw, width, height, fmt_id) -> bytes  (PNG, needs Pillow)
"""

import struct

FMT_NAMES = ['RGBA8', 'RGB8', 'RGBA5551', 'RGB565', 'RGBA4', 'LA8', 'HiLo8',
             'L8', 'A8', 'LA4', 'L4', 'A4', 'ETC1', 'ETC1A4']
_BPP = [32, 24, 16, 16, 16, 16, 16, 8, 8, 8, 4, 4, 4, 8]

_SWIZZLE = [
    0, 1, 8, 9, 2, 3, 10, 11, 16, 17, 24, 25, 18, 19, 26, 27,
    4, 5, 12, 13, 6, 7, 14, 15, 20, 21, 28, 29, 22, 23, 30, 31,
    32, 33, 40, 41, 34, 35, 42, 43, 48, 49, 56, 57, 50, 51, 58, 59,
    36, 37, 44, 45, 38, 39, 46, 47, 52, 53, 60, 61, 54, 55, 62, 63,
]

_ETC1_LUT = [
    (2, 8, -2, -8), (5, 17, -5, -17), (9, 29, -9, -29), (13, 42, -13, -42),
    (18, 60, -18, -60), (24, 80, -24, -80), (33, 106, -33, -106),
    (47, 183, -47, -183),
]
_XT = (0, 4, 0, 4)
_YT = (0, 0, 4, 4)


def min_bytes(width, height, fmt_id):
    """Size in bytes of the base (mip 0) image for this format."""
    if fmt_id in (12, 13):                        # ETC1 / ETC1A4
        bw = max(1, (width + 3) // 4)
        bh = max(1, (height + 3) // 4)
        return bw * bh * (16 if fmt_id == 13 else 8)
    return width * height * _BPP[fmt_id] // 8


def _sat(v):
    return 0 if v < 0 else 255 if v > 255 else v


def _etc1_tile(block):
    """block = 64-bit int (as read: high 32 = pixel-index bits, low 32 =
    the byte-swapped colour word). Returns list of 16 (r,g,b) tuples in
    row-major 4x4 order."""
    block_low = (block >> 32) & 0xFFFFFFFF     # pixel index / MSB-LSB bits
    block_high = block & 0xFFFFFFFF            # colours + tables + flags
    flip = (block_high & 0x1000000) != 0
    diff = (block_high & 0x2000000) != 0

    def s8(x):
        x &= 0xFF
        return x - 256 if x & 0x80 else x

    if diff:
        b1 = block_high & 0x0000F8
        g1 = (block_high & 0x00F800) >> 8
        r1 = (block_high & 0xF80000) >> 16
        b2 = (s8(b1 >> 3) + (s8((block_high & 0x000007) << 5) >> 5)) & 0xFF
        g2 = (s8(g1 >> 3) + (s8((block_high & 0x000700) >> 3) >> 5)) & 0xFF
        r2 = (s8(r1 >> 3) + (s8((block_high & 0x070000) >> 11) >> 5)) & 0xFF
        b1 |= b1 >> 5; g1 |= g1 >> 5; r1 |= r1 >> 5
        b2 = ((b2 << 3) | (b2 >> 2)) & 0xFF
        g2 = ((g2 << 3) | (g2 >> 2)) & 0xFF
        r2 = ((r2 << 3) | (r2 >> 2)) & 0xFF
    else:
        b1 = block_high & 0x0000F0
        g1 = (block_high & 0x00F000) >> 8
        r1 = (block_high & 0xF00000) >> 16
        b2 = (block_high & 0x00000F) << 4
        g2 = (block_high & 0x000F00) >> 4
        r2 = (block_high & 0x0F0000) >> 12
        b1 |= b1 >> 4; g1 |= g1 >> 4; r1 |= r1 >> 4
        b2 |= b2 >> 4; g2 |= g2 >> 4; r2 |= r2 >> 4

    t1 = (block_high >> 29) & 7
    t2 = (block_high >> 26) & 7
    out = [None] * 16

    def px(r, g, b, x, y, table):
        idx = x * 4 + y
        msb = (block_low << 1) & 0xFFFFFFFFFFFFFFFF
        if idx < 8:
            sel = ((block_low >> (idx + 24)) & 1) + ((msb >> (idx + 8)) & 2)
        else:
            sel = ((block_low >> (idx + 8)) & 1) + ((msb >> (idx - 8)) & 2)
        d = _ETC1_LUT[table][sel]
        return (_sat(r + d), _sat(g + d), _sat(b + d))

    if not flip:
        for y in range(4):
            for x in range(2):
                out[y * 4 + x] = px(r1, g1, b1, x, y, t1)
                out[y * 4 + x + 2] = px(r2, g2, b2, x + 2, y, t2)
    else:
        for y in range(2):
            for x in range(4):
                out[y * 4 + x] = px(r1, g1, b1, x, y, t1)
                out[(y + 2) * 4 + x] = px(r2, g2, b2, x, y + 2, t2)
    return out


def _decode_etc1(raw, width, height, alpha):
    out = bytearray(width * height * 4)
    pos = 0
    for ty in range(0, height, 8):
        for tx in range(0, width, 8):
            for t in range(4):
                ablock = 0xFFFFFFFFFFFFFFFF
                if alpha:
                    ablock = struct.unpack_from('<Q', raw, pos)[0]; pos += 8
                cword = struct.unpack_from('>Q', raw, pos)[0]; pos += 8
                tile = _etc1_tile(cword)
                ti = 0
                for py in range(_YT[t], _YT[t] + 4):
                    for px_ in range(_XT[t], _XT[t] + 4):
                        gx, gy = tx + px_, ty + py
                        if gx >= width or gy >= height:
                            ti += 1
                            continue
                        r, g, b = tile[ti]
                        o = (gy * width + gx) * 4
                        out[o] = r; out[o + 1] = g; out[o + 2] = b
                        ash = ((px_ & 3) * 4 + (py & 3)) << 2
                        a = (ablock >> ash) & 0xF
                        out[o + 3] = (a << 4) | a
                        ti += 1
    return bytes(out)


def _u16(buf, off):
    return buf[off] | (buf[off + 1] << 8)


def decode(raw, width, height, fmt_id):
    """-> bytes of length width*height*4 (RGBA, row 0 = top)."""
    if fmt_id == 12:
        return _decode_etc1(raw, width, height, False)
    if fmt_id == 13:
        return _decode_etc1(raw, width, height, True)

    inc = max(1, _BPP[fmt_id] // 8)
    out = bytearray(width * height * 4)
    io = 0
    for ty in range(0, height, 8):
        for tx in range(0, width, 8):
            for p in range(64):
                sx = _SWIZZLE[p] & 7
                sy = (_SWIZZLE[p] - sx) >> 3
                gx, gy = tx + sx, ty + sy
                if gx >= width or gy >= height:
                    io += inc
                    continue
                o = (gy * width + gx) * 4
                f = fmt_id
                if f == 0:            # RGBA8  (stored little-endian ABGR -> bytes A,B,G,R)
                    out[o] = raw[io + 3]; out[o + 1] = raw[io + 2]
                    out[o + 2] = raw[io + 1]; out[o + 3] = raw[io + 0]
                elif f == 1:          # RGB8  (stored B,G,R)
                    out[o] = raw[io + 2]; out[o + 1] = raw[io + 1]
                    out[o + 2] = raw[io + 0]; out[o + 3] = 255
                elif f == 2:          # RGBA5551  (DQ7: R in high bits, A in bit 0)
                    v = _u16(raw, io)
                    r = (v >> 11) & 0x1F; g = (v >> 6) & 0x1F; b = (v >> 1) & 0x1F
                    out[o] = (r << 3) | (r >> 2); out[o + 1] = (g << 3) | (g >> 2)
                    out[o + 2] = (b << 3) | (b >> 2); out[o + 3] = 255 if (v & 1) else 0
                elif f == 3:          # RGB565  (DQ7: R in high bits - standard GL)
                    v = _u16(raw, io)
                    r = (v >> 11) & 0x1F; g = (v >> 5) & 0x3F; b = v & 0x1F
                    out[o] = (r << 3) | (r >> 2); out[o + 1] = (g << 2) | (g >> 4)
                    out[o + 2] = (b << 3) | (b >> 2); out[o + 3] = 255
                elif f == 4:          # RGBA4  (DQ7: R in high bits, A in low nibble)
                    v = _u16(raw, io)
                    r = (v >> 12) & 0xF; g = (v >> 8) & 0xF; b = (v >> 4) & 0xF
                    a = v & 0xF
                    out[o] = (r << 4) | r; out[o + 1] = (g << 4) | g
                    out[o + 2] = (b << 4) | b; out[o + 3] = (a << 4) | a
                elif f == 5:          # LA8  (stored A,L)
                    l = raw[io + 1]
                    out[o] = out[o + 1] = out[o + 2] = l; out[o + 3] = raw[io]
                elif f == 6:          # HiLo8
                    out[o] = raw[io + 1]; out[o + 1] = raw[io]
                    out[o + 2] = 0; out[o + 3] = 255
                elif f == 7:          # L8
                    l = raw[io]
                    out[o] = out[o + 1] = out[o + 2] = l; out[o + 3] = 255
                elif f == 8:          # A8
                    out[o] = out[o + 1] = out[o + 2] = 255; out[o + 3] = raw[io]
                elif f == 9:          # LA4
                    v = raw[io]
                    l = (v >> 4) | (v & 0xF0); a = (v << 4) | (v & 0x0F)
                    out[o] = out[o + 1] = out[o + 2] = l & 0xFF
                    out[o + 3] = a & 0xFF
                elif f == 10:         # L4
                    nib = (raw[io >> 1] >> ((io & 1) << 2)) & 0xF
                    l = (nib << 4) | nib
                    out[o] = out[o + 1] = out[o + 2] = l; out[o + 3] = 255
                elif f == 11:         # A4
                    nib = (raw[io >> 1] >> ((io & 1) << 2)) & 0xF
                    out[o] = out[o + 1] = out[o + 2] = 255
                    out[o + 3] = (nib << 4) | nib
                io += inc
    return bytes(out)


def to_png(raw, width, height, fmt_id):
    from PIL import Image
    rgba = decode(raw, width, height, fmt_id)
    img = Image.frombytes('RGBA', (width, height), rgba)
    import io as _io
    buf = _io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


# DMP ("DMP\0" / "DMP\3") standalone texture dumps: 0x10 header then 8x8
# Morton-swizzled pixels sized bufW*bufH. Header: [4]magic [4]fmt-ascii
# [u16]W [u16]H [u16]bufW [u16]bufH.  fmt ascii -> our format id:
_DMP_FMT = {
    b'8888': 0, b'888 ': 1, b'888\x00': 1,
    b'5551': 2, b'5650': 3, b'4444': 4,
    b'la88': 5, b'hilo': 6, b'l8  ': 7, b'a8  ': 8,
    b'la44': 9, b'l4  ': 10, b'a4  ': 11,
    b'etc1': 12, b'etca': 13, b'et1a': 13,
}


def dmp_info(data):
    """-> (fmt_id, W, H, bufW, bufH) or None if not a DMP dump."""
    if data[:3] != b'DMP':
        return None
    fmt = data[4:8]
    fid = _DMP_FMT.get(fmt)
    if fid is None:
        fid = _DMP_FMT.get(fmt.lower())
    if fid is None:
        return None
    w, h, bw, bh = struct.unpack_from('<4H', data, 8)
    if not (0 < w <= 4096 and 0 < h <= 4096):
        return None
    if bw < w:
        bw = w
    if bh < h:
        bh = h
    return fid, w, h, bw, bh


def dmp_to_png(data):
    """DMP dump bytes -> PNG bytes (or None)."""
    info = dmp_info(data)
    if not info:
        return None
    fid, w, h, bw, bh = info
    body = data[0x10:]
    need = min_bytes(bw, bh, fid)
    if len(body) < need:
        return None
    from PIL import Image
    rgba = decode(body[:need], bw, bh, fid)
    img = Image.frombytes('RGBA', (bw, bh), rgba)
    if (bw, bh) != (w, h):
        img = img.crop((0, 0, w, h))
    import io as _io
    buf = _io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()
