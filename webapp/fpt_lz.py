"""
Decompressor for DQ7 3DS "type 0x40" compressed files.

These are the `.fpt.lz` blobs under `SCREENTEX/` (job portraits, dungeon
atlases, endroll frames, ...) and a few `LAYOUTTEX/` files. They are NOT
LZ11 (0x11) / LZ10 (0x10); the first byte's high nibble is 0x40.

The format is an LZ77 + dual static-Huffman codec (deflate-ish). This
implementation is a direct port of the game's decompressor at
code.decompressed.bin VA 0x00128b8c (the branch reached when
`(header[0] & 0xF0) == 0x40`, dispatched from VA 0x002be378).

Layout
------
  offset 0 : u8   type   (high nibble 0x40; low nibble seen as 0x9/0x7/0x8..)
  offset 1 : u24  decompressed size, little-endian
             (if that u24 == 0, the next u32 LE is the real size and the
              payload starts 4 bytes later)
  then Huffman table 1  (literal / length tree):
             u16 LE  count
             ((count*4 + 4) - 2) bytes of bitstream, 9-bit big-endian
             symbols, each written to node slot 1,2,3,... (max 1023).
  then Huffman table 2  (distance tree):
             u8   count
             ((count*4 + 4) - 1) bytes of bitstream, 5-bit big-endian
             symbols, node slots 1..63.
  then the body: MSB-first bitstream.

Node halfword (tree 1): bits0..6 = child base index, bit7 = "bit=1 child is
a leaf", bit8 = "bit=0 child is a leaf". Walking: read 1 bit b; child slot
= (node & ~1) ... see code. Leaf value < 0x100 => literal byte; value
>= 0x100 => match, length = (value & 0xFF) + 3  (3..258, no extra bits).
Tree 2 is the same with 3-bit child field and flag bits 3/4; its leaf
value S encodes the distance: S==0 -> dist 1, else n = S-1 extra bits and
dist = (1 << n) + <n bits> + 1. Match copy source is (outpos - dist),
overlapping-safe, one byte at a time.
"""

_MASK9 = 0x1FF
_MASK5 = 0x1F


class _BitReaderMSB:
    """MSB-first bit reader over a byte slice, refilled one byte at a time."""
    __slots__ = ("_d", "_i", "_end", "_buf", "_n")

    def __init__(self, data, start, end):
        self._d = data
        self._i = start
        self._end = end
        self._buf = 0
        self._n = 0

    def read(self, k):
        while self._n < k:
            if self._i >= self._end:
                if self._n == 0:
                    return None
                # not enough bits left for a full symbol -> stop
                return None
            self._buf = (self._buf << 8) | self._d[self._i]
            self._i += 1
            self._n += 8
        self._n -= k
        return (self._buf >> self._n) & ((1 << k) - 1)


def _build_tree(data, start, region_len, sym_bits, max_nodes):
    """Read `sym_bits`-wide symbols MSB-first, fill node slots 1.., return list."""
    # region includes the count field (2 bytes for tree1, 1 for tree2); the
    # game starts reading right after it.
    hdr = 2 if sym_bits == 9 else 1
    br = _BitReaderMSB(data, start + hdr, start + region_len)
    nodes = [0] * max_nodes
    idx = 1
    while idx < max_nodes:
        v = br.read(sym_bits)
        if v is None:
            break
        nodes[idx] = v
        idx += 1
    return nodes


def decompress_fpt_lz(data: bytes) -> bytes:
    if not data or (data[0] & 0xF0) != 0x40:
        raise ValueError("not a type-0x40 (.fpt.lz) blob: first byte %r"
                         % (data[:1],))

    out_size = data[1] | (data[2] << 8) | (data[3] << 16)
    p = 4
    if out_size == 0:
        out_size = int.from_bytes(data[4:8], "little")
        p = 8

    # ---- table 1 (literal/length) ----
    t1_count = data[p] | (data[p + 1] << 8)
    t1_len = t1_count * 4 + 4
    tree1 = _build_tree(data, p, t1_len, 9, 1024)
    p += t1_len

    # ---- table 2 (distance) ----
    t2_count = data[p]
    t2_len = t2_count * 4 + 4
    tree2 = _build_tree(data, p, t2_len, 5, 64)
    p += t2_len

    # ---- body ----
    body = data
    bi = p            # byte index into body
    bbuf = 0          # current byte
    bbits = 0         # bits left in bbuf

    out = bytearray(out_size)
    op = 0

    def next_bit():
        nonlocal bbuf, bbits, bi
        if bbits == 0:
            bbuf = body[bi]
            bi += 1
            bbits = 8
        bbits -= 1
        return (bbuf >> bbits) & 1

    while op < out_size:
        # walk tree 1
        node_slot = 1
        while True:
            node = tree1[node_slot]
            b = next_bit()
            child = (b + ((node & 0x7F) << 1) + 2) << 1   # halfword offset
            base = node_slot & ~1                         # word-align (in halfwords)
            leaf = (node & (0x100 >> b)) != 0
            target = base + (child >> 1)
            if not leaf:
                node_slot = target
                continue
            val = tree1[target]
            break

        if val < 0x100:
            out[op] = val
            op += 1
            continue

        length = (val & 0xFF) + 3

        # walk tree 2
        node_slot = 1
        while True:
            node = tree2[node_slot]
            b = next_bit()
            child = (b + ((node & 0x7) << 1) + 2) << 1
            base = node_slot & ~1
            leaf = (node & (0x10 >> b)) != 0
            target = base + (child >> 1)
            if not leaf:
                node_slot = target
                continue
            s = tree2[target]
            break

        if s == 0:
            dist = 1
        else:
            n = s - 1
            acc = 1
            for _ in range(n):
                acc = ((acc << 1) & 0xFFFF) | next_bit()
            dist = acc + 1

        if op + length > out_size:
            length = out_size - op
        src = op - dist
        for _ in range(length):
            out[op] = out[src]
            op += 1
            src += 1

    return bytes(out)
