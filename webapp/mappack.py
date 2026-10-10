"""Map model packs (RomFS MAP/MAPDATA/*.pack.lz, MAP/*.pack.lz).

Every map pack is an LZ11-compressed tree of one generic chunk container
(see docs/formats/models/map_pack.md):

    +0x00 char[16] magic ('MODEL', 'FldData', 'FILE', 'COLL', 'PARM', 'WNOD')
    +0x10 u32 count
    +0x14 u32 dataBase      entry offsets are relative to the container start + dataBase
    +0x18 u32 tableSize     dataBase - 0x20
    +0x20 {u32 offset, u32 size} * count

Top level 'MODEL' (6 entries, always in this order):
    0 WNOD  placement nodes (GNOD records)
    1 MODEL one FldData per part
    2 FILE  part name tables (NRML / CMMN / LODM)
    3 COLL  collision (PLGN/GRDS/NULL/TINF/ROOT/CELL, not decoded here)
    4 PARM  BACK (clear color) / CAMR / FOG
    5 CGFX  shared Textures dict used by every part's material

FldData (3 entries): 0 = part CGFX (Models, materials reference textures of
the shared CGFX by name), 1 = CGFX with SkeletalAnims (may be empty),
2 = CGFX with MaterialAnims (may be absent).

GNOD (one per WNOD entry):
    +0x00 'GNOD'  +0x04 u32 type (0=root, 1=part instance)  +0x08 u32 version
    +0x0c i32 part index (FldData index in the inner MODEL; -1 for root)
    +0x10 char[N] name (= the part CGFX's model name)
    then vec4 translation, vec4 rotation (radians, XYZ), vec4 scale,
    vec4 bbox min, vec4 bbox max (part-local), extra params (not decoded).
    version 0x00010500 (every MAP/MAPDATA pack): N = 32, record 0xb0
    version 0x00010400 (MAP/z01n2f7.pack.lz only): N = 16, record 0xa0
Part geometry is in part-local space: the node's bbox equals the part's
vertex extent, so world = T * R * S * local.
"""

import collections
import os
import struct

from lz11_decompress import decompress_lz11
import bcmdl


def _magic(buf, off, n=16):
    return buf[off:off + n].split(b'\0', 1)[0].decode('ascii', 'replace')


def read_container(buf, off):
    """-> (magic, [(abs_offset, size), ...]) for the generic chunk container at `off`."""
    count, base = struct.unpack_from('<II', buf, off + 0x10)
    if count > 0x10000:
        raise ValueError(f'bad container count {count} at {off:#x}')
    entries = []
    for i in range(count):
        o, s = struct.unpack_from('<II', buf, off + 0x20 + i * 8)
        entries.append((off + base + o, s))
    return _magic(buf, off), entries


# GNOD +0x08 version -> length of the name field (see module docstring)
_GNOD_NAME_LEN = {0x00010500: 32, 0x00010400: 16}


def _vec(buf, off, n=3):
    return [round(v, 5) for v in struct.unpack_from(f'<{n}f', buf, off)]


class MapPack:
    def __init__(self, data: bytes):
        if data[:5] != b'MODEL':
            raise ValueError(f'not a map pack (magic {data[:8]!r})')
        self.d = data
        _, top = read_container(data, 0)
        self.chunks = {}
        for off, size in top:
            # 4-char tags except the nested 'MODEL' (CGFX's magic is followed
            # by its BOM, not NUL, so a 16-byte read would not terminate)
            m = 'MODEL' if data[off:off + 5] == b'MODEL' else _magic(data, off, 4)
            if size and m not in self.chunks:
                self.chunks[m] = (off, size)
        self._tex_cg = None
        self._part_offsets = None

    # ---- shared textures -----------------------------------------------------
    def texture_cgfx(self):
        if self._tex_cg is None and 'CGFX' in self.chunks:
            off, size = self.chunks['CGFX']
            self._tex_cg = bcmdl.Cgfx(self.d[off:off + size])
        return self._tex_cg

    def texture_names(self):
        cg = self.texture_cgfx()
        return [t['name'] for t in cg.textures()] if cg else []

    # ---- parts ---------------------------------------------------------------
    def part_offsets(self):
        """[(fldd_off, fldd_size), ...] indexed by GNOD part index."""
        if self._part_offsets is None:
            self._part_offsets = []
            if 'MODEL' in self.chunks:
                _, self._part_offsets = read_container(self.d, self.chunks['MODEL'][0])
        return self._part_offsets

    def part_cgfx(self, idx):
        off, size = self.part_offsets()[idx]
        if not size or self.d[off:off + 7] != b'FldData':
            return None
        _, sub = read_container(self.d, off)
        if not sub or not sub[0][1]:
            return None
        co, cs = sub[0]
        if self.d[co:co + 4] != b'CGFX':
            return None
        return bcmdl.Cgfx(self.d[co:co + cs])

    def part_info(self, idx):
        """{index, name, hasSkeletalAnims, hasMaterialAnims} without decoding geometry."""
        off, size = self.part_offsets()[idx]
        info = {'index': idx, 'name': None, 'hasSkeletalAnims': False, 'hasMaterialAnims': False}
        if not size or self.d[off:off + 7] != b'FldData':
            return info
        _, sub = read_container(self.d, off)
        for k, (co, cs) in enumerate(sub):
            if not cs or self.d[co:co + 4] != b'CGFX':
                continue
            dicts = bcmdl.Cgfx(self.d[co:co + cs]).structure()['dicts']
            if k == 0:
                models = dicts.get('Models') or []
                info['name'] = models[0] if models else None
            if dicts.get('SkeletalAnims'):
                info['hasSkeletalAnims'] = True
            if dicts.get('MaterialAnims'):
                info['hasMaterialAnims'] = True
        return info

    def part_geometry(self, idx):
        """Part geometry with materials resolved. Textures normally live in
        the shared CGFX (referenced by name); a part may also carry its own
        Textures dict (seen only in MAP/z01n2f7.pack.lz), which
        `bcmdl._materials()` already includes, so those resolve too."""
        cg = self.part_cgfx(idx)
        if cg is None:
            return None
        geo = cg.geometry()
        own = {t['name'] for t in cg.textures()}
        bcmdl.attach_shape_materials(cg, geo, self.texture_names(),
                                     cg if own else self.texture_cgfx())
        return geo

    def texture_png(self, name):
        """PNG of a texture by name: the shared CGFX first, then any part
        CGFX that carries its own Textures dict."""
        cg = self.texture_cgfx()
        if cg and name in {t['name'] for t in cg.textures()}:
            return cg.texture_png(name)
        for idx in range(len(self.part_offsets())):
            pc = self.part_cgfx(idx)
            if pc and name in {t['name'] for t in pc.textures()}:
                return pc.texture_png(name)
        return None

    # ---- placement -----------------------------------------------------------
    def nodes(self):
        if 'WNOD' not in self.chunks:
            return []
        _, ents = read_container(self.d, self.chunks['WNOD'][0])
        out = []
        for off, size in ents:
            if size < 0x80 or self.d[off:off + 4] != b'GNOD':
                continue
            ntype, version, part = struct.unpack_from('<IIi', self.d, off + 4)
            name_len = _GNOD_NAME_LEN.get(version, 32)
            v = off + 0x10 + name_len
            out.append({
                'type': ntype,
                'version': version,
                'part': part,
                'name': _magic(self.d, off + 0x10, name_len),
                'translation': _vec(self.d, v),
                'rotation': _vec(self.d, v + 0x10),
                'scale': _vec(self.d, v + 0x20),
                'bboxMin': _vec(self.d, v + 0x30),
                'bboxMax': _vec(self.d, v + 0x40),
            })
        return out

    # ---- FILE name tables ----------------------------------------------------
    def file_tables(self):
        """{'NRML': {count, size, names}, 'CMMN': {count, size, names: []}, 'LODM': ...}.
        Each section: +0x00 tag, +0x08 u32 count. NRML records are 0x30 bytes
        from +0x10 with the name at +0x00; NRML[i] is FldData i, and GNOD
        nodes only ever reference these (part index < NRML count, node name
        == NRML name, checked on c01nout/h01nout1/wld_n25a). CMMN lists the
        animated common objects (doors etc., e.g. 'a_wdoor02_1') whose
        FldData follow the NRML ones; they are not placed by WNOD and their
        record layout is not decoded here."""
        out = {}
        if 'FILE' not in self.chunks:
            return out
        _, ents = read_container(self.d, self.chunks['FILE'][0])
        for off, size in ents:
            m = _magic(self.d, off, 4)
            cnt, = struct.unpack_from('<I', self.d, off + 8)
            names = []
            if m == 'NRML':
                for i in range(cnt):
                    names.append(_magic(self.d, off + 0x10 + i * 0x30, 32))
            out[m] = {'count': cnt, 'size': size, 'names': names}
        return out

    # ---- PARM ------------------------------------------------------------------
    def params(self):
        out = {}
        if 'PARM' not in self.chunks:
            return out
        _, ents = read_container(self.d, self.chunks['PARM'][0])
        for off, size in ents:
            m = _magic(self.d, off, 4).strip()
            if not size:
                continue
            if m == 'BACK':
                out['background'] = _vec(self.d, off + 0x10, 4)
            elif m == 'CAMR':
                out['camera'] = _vec(self.d, off + 0x10, 4)
            else:
                out[m] = self.d[off + 0x10:off + size].hex()
        return out

    # ---- COLL / PLGN ------------------------------------------------------------
    def collision(self):
        """COLL's PLGN section -> {count, bboxMin, bboxMax, positions, attrs}.
        PLGN: +0x10 u32 count, records from +0x20, 0x80 bytes each:
            +0x00 u32 1 = quad, 0 = triangle (4th vertex zero-filled)
            +0x04 u32[3] attributes (not decoded; kept raw)
            +0x10 vec4[4] vertices (w = 0)  +0x50 vec4 normal
            +0x60 vec4 bbox min  +0x70 vec4 bbox max (w = 1)
        (bbox == min/max of the 3 or 4 vertices for all 9970 records of 60
        random packs.) `positions` is a triangle soup (quads split 0-1-2 /
        0-2-3, the vertices are stored in perimeter order); `attrs[i]` is
        record i's raw +0x00..+0x0c words; `triPoly[k]` = source record index
        of triangle k."""
        if 'COLL' not in self.chunks:
            return None
        _, ents = read_container(self.d, self.chunks['COLL'][0])
        pl = next(((o, s) for o, s in ents if self.d[o:o + 4] == b'PLGN'), None)
        if not pl:
            return None
        o, size = pl
        n, = struct.unpack_from('<I', self.d, o + 0x10)
        n = min(n, max(0, (size - 0x20) // 0x80))
        pos, tri_poly, attrs = [], [], []
        lo = [float('inf')] * 3
        hi = [float('-inf')] * 3
        for i in range(n):
            r = o + 0x20 + i * 0x80
            quad, a1, a2, a3 = struct.unpack_from('<4I', self.d, r)
            v = [struct.unpack_from('<3f', self.d, r + 0x10 + k * 16) for k in range(4 if quad == 1 else 3)]
            attrs.append([quad, a1, a2, a3])
            tris = [(0, 1, 2), (0, 2, 3)] if len(v) == 4 else [(0, 1, 2)]
            for t in tris:
                for k in t:
                    pos.extend(round(c, 4) for c in v[k])
                tri_poly.append(i)
            for j in range(3):
                lo[j] = min(lo[j], struct.unpack_from('<f', self.d, r + 0x60 + j * 4)[0])
                hi[j] = max(hi[j], struct.unpack_from('<f', self.d, r + 0x70 + j * 4)[0])
        if not n:
            return {'count': 0}
        return {'count': n, 'bboxMin': _round_list(lo), 'bboxMax': _round_list(hi),
                'positions': pos, 'triPoly': tri_poly, 'attrs': attrs}

    def chunk_summary(self):
        out = []
        for m, (off, size) in self.chunks.items():
            item = {'magic': m, 'offset': off, 'size': size}
            if m in ('COLL', 'FILE', 'PARM', 'WNOD', 'MODEL'):
                _, ents = read_container(self.d, off)
                item['entries'] = len(ents)
                if m in ('COLL', 'FILE', 'PARM'):
                    item['sections'] = [{'magic': _magic(self.d, o, 4), 'size': s} for o, s in ents]
            out.append(item)
        return out


_CACHE = collections.OrderedDict()   # (path, mtime_ns, size) -> MapPack
_CACHE_MAX = 3


def load(path):
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    mp = _CACHE.get(key)
    if mp is None:
        with open(path, 'rb') as f:
            raw = f.read()
        if raw[:1] == b'\x11':
            raw = decompress_lz11(raw)
        mp = MapPack(raw)
        _CACHE[key] = mp
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return mp


def _round_list(xs, nd=4):
    return [round(v, nd) for v in xs] if xs else xs


def read_map(path):
    """path -> {nodes, parts, textures, params, chunks, fileTables, missingTextures}.
    Each referenced part's geometry is sent once; nodes instance it."""
    mp = load(path)
    nodes = mp.nodes()
    used = sorted({n['part'] for n in nodes if n['type'] == 1 and n['part'] >= 0})
    tex_names = set(mp.texture_names())
    parts = []
    missing = set()
    n_parts = len(mp.part_offsets())
    for idx in used:
        if idx >= n_parts:
            continue
        pc = mp.part_cgfx(idx)
        own_tex = {t['name'] for t in pc.textures()} if pc else set()
        geo = mp.part_geometry(idx)
        info = mp.part_info(idx)
        shapes = []
        for sh in (geo or {}).get('shapes', []):
            if not sh.get('ok'):
                continue
            for k in ('positions', 'normals', 'uvs', 'uvs1', 'uvs2', 'colors'):
                if k in sh:
                    sh[k] = _round_list(sh[k])
            for tn in sh.get('textures') or []:
                if tn not in tex_names and tn not in own_tex:
                    missing.add(tn)
            shapes.append(sh)
        info['shapes'] = shapes
        parts.append(info)
    return {
        'nodes': nodes,
        'parts': parts,
        'partCount': n_parts,
        'textures': sorted(tex_names),
        'missingTextures': sorted(missing),
        'params': mp.params(),
        'chunks': mp.chunk_summary(),
        'fileTables': mp.file_tables(),
        'collision': mp.collision(),
    }


def texture_png(path, name):
    return load(path).texture_png(name)
