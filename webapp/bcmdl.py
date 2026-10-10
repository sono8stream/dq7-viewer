"""
DQ7 3D model reader: LZ11-decompress + CGFX (BCRES/.bcmdl) parse -> geometry.

DQ7 (3DS) ships models as `*.bcmdl.lz` (CHARACTER/, MONSTER/) and
`*.shp.lz` (SHAPE/), which are LZ11-compressed CGFX containers - the
standard NintendoWare-for-CTR binary model format (magic 'CGFX', then a
'DATA' section holding Patricia dictionaries of Models/Textures/Materials/
... , each model a 'CMDL' with 'SOBJ' shapes/meshes, 'MTOB' materials,
'TXOB' textures). See docs/bcmdl_model_viewer.md.

This is a FIRST-PASS parser aimed at the web model viewer: it always
returns a structural inventory (`structure()`), and makes a best effort
at pulling renderable geometry (`geometry()` -> per-shape float32
positions / normals / uv0 + index buffer). Not every shape parses yet -
`geometry()['shapes'][i]['ok']` says which did, and `errors` collects why
the rest didn't. Materials/skeleton/skinning/textures are not decoded yet.

Layout facts used here (standard CGFX, little-endian, all "offset" fields
are self-relative: the value is added to the address of the field that
holds it; 0 means null):

  CGFX header : 'CGFX' u16 bom, u16 headerLen(0x14), u32 revision,
                u32 nBlocks
  DATA @ 0x14 : 'DATA' u32 len, then 15 (u32 count, i32 selfRelPtr) pairs
                -> Models, Textures, LUTS, Materials, Shaders, Cameras,
                   Lights, Fogs, Scenes, SkeletalAnims, MaterialAnims,
                   VisAnims, CameraAnims, LightAnims, Emitters
  DICT       : 'DICT' u32 byteLen, u32 count, then (count+1) nodes of
                {u32 refBit, u16 idxLeft, u16 idxRight, i32 nameSelfRel,
                 i32 dataSelfRel}; node[0] is the tree root (skip it).
  GfxObject  : every dict-referenced object starts with u32 flags then a
                4CC magic ('CMDL','SOBJ','MTOB','TXOB',...) at +4.
"""

import collections
import math
import os
import struct

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))

import sys
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from lz11_decompress import decompress_lz11  # noqa: E402
import ctr_texture  # noqa: E402

_FMT_NAMES = ctr_texture.FMT_NAMES
_tex_min_bytes = ctr_texture.min_bytes


_DATA_DICTS = [
    'Models', 'Textures', 'LUTS', 'Materials', 'Shaders', 'Cameras',
    'Lights', 'Fogs', 'Scenes', 'SkeletalAnims', 'MaterialAnims',
    'VisAnims', 'CameraAnims', 'LightAnims', 'Emitters',
]

# PICA200 attribute component formats
_ATTR_FMT = {0: ('b', 1), 1: ('B', 1), 2: ('h', 2), 3: ('f', 4)}
# CGFX attribute usage id -> our name
_ATTR_USAGE = {
    0: 'position', 1: 'normal', 2: 'tangent', 3: 'color',
    4: 'uv0', 5: 'uv1', 6: 'uv2', 7: 'boneIndex', 8: 'boneWeight',
    9: 'userAttr0', 10: 'userAttr1', 11: 'userAttr2',
}


def _unwrap_packdata(buf):
    """DQ7 wraps some CGFX in a 'PackData' container:
      0x00 'PackData'  0x10 u32 entryCount  0x14 u32 tableOfs  0x18 u32 ?
      then at tableOfs: per entry {u32 offset, u32 size} (offsets absolute).
    The first CGFX entry is the model; later entries are CANM etc. Returns
    the inner CGFX slice, or the original buffer unchanged if not PackData.
    """
    if buf[:8] != b'PackData':
        return buf
    cnt = struct.unpack_from('<I', buf, 0x10)[0]
    tbl = struct.unpack_from('<I', buf, 0x14)[0]
    cgfx_entries = []
    for i in range(cnt):
        off = struct.unpack_from('<I', buf, tbl + i * 8)[0]
        size = struct.unpack_from('<I', buf, tbl + i * 8 + 4)[0]
        if 0 < off < len(buf) and buf[off:off + 4] == b'CGFX':
            end = off + size if off + size <= len(buf) else len(buf)
            cgfx_entries.append(buf[off:end])
    if cgfx_entries:
        # prefer a CGFX that actually carries a model (CMDL); some packs
        # bundle an anim-only CGFX first.
        for c in cgfx_entries:
            if b'CMDL' in c:
                return c
        return cgfx_entries[0]
    j = buf.find(b'CGFX')
    return buf[j:] if j >= 0 else buf


def load_bcmdl_bytes(path):
    """Read a model file -> raw CGFX bytes. Handles LZ11 (.lz) and the
    'PackData' wrapper used by the *.pack.lz companion files (which carry
    the full quantized mesh geometry; the bare *.bcmdl.lz is lighter)."""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw[:1] == b'\x11':
        raw = decompress_lz11(raw)
    return _unwrap_packdata(raw)


class Cgfx:
    def __init__(self, data: bytes):
        self.d = data
        if data[:4] != b'CGFX':
            raise ValueError(f'not a CGFX container (magic {data[:4]!r})')
        self.rev = self.u32(8)
        if self.d[0x14:0x18] != b'DATA':
            raise ValueError('no DATA section at 0x14')

    # ---- primitive readers -------------------------------------------------
    def u8(self, o):  return self.d[o]
    def u16(self, o): return struct.unpack_from('<H', self.d, o)[0]
    def u32(self, o): return struct.unpack_from('<I', self.d, o)[0]
    def i32(self, o): return struct.unpack_from('<i', self.d, o)[0]
    def f32(self, o): return struct.unpack_from('<f', self.d, o)[0]

    def ref(self, o):
        """Resolve a self-relative offset field at absolute position `o`.
        Returns 0 for null or for anything that lands outside the buffer."""
        if o < 0 or o + 4 > len(self.d):
            return 0
        v = self.i32(o)
        if v == 0:
            return 0
        t = o + v
        return t if 0 <= t < len(self.d) else 0

    def cstr(self, o):
        if not o or o >= len(self.d):
            return ''
        e = self.d.find(b'\x00', o)
        return self.d[o:e].decode('ascii', 'replace') if e >= 0 else ''

    # ---- DICT ------------------------------------------------------------
    def read_dict(self, o):
        """Return [(name, dataAbsOffset), ...] for the DICT at absolute `o`."""
        if not o or self.d[o:o + 4] != b'DICT':
            return []
        count = self.u32(o + 8)
        out = []
        node = o + 12
        for i in range(count + 1):
            name_ref = self.ref(node + 8)
            data_ref = self.ref(node + 12)
            if i > 0:  # node[0] is the tree root
                out.append((self.cstr(name_ref), data_ref))
            node += 16
        return out

    def data_dicts(self):
        """{'Models': [(name, off), ...], 'Textures': [...], ...} (only non-empty)."""
        base = 0x1c
        res = {}
        for k, nm in enumerate(_DATA_DICTS):
            o = base + k * 8
            cnt = self.u32(o)
            ptr = self.ref(o + 4)
            if cnt and ptr:
                res[nm] = self.read_dict(ptr)
        return res

    # ---- structural inventory (always safe) -----------------------------
    def structure(self):
        dd = self.data_dicts()
        magics = {}
        for m in (b'CMDL', b'SOBJ', b'MTOB', b'TXOB', b'SHDR', b'LUTS', b'CENV', b'ANOD'):
            i = 0
            n = 0
            while True:
                i = self.d.find(m, i)
                if i < 0:
                    break
                n += 1
                i += 4
            if n:
                magics[m.decode()] = n
        return {
            'revision': f'0x{self.rev:08x}',
            'size': len(self.d),
            'dicts': {k: [n for n, _ in v] for k, v in dd.items()},
            'chunk_counts': magics,
            'shapes': [f'0x{o:x}' for o in self._shape_offsets()],
            'textures': [n for n, _ in dd.get('Textures', [])],
            'materials': [n for n, _ in dd.get('Materials', [])],
        }

    # ---- geometry (SPICA CtrGfx layout, verified against MONSTER/e001) --
    #
    # All refs self-relative. Field maps (byte offsets from the object's
    # TypeChoice word) confirmed by hand against dq8-tools/_ref/SPICA and a
    # dq7 monster model:
    #
    # GfxModel (0x4000_0012 plain / 0x4000_0092 skeletal), TypeChoice word
    # at P:
    #   +0x00 typeId  +0x04 'CMDL'  +0x08 rev  +0x0c nameRef
    #   +0x10 meta.count +0x14 meta.ref
    #   +0x18 branchVisible  +0x1c isBranchVisible (bool = 4 bytes!)
    #   +0x20 childs.count +0x24 childs.ref
    #   +0x28 animGrp.count +0x2c animGrp.ref
    #   +0x30 scale[3] +0x3c rot[3] +0x48 trans[3]
    #   +0x54 localMtx[12] +0x84 worldMtx[12]
    #   +0xb4 meshes.count   +0xb8 meshes.ref
    #   +0xbc materials.count +0xc0 materials.ref
    #   +0xc4 shapes.count   +0xc8 shapes.ref   (-> array of self-rel ptrs)
    #
    # GfxShape (0x1000_0001), word at S:
    #   +0x00 typeId +0x04 'SOBJ' +0x08 rev +0x0c nameRef
    #   +0x10 meta.count +0x14 meta.ref
    #   +0x18 flags  +0x1c boundingBox.ref
    #   +0x20 positionOffset[3]
    #   +0x2c subMeshes.count +0x30 subMeshes.ref
    #   +0x34 baseAddress
    #   +0x38 vertexBuffers.count +0x3c vertexBuffers.ref
    #   +0x40 blendShape.ref
    #
    # GfxVertexBufferInterleaved (0x4000_0002), word at V:
    #   +0x04 attrName +0x08 type +0x0c bufferObj +0x10 locationFlag
    #   +0x14 raw.len(i32) +0x18 raw.ref  +0x1c locationPtr +0x20 memoryArea
    #   +0x24 vertexStride +0x28 attrs.count +0x2c attrs.ref
    # GfxAttribute (0x4000_0001), word at A:
    #   +0x04 attrName +0x08 type +0x0c bufferObj +0x10 locationFlag
    #   +0x14 raw.len +0x18 raw.ref +0x1c locationPtr +0x20 memoryArea
    #   +0x24 format(GL enum) +0x28 elements +0x2c scale(f32) +0x30 offset
    #
    # GfxSubMesh: +0x00 boneIdx.count +0x04 boneIdx.ref +0x08 skinning
    #             +0x0c faces.count +0x10 faces.ref
    # GfxFace:    +0x00 faceDesc.count +0x04 faceDesc.ref
    # GfxFaceDescriptor: +0x00 format(GL enum) +0x04 primMode/visible
    #             +0x08 raw.len(i32) +0x0c raw.ref  (-> index bytes)

    _GL = {0x1400: ('b', 1), 0x1401: ('B', 1), 0x1402: ('h', 2),
           0x1403: ('H', 2), 0x1406: ('f', 4), 0x140C: ('i', 4)}
    _NAME = {0: 'position', 1: 'normal', 2: 'tangent', 3: 'color',
             4: 'uv0', 5: 'uv1', 6: 'uv2', 7: 'boneIndex', 8: 'boneWeight'}

    def _list_ref(self, o):
        """A `[i32 count][u32 selfRelPtr]` list field at absolute `o`.
        Returns (count, array_abs_offset)."""
        return self.i32(o), self.ref(o + 4)

    def _model_offsets(self):
        return [off for _, off in self.data_dicts().get('Models', [])]

    def _shape_offsets(self):
        out = []
        for m in self._model_offsets():
            cnt, arr = self._list_ref(m + 0xC4)
            if arr and 0 < cnt < 4096:
                for k in range(cnt):
                    sp = self.ref(arr + k * 4)
                    if sp and self.d[sp + 4:sp + 8] == b'SOBJ':
                        out.append(sp)
        return out

    def _decode_attr(self, stream, stride, vcount, a):
        """a = (name, glformat, elements, scale, offset) -> list of tuples."""
        _, gfmt, elem, scale, aoff = a
        fchar, _ = self._GL.get(gfmt, ('f', 4))
        sfmt = '<' + fchar * elem
        step = struct.calcsize(sfmt)
        d = self.d
        out = []
        for v in range(vcount):
            o = stream + v * stride + aoff
            if o + step > len(d):
                break
            raw = struct.unpack_from(sfmt, d, o)
            out.append(tuple(x * scale for x in raw))
        return out

    def _parse_interleaved(self, v):
        stride = self.i32(v + 0x24)
        acnt, aarr = self._list_ref(v + 0x28)
        raw_len = self.i32(v + 0x14)
        raw = self.ref(v + 0x18)
        if not raw or stride <= 0 or not (0 < acnt <= 32):
            return None
        vcount = raw_len // stride
        attrs = []
        for k in range(acnt):
            ap = self.ref(aarr + k * 4)
            if not ap or self.u32(ap) != 0x40000001:
                continue
            name = self._NAME.get(self.u32(ap + 0x04), f'attr{self.u32(ap + 0x04)}')
            gfmt = self.u32(ap + 0x24)
            elem = self.i32(ap + 0x28)
            scale = self.f32(ap + 0x2C)
            aoff = self.i32(ap + 0x30)
            attrs.append((name, gfmt, elem, scale, aoff))
        return {'stream': raw, 'stride': stride, 'vcount': vcount, 'attrs': attrs}

    # ---- skeleton (bind-pose bone world transforms) --------------------
    #
    # GfxModelSkeletal (typeId 0x40000092): after the GfxModel fields, a
    #   +0xE0  GfxSkeleton ref
    # GfxSkeleton (typeId 0x02000000), word at K:
    #   +0x18 Bones.count  +0x1C Bones.ref (-> DICT of GfxBone)
    # GfxBone record (stride 0xE0, NOT a GfxObject - no typeId/magic):
    #   +0x00 name ref  +0x04 flags  +0x08 Index  +0x0C ParentIndex
    #   +0x10 Parent ref +0x14 Child ref +0x18 PrevSib +0x1C NextSib
    #   +0x20 scale[3] +0x2C rot[3] +0x38 trans[3]
    #   +0x44 LocalTransform  Matrix3x4 (48)
    #   +0x74 WorldTransform  Matrix3x4 (48)   <- bind pose, what we need
    #   +0xA4 InvWorldTransform Matrix3x4 (48)
    # Matrix3x4 on disk = 12 f32 in the order M11,M21,M31,M41, M12,M22,
    # M32,M42, M13,M23,M33,M43 (row-major 3x4 affine, translation in the
    # 4th column): x' = x*f0 + y*f1 + z*f2 + f3  (and f4..7 -> y', f8..11 -> z').

    @staticmethod
    def _mat_to_trs(m):
        """Decompose a row-major 3x4 affine matrix (see `_mat_mul` docstring
        for the on-disk layout) into (pos[3], quat[4] xyzw, scale[3]) so a
        client can rebuild the transform as THREE.Bone position/quaternion/
        scale. Scale = column norms of the 3x3 part; rotation = that part
        with columns re-normalized, converted to a quaternion (Shepperd)."""
        c0 = (m[0], m[4], m[8])
        c1 = (m[1], m[5], m[9])
        c2 = (m[2], m[6], m[10])
        sx = (c0[0]**2 + c0[1]**2 + c0[2]**2) ** 0.5 or 1.0
        sy = (c1[0]**2 + c1[1]**2 + c1[2]**2) ** 0.5 or 1.0
        sz = (c2[0]**2 + c2[1]**2 + c2[2]**2) ** 0.5 or 1.0
        r00, r10, r20 = c0[0] / sx, c0[1] / sx, c0[2] / sx
        r01, r11, r21 = c1[0] / sy, c1[1] / sy, c1[2] / sy
        r02, r12, r22 = c2[0] / sz, c2[1] / sz, c2[2] / sz
        trace = r00 + r11 + r22
        if trace > 0:
            s = (trace + 1.0) ** 0.5 * 2
            qw = 0.25 * s
            qx = (r21 - r12) / s
            qy = (r02 - r20) / s
            qz = (r10 - r01) / s
        elif r00 > r11 and r00 > r22:
            s = (1.0 + r00 - r11 - r22) ** 0.5 * 2
            qw = (r21 - r12) / s
            qx = 0.25 * s
            qy = (r01 + r10) / s
            qz = (r02 + r20) / s
        elif r11 > r22:
            s = (1.0 + r11 - r00 - r22) ** 0.5 * 2
            qw = (r02 - r20) / s
            qx = (r01 + r10) / s
            qy = 0.25 * s
            qz = (r12 + r21) / s
        else:
            s = (1.0 + r22 - r00 - r11) ** 0.5 * 2
            qw = (r10 - r01) / s
            qx = (r02 + r20) / s
            qy = (r12 + r21) / s
            qz = 0.25 * s
        return (m[3], m[7], m[11]), (qx, qy, qz, qw), (sx, sy, sz)

    @staticmethod
    def _mat_mul(a, b):
        """Compose two row-major 3x4 affine matrices: result applies `a`
        then `b`  (point' = ((point . a) . b))."""
        return (
            a[0] * b[0] + a[4] * b[1] + a[8] * b[2],
            a[1] * b[0] + a[5] * b[1] + a[9] * b[2],
            a[2] * b[0] + a[6] * b[1] + a[10] * b[2],
            a[3] * b[0] + a[7] * b[1] + a[11] * b[2] + b[3],
            a[0] * b[4] + a[4] * b[5] + a[8] * b[6],
            a[1] * b[4] + a[5] * b[5] + a[9] * b[6],
            a[2] * b[4] + a[6] * b[5] + a[10] * b[6],
            a[3] * b[4] + a[7] * b[5] + a[11] * b[6] + b[7],
            a[0] * b[8] + a[4] * b[9] + a[8] * b[10],
            a[1] * b[8] + a[5] * b[9] + a[9] * b[10],
            a[2] * b[8] + a[6] * b[9] + a[10] * b[10],
            a[3] * b[8] + a[7] * b[9] + a[11] * b[10] + b[11],
        )

    def _skeleton(self):
        """{bone Index: bind-pose world 3x4 matrix (12 floats)}.

        DQ7 leaves the serialized WorldTransform field (bone+0x74) all
        zero (game engine fills it), so we compose it ourselves from each
        bone's LocalTransform (bone+0x44) up the ParentIndex chain."""
        if getattr(self, '_skel_cache', None) is not None:
            return self._skel_cache
        local, parent = {}, {}
        self._skel_names = {}
        for m in self._model_offsets():
            if self.u32(m) != 0x40000092:          # not skeletal
                continue
            k = self.ref(m + 0xE0)
            if not k or self.d[k + 4:k + 8] != b'SOBJ':
                continue
            bcnt, barr = self._list_ref(k + 0x18)
            if not barr or not (0 < bcnt <= 4096):
                continue
            for _, bo in self.read_dict(barr):
                if not bo:
                    continue
                idx = self.i32(bo + 0x08)
                local[idx] = struct.unpack_from('<12f', self.d, bo + 0x44)
                parent[idx] = self.i32(bo + 0x0C)
                self._skel_names[idx] = self.cstr(self.ref(bo)) or f'bone{idx}'

        world = {}

        def resolve(i, seen):
            if i in world:
                return world[i]
            if i in seen or i not in local:
                return None
            seen.add(i)
            p = parent.get(i, -1)
            pw = resolve(p, seen) if p >= 0 else None
            world[i] = self._mat_mul(local[i], pw) if pw else local[i]
            return world[i]

        for i in local:
            resolve(i, set())
        self._skel_parent = parent
        self._skel_local = local
        self._skel_cache = world
        return world

    def skeleton_bones(self):
        """Bind-pose skeleton as [{index, name, parent, pos:[x,y,z],
        localPos, localQuat, localScale}] in model space (same space as the
        decoded shape vertices), or [] if the model has no skeleton. `pos`
        is the bone head (world); draw a segment to each child's `pos` to
        see the skeleton. `localPos`/`localQuat`(xyzw)/`localScale` are the
        bone's transform relative to its parent (bind pose), decomposed from
        LocalTransform (see `_mat_to_trs`) - enough for a client to rebuild
        a THREE.Bone hierarchy and drive it with animation tracks."""
        world = self._skeleton()
        if not world:
            return []
        names = getattr(self, '_skel_names', {})
        parent = getattr(self, '_skel_parent', {})
        local = getattr(self, '_skel_local', {})
        out = []
        for idx, m in sorted(world.items()):
            lp, lq, ls = self._mat_to_trs(local[idx])
            out.append({
                'index': idx,
                'name': names.get(idx, f'bone{idx}'),
                'parent': parent.get(idx, -1),
                'pos': [m[3], m[7], m[11]],
                'localPos': list(lp),
                'localQuat': list(lq),
                'localScale': list(ls),
            })
        return out

    @staticmethod
    def _xform_pt(m, x, y, z):
        return (x * m[0] + y * m[1] + z * m[2] + m[3],
                x * m[4] + y * m[5] + z * m[6] + m[7],
                x * m[8] + y * m[9] + z * m[10] + m[11])

    @staticmethod
    def _xform_dir(m, x, y, z):
        vx = x * m[0] + y * m[1] + z * m[2]
        vy = x * m[4] + y * m[5] + z * m[6]
        vz = x * m[8] + y * m[9] + z * m[10]
        n = (vx * vx + vy * vy + vz * vz) ** 0.5 or 1.0
        return (vx / n, vy / n, vz / n)

    def _facedesc_indices(self, fdo):
        gfmt = self.u32(fdo + 0x00)
        blen = self.i32(fdo + 0x08)
        bptr = self.ref(fdo + 0x0C)
        if not bptr or blen <= 0 or bptr + blen > len(self.d):
            return []
        unit = 2 if gfmt == 0x1403 else 1
        n = blen // unit
        return list(struct.unpack_from('<%d%s' % (n, 'H' if unit == 2 else 'B'), self.d, bptr))

    def _submeshes(self, s):
        """Yield (skinning, bone_indices, face_index_list) per SubMesh."""
        smc, sma = self._list_ref(s + 0x2C)
        if not sma or not (0 < smc <= 4096):
            return
        for si in range(smc):
            smo = self.ref(sma + si * 4)
            if not smo:
                continue
            bic, bia = self._list_ref(smo + 0x00)
            bone_idx = []
            if bia and 0 < bic <= 4096:
                bone_idx = list(struct.unpack_from('<%di' % bic, self.d, bia))
            skinning = self.u32(smo + 0x08)
            fc, fa = self._list_ref(smo + 0x0C)
            faces = []
            if fa and 0 < fc <= 4096:
                for fi in range(fc):
                    fo = self.ref(fa + fi * 4)
                    if not fo:
                        continue
                    fdc, fda = self._list_ref(fo + 0x00)
                    if not fda or not (0 < fdc <= 4096):
                        continue
                    for di in range(fdc):
                        fdo = self.ref(fda + di * 4)
                        if fdo:
                            faces.extend(self._facedesc_indices(fdo))
            yield skinning, bone_idx, faces

    def _one_shape(self, s):
        name = self.cstr(self.ref(s + 0x0C))
        vc, va = self._list_ref(s + 0x38)
        inter = None
        if va and 0 < vc <= 32:
            for k in range(vc):
                vp = self.ref(va + k * 4)
                if vp and self.u32(vp) == 0x40000002:
                    inter = self._parse_interleaved(vp)
                    break
        if not inter or not inter['attrs']:
            return {'name': name, 'offset': f'0x{s:x}', 'ok': False,
                    'reason': 'no interleaved vertex buffer'}
        stream, stride, vcount = inter['stream'], inter['stride'], inter['vcount']
        pos_a = next((a for a in inter['attrs'] if a[0] == 'position'), None)
        if not pos_a or vcount <= 0:
            return {'name': name, 'offset': f'0x{s:x}', 'ok': False,
                    'reason': 'no position attribute'}
        pos = self._decode_attr(stream, stride, vcount, pos_a)
        nrm_a = next((a for a in inter['attrs'] if a[0] == 'normal'), None)
        uv_a = next((a for a in inter['attrs'] if a[0] == 'uv0'), None)
        uv1_a = next((a for a in inter['attrs'] if a[0] == 'uv1'), None)
        uv2_a = next((a for a in inter['attrs'] if a[0] == 'uv2'), None)
        bi_a = next((a for a in inter['attrs'] if a[0] == 'boneIndex'), None)
        bw_a = next((a for a in inter['attrs'] if a[0] == 'boneWeight'), None)
        nrm = self._decode_attr(stream, stride, vcount, nrm_a) if nrm_a else None
        uv0 = self._decode_attr(stream, stride, vcount, uv_a) if uv_a else None
        uv1 = self._decode_attr(stream, stride, vcount, uv1_a) if uv1_a else None
        uv2 = self._decode_attr(stream, stride, vcount, uv2_a) if uv2_a else None
        # Vertex color (usage 3). Map parts (MAP/MAPDATA FldData) carry
        # position+color+uv0 with no normals - the lighting is baked into
        # this RGBA (float 0..1 there; the attribute's own scale normalizes
        # other formats the same way as uv/boneWeight).
        col_a = next((a for a in inter['attrs'] if a[0] == 'color'), None)
        col = self._decode_attr(stream, stride, vcount, col_a) if col_a else None
        bidx = self._decode_attr(stream, stride, vcount, bi_a) if bi_a else None
        bwgt = self._decode_attr(stream, stride, vcount, bw_a) if bw_a else None
        poff = struct.unpack_from('<3f', self.d, s + 0x20)

        bones = self._skeleton()
        subs = list(self._submeshes(s))

        def influences(vi, bone_idx, skinning):
            """[(global_bone_idx, weight), ...], weight>0 only, up to 4.

            skinning != 2 (rigid/none): one vertex = one bone, weight 1.0 -
            same "dominant influence" `bidx[vi][0]` used for the position
            transform below (see docs/bcmdl_model_viewer.md skinning notes).
            skinning == 2 (smooth): a real multi-bone blend. Two on-disk
            shapes seen (both confirmed against p0003_j00.bcmdl.lz):
              - boneIndex attr present (byte, LOCAL index into this
                submesh's `bone_idx` array) + boneWeight attr (byte, scaled
                to 0..1 by the attribute's own `scale` field) with the same
                element count -> pair them up per component.
              - boneWeight attr only, N components matching len(bone_idx)
                exactly -> positional correspondence, weight[k] <-> bone_idx[k]
                (no per-vertex index needed because every vertex in the
                submesh may reference the same fixed bone list)."""
            if not bone_idx:
                return []
            if skinning != 2:
                li = int(round(bidx[vi][0])) if bidx else 0
                gi = bone_idx[li] if 0 <= li < len(bone_idx) else bone_idx[0]
                return [(gi, 1.0)]
            if bidx and bwgt:
                n = min(len(bidx[vi]), len(bwgt[vi]))
                out = []
                for k in range(n):
                    w = bwgt[vi][k]
                    if w <= 1e-6:
                        continue
                    li = int(round(bidx[vi][k]))
                    if 0 <= li < len(bone_idx):
                        out.append((bone_idx[li], w))
                return out[:4]
            if bwgt and not bidx:
                n = min(len(bwgt[vi]), len(bone_idx))
                return [(bone_idx[k], bwgt[vi][k]) for k in range(n) if bwgt[vi][k] > 1e-6][:4]
            if bidx and not bwgt:
                li = int(round(bidx[vi][0]))
                gi = bone_idx[li] if 0 <= li < len(bone_idx) else bone_idx[0]
                return [(gi, 1.0)]
            return [(bone_idx[0], 1.0)]

        # Rigid / None submeshes store vertices in their bone's LOCAL space -
        # multiply by the dominant bone's bind-pose WorldTransform to place
        # them (this is why unskinned face/hand shapes were piling up at the
        # origin). Smooth submeshes are already in model space and instead
        # carry a real multi-bone weight blend (see `influences` above) -
        # used for animation only, bind-pose position is untouched. Build an
        # expanded, per-submesh-transformed vertex list (models here are small).
        out_pos, out_nrm, out_uv, out_idx = [], [], [], []
        out_uv1, out_uv2 = [], []
        out_col = []
        out_skin_idx, out_skin_weight = [], []
        used_any = False
        any_skin = False
        for skinning, bone_idx, faces in subs:
            if not faces:
                continue
            used_any = True
            do_xform = bones and skinning != 2 and bone_idx
            remap = {}
            for vi in faces:
                if vi >= vcount:
                    continue
                key = vi
                if key not in remap:
                    px, py, pz = pos[vi][:3] if len(pos[vi]) >= 3 else (list(pos[vi]) + [0, 0, 0])[:3]
                    px += poff[0]; py += poff[1]; pz += poff[2]
                    nx, ny, nz = (nrm[vi] + (0, 0, 0))[:3] if nrm else (0.0, 0.0, 0.0)
                    infs = influences(vi, bone_idx, skinning) if bones and bone_idx else []
                    if do_xform and infs:
                        m = bones.get(infs[0][0])
                        if m:
                            px, py, pz = self._xform_pt(m, px, py, pz)
                            if nrm:
                                nx, ny, nz = self._xform_dir(m, nx, ny, nz)
                        else:
                            infs = []
                    remap[key] = len(out_pos) // 3
                    out_pos.extend((px, py, pz))
                    if infs:
                        any_skin = True
                    for slot in range(4):
                        if slot < len(infs):
                            out_skin_idx.append(infs[slot][0])
                            out_skin_weight.append(infs[slot][1])
                        else:
                            out_skin_idx.append(0)
                            out_skin_weight.append(0.0)
                    if nrm:
                        out_nrm.extend((nx, ny, nz))
                    if uv0:
                        out_uv.extend((uv0[vi] + (0, 0))[:2])
                    if uv1:
                        out_uv1.extend((uv1[vi] + (0, 0))[:2])
                    if uv2:
                        out_uv2.extend((uv2[vi] + (0, 0))[:2])
                    if col:
                        out_col.extend((col[vi] + (1, 1, 1, 1))[:4])
                out_idx.append(remap[key])

        if not used_any:
            # no submesh face lists - fall back to a plain vertex soup
            for i, v in enumerate(pos):
                x, y, z = (list(v) + [0, 0, 0])[:3]
                out_pos.extend((x + poff[0], y + poff[1], z + poff[2]))
            out_skin_idx = [0] * (len(pos) * 4)
            out_skin_weight = [0.0] * (len(pos) * 4)
            if nrm:
                out_nrm = [c for v in nrm for c in (list(v) + [0, 0, 0])[:3]]
            if uv0:
                out_uv = [c for v in uv0 for c in (list(v) + [0, 0])[:2]]
            if uv1:
                out_uv1 = [c for v in uv1 for c in (list(v) + [0, 0])[:2]]
            if uv2:
                out_uv2 = [c for v in uv2 for c in (list(v) + [0, 0])[:2]]
            if col:
                out_col = [c for v in col for c in (list(v) + [1, 1, 1, 1])[:4]]
            out_idx = list(range(len(pos)))

        out = {
            'name': name, 'offset': f'0x{s:x}', 'ok': True,
            'vcount': len(out_pos) // 3, 'icount': len(out_idx),
            'attrs': [a[0] for a in inter['attrs']],
            'skinned': bool(bones) and any_skin,
            'positions': out_pos, 'indices': out_idx,
        }
        if out_nrm:
            out['normals'] = out_nrm
        if out_uv:
            out['uvs'] = out_uv
        if out_uv1:
            out['uvs1'] = out_uv1
        if out_uv2:
            out['uvs2'] = out_uv2
        if out_col:
            out['colors'] = out_col
        if out['skinned']:
            out['skinIndex'] = out_skin_idx
            out['skinWeight'] = out_skin_weight
        return out

    def geometry(self):
        shapes = []
        errors = []
        offs = self._shape_offsets()
        for so in offs:
            try:
                shapes.append(self._one_shape(so))
            except Exception as e:  # noqa: BLE001 - keep going, report
                errors.append(f'SOBJ@0x{so:x}: {type(e).__name__}: {e}')
        return {
            'shapes': shapes,
            'ok_count': sum(1 for s in shapes if s.get('ok')),
            'total_shapes': len(offs),
            'errors': errors,
        }


    # ---- textures (TXOB) ---------------------------------------------
    #
    # GfxTexture / GfxTextureImage (typeId 0x20000011), word at T:
    #   +0x00 typeId  +0x04 'TXOB'  +0x08 rev  +0x0C name ref
    #   +0x10 meta.count +0x14 meta.ref
    #   +0x18 Height  +0x1C Width  +0x20 GLFormat  +0x24 GLType
    #   +0x28 MipmapSize  +0x2C TextureObj  +0x30 LocationFlag
    #   +0x34 HwFormat (PICATextureFormat 0..13)
    #   +0x38 Image ref -> GfxTextureImageData:
    #         +0x00 Height  +0x04 Width
    #         +0x08 raw.len(i32)  +0x0C raw.ref (pixel bytes, base + mips)
    #         +0x10 DynamicAlloc  +0x14 BitsPerPixel ...
    def textures(self):
        out = []
        for name, off in self.data_dicts().get('Textures', []):
            if not off or self.d[off + 4:off + 8] != b'TXOB':
                continue
            h = self.i32(off + 0x18)
            w = self.i32(off + 0x1C)
            fmt = self.u32(off + 0x34)
            img = self.ref(off + 0x38)
            rec = {'name': name, 'width': w, 'height': h, 'format_id': fmt,
                   'format': None, 'ok': False}
            if 0 <= fmt < len(_FMT_NAMES):
                rec['format'] = _FMT_NAMES[fmt]
            if img:
                rlen = self.i32(img + 0x08)
                rptr = self.ref(img + 0x0C)
                if rptr and 0 < w <= 4096 and 0 < h <= 4096 and rec['format']:
                    need = _tex_min_bytes(w, h, fmt)
                    if 0 < need <= rlen and rptr + need <= len(self.d):
                        rec['ok'] = True
                        rec['_raw'] = self.d[rptr:rptr + need]
            out.append(rec)
        return out

    def texture_png(self, name):
        for t in self.textures():
            if t['name'] == name and t.get('ok'):
                import ctr_texture
                return ctr_texture.to_png(t['_raw'], t['width'], t['height'],
                                          t['format_id'])
        return None


# GfxTestFunc (SPICA CtrGfx.Model.Material.GfxTestFunc / hardware PICATestFunc,
# same ordering): the comparison the PICA200 alpha test performs against the
# per-material reference value.
_ALPHA_TEST_FUNC_NAMES = [
    'never', 'always', 'less', 'lequal', 'equal', 'gequal', 'greater', 'notequal',
]

# GfxAlphaTest (SPICA CtrGfx.Model.Material.GfxAlphaTest / GfxFragShader.AlphaTest)
# is serialized as a *raw PICA200 command pair*, not a plain struct: word0 is
# the packed test param (bit0 Enabled, bits4-6 Function, bits8-15 Reference
# 0..255), word1 is the command header `GPUREG_FRAGOP_ALPHA_TEST(0x0104) |
# (mask=0xf)<<16` == the fixed 32-bit constant 0x000F0104 emitted by
# PICACommandWriter.SetCommand() (see _ref/SPICA
# PICA/PICACommandWriter.cs:46-50, Formats/CtrGfx/Model/Material/
# GfxAlphaTest.cs). Because that header word is fixed, scanning an MTOB
# record for it locates the real, per-material alpha-test config the game
# actually uses - confirmed empirically (see docs/bcmdl_model_viewer.md,
# 2026-09-21 "AlphaTest構造体を読む根本修正"): CHARACTER/p0001_j01's `yoroi`
# (armor/helmet) and p0001_j06's `fuku` (torso) both have Enabled=False (no
# cutout at all - the alpha channel there isn't live transparency), while
# `FaceMaterial` has Enabled=True, Function=Greater, Reference=128 (real
# eye/mouth cutouts). This replaces the earlier `_base_texture_mostly_holes`
# UV-sampling heuristic, which only *guessed* opaqueness from where a shape's
# UVs happened to land on the texture instead of reading the GPU state DQ7
# actually shipped.
_ALPHA_TEST_HDR = 0x000F0104


def _alpha_test(cg, mo, end):
    """Scan MTOB bytes [mo, end) for the GfxFragShader.AlphaTest command pair
    and return {'enabled', 'function', 'functionName', 'reference'} (reference
    0..255), or None if not found (e.g. unexpected/older CGFX revision) - the
    caller should fall back to treating alpha as live transparency in that
    case."""
    d = cg.d
    for off in range(4, end - mo, 4):
        if struct.unpack_from('<I', d, mo + off)[0] != _ALPHA_TEST_HDR:
            continue
        param = struct.unpack_from('<I', d, mo + off - 4)[0]
        func = (param >> 4) & 7
        return {
            'enabled': bool(param & 1),
            'function': func,
            'functionName': _ALPHA_TEST_FUNC_NAMES[func],
            'reference': (param >> 8) & 0xff,
        }
    return None


# GfxRasterization.FaceCullingCommand (SPICA CtrGfx.Model.Material.
# GfxRasterization) is, like AlphaTest, a raw PICA200 command pair: word0 is
# the packed CullMode param (bits0-1, PICAFaceCulling: 0=Never/no culling ->
# both faces drawn, 1=FrontFace culled -> only back faces drawn, 2=BackFace
# culled -> only front faces drawn, the usual single-sided case), word1 is
# `GPUREG_FACECULLING_CONFIG(0x0040) | (mask=1)<<16` == the fixed constant
# 0x00010040 (GfxRasterization.cs: `Writer.SetCommand(...CullMode, 1)`).
# Investigating CHARACTER/p0006_j09's reported color/layering weirdness
# turned this up: every shape is rendered `THREE.DoubleSide` regardless of
# what the material actually specifies (see docs/bcmdl_model_viewer.md,
# 2026-09-21 "CullMode構造体を読む修正") - e.g. its `body`/`huku`/
# `FaceMaterial` are real single-sided (CullMode=2, draw front only) while
# `bodyryomen`/`hukuyomen`/`kami`/`kami2`/`acse` are CullMode=0 (Never,
# intentionally double-sided - thin flap/hair-strand geometry, not a mistake
# to "fix" by culling). Forcing DoubleSide everywhere means the single-sided
# shapes' normally-hidden backfaces get drawn too, which can z-fight or peek
# through neighboring geometry, showing wrong colors/edges at some angles.
# Sampled 191 materials across 50 random files: every one produced exactly
# one hit (one had a spurious second match elsewhere in the record - the
# first is always the real one, matching `_alpha_test()`'s precedent).
_CULL_HDR = 0x00010040
# PICAFaceCulling value -> THREE.js `side` constant name the caller should use.
_CULL_SIDE_NAMES = {0: 'double', 1: 'back', 2: 'front'}


def _cull_mode(cg, mo, end):
    """Scan MTOB bytes [mo, end) for GfxRasterization.FaceCullingCommand and
    return 'front' | 'back' | 'double' (THREE.js `side` to render with), or
    None if not found."""
    d = cg.d
    for off in range(4, end - mo, 4):
        if struct.unpack_from('<I', d, mo + off)[0] != _CULL_HDR:
            continue
        param = struct.unpack_from('<I', d, mo + off - 4)[0] & 3
        return _CULL_SIDE_NAMES.get(param, 'double')
    return None


# GfxTexEnv (SPICA CtrGfx.Model.Material.GfxTexEnv, the up-to-6-stage PICA200
# texture combiner every material's FragmentShader carries) is, like
# AlphaTest/CullMode, written as a raw PICA200 command - but a *Consecutive*
# one (PICACommandWriter.SetCommands): stage N's header is
# `GPUREG_TEXENV<N>_SOURCE(0xC0 + N*8) | (mask=0xf)<<16 | (extraParams=4)<<20
# | (Consecutive=1)<<31`, a fixed constant PER STAGE INDEX (see
# GfxTexEnv.cs RebuildCommands()). The raw layout around that header is
# `[Source][header][Operand][Combiner][Color][Scale]` (6 words = the
# Consecutive command's first param, then the header, then its 4 remaining
# params - see PICACommandWriter.SetCommands()).
#
# Why this replaces a heuristic: whether a secondary texture (mapper 1 or 2)
# is a real alpha decal, a multiply-tint/shading map, an additive glow map,
# or not sampled by the pixel combiner AT ALL (e.g. consumed only by a
# separate compiled shader program as a normal map input - PICA200's
# fixed-function TexEnv combiner and a SHDR program are two different,
# independent things) is *exactly* what this data says: which
# PICATextureCombinerSource(Texture0=3/Texture1=4/Texture2=5) each active
# stage's color/alpha inputs use, and which PICATextureCombinerMode combines
# them. Guessing this from how opaque the texture's pixels happen to be
# (the previous, REMOVED approach - `_texture_opaque_fraction()`/
# `_DECAL_MAX_OPAQUE_FRACTION`, see docs/bcmdl_model_viewer.md, 2026-09-21
# "TexEnvコンバイナ構造を読む根本修正") was a plausible-looking proxy that
# happened to separate the two 80-file samples checked, but is not what the
# GPU actually does - a texture that never appears as a Texture{1,2} source
# in any stage is, by construction, not part of the combiner's color/alpha
# output no matter what its own pixels look like, and one that IS
# referenced should be composited the way its combiner mode actually says,
# not approximated as one generic "alpha decal".
_TEXENV_STAGE_COUNT = 6
_TEXENV_HDRS = {
    (0xC0 + stage * 8) | (0xf << 16) | (4 << 20) | 0x80000000: stage
    for stage in range(_TEXENV_STAGE_COUNT)
}
# PICATextureCombinerSource values for the physical texture units (mapper
# index -> source id); PrimaryColor/FragmentPrimary/FragmentSecondary/
# Constant/Previous/PreviousBuffer are the non-texture sources and aren't
# mapper-specific.
_TEXENV_SRC_TEXTURE = {0: 3, 1: 4, 2: 5}
# PICATextureCombinerMode order (GfxTextureCombinerMode enum).
_COMBINER_MODE_NAMES = [
    'replace', 'modulate', 'add', 'addSigned', 'interpolate',
    'subtract', 'dotProduct3Rgb', 'dotProduct3Rgba', 'multAdd', 'addMult',
]
# How many of the 3 source/operand slots each combiner mode actually reads,
# confirmed against SPICA's GLSL emitter (SPICA.Rendering/Shaders/
# FragmentShaderGenerator.cs GenCombinerColor/GenCombinerAlpha): Replace=1
# (`Args[0]`), Modulate/Add/AddSigned/Subtract/DotProduct3*=2 (`Args[0..1]`),
# Interpolate/MultAdd/AddMult=3 (`Args[0..2]`). A source nibble beyond a
# mode's input count is unused padding in the raw command, NOT a real input -
# see the mapper-role bug this fixes, below.
_COMBINER_INPUT_COUNT = {
    'replace': 1, 'modulate': 2, 'add': 2, 'addSigned': 2, 'interpolate': 3,
    'subtract': 2, 'dotProduct3Rgb': 2, 'dotProduct3Rgba': 2,
    'multAdd': 3, 'addMult': 3,
}
# Combiner mode -> how we actually composite that stage's texture as an
# overlay mesh on top of the base (stage 0) mesh, in terms three.js can
# render directly:
#   'interpolate' -> lerp(previous, thisTexture, thisTexture.alpha), which a
#     normal alpha-blended overlay mesh approximates directly (this is what
#     real decals - eyes, mouths, emblems - use).
#   'modulate'    -> previous * thisTexture (channel-wise multiply) ->
#     THREE.MultiplyBlending.
#   'add'/'addSigned'/'multAdd'/'addMult' -> all sum something onto
#     `previous` -> THREE.AdditiveBlending approximates the visible result
#     (a brightening contribution) reasonably for the glow/highlight-style
#     stages DQ7 uses these for.
#   Anything else observed (replace/subtract/dotProduct*) is rare enough in
#   practice that we fall back to the interpolate/alpha-blend treatment
#   rather than invent a bespoke three.js material for it.
_COMBINER_TO_BLEND = {
    'interpolate': 'blend',
    'modulate': 'multiply',
    'add': 'add', 'addSigned': 'add', 'multAdd': 'add', 'addMult': 'add',
}


def _tex_env_mapper_roles(cg, mo, end):
    """{mapperIndex(1|2): 'blend'|'multiply'|'add'} for every TextureMapper
    slot beyond the base (mapper 0) that some active TexEnv stage actually
    samples as a Texture1/Texture2 combiner source (color OR alpha) - see
    the big comment above. A mapper index simply absent from the returned
    dict means no stage ever references it as a color/alpha source: it is
    genuinely not part of this material's pixel output (most likely a
    normal/shading map feeding a separate SHDR program instead), so the
    caller should not render it as an overlay at all - not "render it but
    mostly-transparent", not render it at all.

    A stage's raw Source word always has 3 nibbles per channel (color/alpha)
    regardless of how many the stage's combiner mode actually reads (see
    _COMBINER_INPUT_COUNT) - e.g. Modulate only evaluates Args[0]/Args[1],
    so whatever texture ID happens to sit in the unused 3rd nibble is NOT
    actually part of that stage's output. Found via MONSTER/e001.bcmdl.lz
    (monster "e001", reported rendering solid black instead of its blue base
    with e001b's black regions showing through): stage0 is
    Modulate(Texture2, Texture0) with Texture1(e001b)'s id sitting unread in
    the unused 3rd color-source nibble; before this fix that unused nibble
    made mapper1(e001b) match first and get locked in as stage0's 'modulate'
    (-> MultiplyBlending), even though e001b's real-and-only use is stage1's
    MultAdd(Previous, FragmentPrimaryColor, Texture1) - a 3-input op whose
    3rd term genuinely adds Texture1 onto the running result (-> additive:
    black contributes nothing, matching the expected see-through blue).
    Truncating each stage's source nibbles to its mode's real input count
    before matching fixes this (and generalizes: any mode whose 3rd nibble
    is unused - Replace/Modulate/Add/AddSigned/Subtract/DotProduct3* - can
    no longer produce a false match off of combiner-irrelevant padding)."""
    d = cg.d
    roles = {}
    off = 4
    limit = end - mo
    while off + 4 <= limit:
        stage = _TEXENV_HDRS.get(struct.unpack_from('<I', d, mo + off)[0])
        if stage is not None and off + 16 <= limit:
            source = struct.unpack_from('<I', d, mo + off - 4)[0]
            combiner = struct.unpack_from('<I', d, mo + off + 8)[0]
            color_mode = _COMBINER_MODE_NAMES[combiner & 0xf]
            alpha_mode = _COMBINER_MODE_NAMES[(combiner >> 16) & 0xf]
            n_color = _COMBINER_INPUT_COUNT.get(color_mode, 3)
            n_alpha = _COMBINER_INPUT_COUNT.get(alpha_mode, 3)
            color_src = [(source >> k) & 0xf for k in (0, 4, 8)][:n_color]
            alpha_src = [(source >> k) & 0xf for k in (16, 20, 24)][:n_alpha]
            for mapper_idx, tex_src in _TEXENV_SRC_TEXTURE.items():
                if mapper_idx == 0 or mapper_idx in roles:
                    continue  # mapper 0 always renders as the base mesh
                if tex_src in color_src:
                    roles[mapper_idx] = _COMBINER_TO_BLEND.get(color_mode, 'blend')
                elif tex_src in alpha_src:
                    roles[mapper_idx] = _COMBINER_TO_BLEND.get(alpha_mode, 'blend')
        off += 4
    return roles


# PICATextureCombinerSource.PrimaryColor - the vertex shader's output color,
# i.e. the per-vertex `color` attribute for the unlit map shaders.
_TEXENV_SRC_PRIMARY_COLOR = 0


def _tex_env_vertex_color_mode(cg, mo, end):
    """'modulate' | 'replace' | ... (the combiner mode of the first active
    TexEnv stage that reads PrimaryColor as a COLOR input), or None when no
    stage does. Same stage scan / input-count truncation as
    `_tex_env_mapper_roles()`. Every map part material (MAP/MAPDATA FldData,
    648 materials sampled across c01nout/wld_n25a) is stage0 =
    Modulate(PrimaryColor, Texture0) with stages 1.. = Replace(Previous): the
    baked vertex color multiplies the texture."""
    d = cg.d
    off = 4
    limit = end - mo
    while off + 16 <= limit:
        if _TEXENV_HDRS.get(struct.unpack_from('<I', d, mo + off)[0]) is not None:
            source = struct.unpack_from('<I', d, mo + off - 4)[0]
            combiner = struct.unpack_from('<I', d, mo + off + 8)[0]
            color_mode = _COMBINER_MODE_NAMES[combiner & 0xf]
            n_color = _COMBINER_INPUT_COUNT.get(color_mode, 3)
            if _TEXENV_SRC_PRIMARY_COLOR in [(source >> k) & 0xf for k in (0, 4, 8)][:n_color]:
                return color_mode
        off += 4
    return None


def _shape_vertex_color_modes(cg, n_shapes):
    """[mode | None] per shape index via GfxMesh (ShapeIndex@+0x18,
    MaterialIndex@+0x1C) -> material -> `_tex_env_vertex_color_mode()`."""
    mats = []  # material offsets in dict order
    for m in cg._model_offsets():
        mc, mp = cg._list_ref(m + 0xBC)
        if mp and cg.d[mp:mp + 4] == b'DICT':
            mats.extend(mo for _, mo in cg.read_dict(mp))
    by_offset = sorted(mo for mo in mats if mo)
    next_start = {mo: (by_offset[i + 1] if i + 1 < len(by_offset) else min(mo + 0x900, len(cg.d)))
                  for i, mo in enumerate(by_offset)}
    modes = [(_tex_env_vertex_color_mode(cg, mo, next_start[mo]) if mo else None) for mo in mats]
    res = [None] * n_shapes
    for m in cg._model_offsets():
        mc, ma = cg._list_ref(m + 0xB4)          # Meshes array
        if not ma or not (0 < mc <= 4096):
            continue
        for k in range(mc):
            mo = cg.ref(ma + k * 4)
            if not mo or cg.d[mo + 4:mo + 8] != b'SOBJ':
                continue
            si = cg.i32(mo + 0x18)
            mi = cg.i32(mo + 0x1C)
            if 0 <= si < n_shapes and 0 <= mi < len(modes):
                res[si] = modes[mi]
    return res


# GfxTextureCoord[3] (SPICA CtrGfx.Model.Material.GfxTextureCoord, the
# `TextureCoords` field on GfxMaterial) is a genuinely fixed-size, fixed-offset
# inline VALUE-TYPE array (unlike TextureMappers[], whose slots are
# self-relative pointers to separately-placed GfxTextureMapper objects) -
# there is no raw-command trick here like AlphaTest/CullMode, so this offset
# is derived from GfxMaterial's field layout instead: GfxObject header ends
# at +0x18 (flags/magic/rev/name/MetaData), then Flags/TexCoordConfig/
# TranslucencyKind (3x u32 = 0xC) -> Colors starts +0x24. GfxMaterialColor is
# 11 Vector4 (its `*F` backing fields, 0xB0) + 11 RGBA (4 bytes each, 0x2C) +
# CommandCache (u32) = 0xE0 -> Rasterization at +0x104. GfxRasterization is
# IsPolygonOffsetEnabled(u32)+FaceCulling(u32)+PolygonOffsetUnit(f32)+
# FaceCullingCommand(2x u32) = 0x14 -> FragmentOperation at +0x118.
# GfxFragOp = Depth(Flags u32+Commands 4xu32=0x14) + Blend(Mode u32+ColorF
# Vector4+Commands 6xu32=0x2C) + Stencil(Commands 4xu32=0x10) = 0x50 ->
# UsedTextureCoordsCount(int) at +0x168, TextureCoords[3] at +0x16C.
# Each GfxTextureCoord = SourceCoordIndex(int)+MappingType(u32)+
# ReferenceCameraIndex(int)+TransformType(u32)+Scale(Vector2)+Rotation(f32)+
# Translation(Vector2)+Flags(u32)+Transform(Matrix3x4, 12 f32) = 0x58 bytes,
# so SourceCoordIndex for TextureCoords[k] sits at +0x16C + k*0x58.
#
# Why this matters: `SourceCoordIndex` is which UV channel (0/1/2, i.e. this
# model's uv0/uv1/uv2 vertex attribute) that texture COORDINATE slot actually
# samples from - and crucially, TextureCoords[k] feeds TextureMappers[k] (the
# same stage index k), NOT necessarily uv channel k. Before this fix,
# `_shape_textures()`/model.js assumed stage k always reads uv channel k,
# which happens to be true whenever a material's SourceCoordIndex[k] == k
# (the common case - confirmed correct for e.g. FaceMaterial's kao/e0/m0 and
# most single-texture materials) but is WRONG whenever it isn't.
#
# Found investigating CHARACTER/p0006_j09's reported "服(clothes)がおかしい,
# p0006_j09huku が読まれるべき" (see docs/bcmdl_model_viewer.md, 2026-09-21
# "TextureCoordのSourceCoordIndexを読む修正"): its `huku`/`hukuyomen`/`body`/
# `acse` materials all have SourceCoordIndex[0] == 1, meaning their PRIMARY
# texture (stage 0 - `p0006_j09huku` itself, exactly the texture the user
# named) must be sampled with uv1, not uv0. uv0 for that shape is a nearly
# degenerate sliver (v spans just 0..0.089 - less than 9% of the texture's
# height), so the old stage-index assumption sampled the base texture from a
# ~9%-tall strip instead of its real, fully-unwrapped UV island in uv1 -
# reading a real texture, just through the wrong UV channel, which looked
# like a smeared/wrong-colored garment. Sampled 474 (material, stage) triples
# across 40 random files: every SourceCoordIndex decoded to a sane 0/1/2, and
# stage0 (the base texture actually always rendered) disagreed with the
# naive "uv{stage}" assumption in 12 of ~158 materials (~7.6%) - a real,
# non-rare class of bug, not a one-off.
_TEXCOORD0_OFF = 0x16C
_TEXCOORD_STRIDE = 0x58


def _tex_coord_indices(cg, mo):
    """[SourceCoordIndex for TextureCoords[0], [1], [2]] (each 0/1/2 - which
    uv attribute that texture stage actually samples), read directly at their
    fixed GfxMaterial offsets (see comment above)."""
    d = cg.d
    out = []
    for k in range(3):
        off = mo + _TEXCOORD0_OFF + k * _TEXCOORD_STRIDE
        if off + 4 > len(d):
            out.append(0)
            continue
        val = struct.unpack_from('<i', d, off)[0]
        out.append(val if val in (0, 1, 2) else 0)
    return out


def _materials(cg, ext_tex_names=None):
    """Ordered [(material_name, [texture_name, ...], alphaTest, side,
    coordIdx, mapperRoles), ...] from the MODEL's Materials dict (model+0xBC
    count / +0xC0 ref -> DICT of MTOB). The per-material texture-name strings
    sit at fixed MTOB offsets
    (+0x33c is the primary/diffuse mapper, +0x3c8 / +0x454 the next ones), so
    we scan the record for pointers to known texture names, lowest offset
    first. `alphaTest`/`side`/`mapperRoles` (see `_alpha_test()`/
    `_cull_mode()`/`_tex_env_mapper_roles()`) are looked up in the byte range
    up to the next material's start (materials are laid out back-to-back in
    file order; MTOB records are variable-sized so a fixed offset doesn't
    work).

    `ext_tex_names`: texture names that live OUTSIDE this CGFX. Map parts
    (MAP/MAPDATA/*.pack.lz FldData, see mappack.py) carry no Textures dict of
    their own - each material's mapper points at an inline
    GfxTextureReference (TXOB, TypeChoice 0x20000004) whose `Path` (+0x18)
    names a texture in the map pack's shared texture CGFX. The scan below
    already reaches that Path pointer (the reference TXOB sits inside the
    MTOB record), it just needs to know the external names are valid."""
    tex_names = {t['name'] for t in cg.textures()}
    if ext_tex_names:
        tex_names |= set(ext_tex_names)
    entries = []  # (mo, mname)
    for m in cg._model_offsets():
        mc, mp = cg._list_ref(m + 0xBC)
        if not mp or cg.d[mp:mp + 4] != b'DICT':
            continue
        for mname, mo in cg.read_dict(mp):
            entries.append((mo, mname))
    by_offset = sorted((e for e in entries if e[0]), key=lambda e: e[0])
    # the last material has no successor: scan at most 0x900 bytes, but never
    # past the end of the buffer (small CGFX - e.g. a map part with a single
    # material near the end of the file - used to raise struct.error here)
    next_start = {mo: (by_offset[i + 1][0] if i + 1 < len(by_offset) else min(mo + 0x900, len(cg.d)))
                  for i, (mo, _) in enumerate(by_offset)}
    out = []
    for mo, mname in entries:
        names = []
        alpha = None
        side = None
        coord_idx = [0, 1, 2]
        roles = {}
        if mo:
            for j in range(0x10, 0x600, 4):
                p = cg.ref(mo + j)
                s = cg.cstr(p) if p else ''
                if s in tex_names and s not in names:
                    names.append(s)
            end = next_start[mo]
            alpha = _alpha_test(cg, mo, end)
            side = _cull_mode(cg, mo, end)
            coord_idx = _tex_coord_indices(cg, mo)
            roles = _tex_env_mapper_roles(cg, mo, end)
        out.append((mname, names, alpha, side, coord_idx, roles))
    return out


def _shape_textures(cg, n_shapes, ext_tex_names=None):
    """([[texture_name, ...] | None], [alphaTest | None], [side | None],
    [[uvChannel, ...] | None], [[blendMode, ...] | None]) per shape index,
    resolved through GfxMesh (ShapeIndex@+0x18, MaterialIndex@+0x1C) ->
    material -> textures/alphaTest/side/coordIdx/blendMode. The texture list
    is every texture stage of the material (base + secondary combiner
    stages); `uvChannel[i]` (0/1/2, see `_tex_coord_indices()`) is the uv
    attribute stage i actually samples - NOT necessarily uv{i}.
    `blendMode[i]` is 'base' for stage 0, else 'blend'/'multiply'/'add'/
    'unused' from `_tex_env_mapper_roles()` (missing role -> 'unused': the
    combiner never samples this stage, so it must not be drawn at all)."""
    mats = _materials(cg, ext_tex_names)
    tex_res = [None] * n_shapes
    alpha_res = [None] * n_shapes
    side_res = [None] * n_shapes
    coord_res = [None] * n_shapes
    blend_res = [None] * n_shapes
    for m in cg._model_offsets():
        mc, ma = cg._list_ref(m + 0xB4)          # Meshes array
        if not ma or not (0 < mc <= 4096):
            continue
        for k in range(mc):
            mo = cg.ref(ma + k * 4)
            if not mo or cg.d[mo + 4:mo + 8] != b'SOBJ':
                continue
            si = cg.i32(mo + 0x18)
            mi = cg.i32(mo + 0x1C)
            if 0 <= si < n_shapes and 0 <= mi < len(mats):
                textures, roles = mats[mi][1], mats[mi][5]
                if textures:
                    tex_res[si] = list(textures)
                    coord_res[si] = list(mats[mi][4][:len(textures)])
                    blend_res[si] = ['base' if i == 0 else roles.get(i, 'unused')
                                      for i in range(len(textures))]
                alpha_res[si] = mats[mi][2]
                side_res[si] = mats[mi][3]
    return tex_res, alpha_res, side_res, coord_res, blend_res


_CGFX_CACHE = collections.OrderedDict()   # (path, mtime_ns, size) -> Cgfx
_CGFX_CACHE_MAX = 6


def get_cgfx(path):
    """Cgfx(path), cached per (path, mtime, size). Loading a .bcmdl.lz means
    decompressing it; the texture endpoint asks for one texture at a time
    (~8 requests/model) and each was re-decompressing + re-parsing."""
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return Cgfx(load_bcmdl_bytes(path))
    cg = _CGFX_CACHE.get(key)
    if cg is None:
        cg = Cgfx(load_bcmdl_bytes(path))
        _CGFX_CACHE[key] = cg
        _CGFX_CACHE.move_to_end(key)
        while len(_CGFX_CACHE) > _CGFX_CACHE_MAX:
            _CGFX_CACHE.popitem(last=False)
    else:
        _CGFX_CACHE.move_to_end(key)
    return cg


def _base_texture_mostly_holes(cg, uvs, texname, _cache, threshold=0.6):
    """FALLBACK ONLY (used when `_alpha_test()` can't find the material's real
    GfxAlphaTest command pair, e.g. an unexpected CGFX revision): true if
    sampling `texname`'s alpha channel at this shape's OWN uv coordinates
    lands on near-zero alpha for more than `threshold` of its vertices.

    This is a UV-sampling heuristic superseded by reading the material's
    actual AlphaTest.Enabled flag (see `_alpha_test()` / read_model()) - kept
    only as a safety net. It was originally the primary (and wrong) fix for
    CHARACTER/p0001_j06's torso rendering invisible: some materials' primary
    (stage 0) texture is a shared atlas where a shape's UV island legitimately
    covers a big chunk of otherwise-unused atlas space that the original
    artist filled with a flat near-black, alpha=0 placeholder (confirmed by
    dumping raw texel bytes: the "empty" region decodes to a few repeating
    constant values, not corrupt data). For a normal cutout part (hair strand
    edges, a handful of rivet holes) only a small fraction of vertices ever
    land on such texels. When most of a shape's own vertices do, alpha
    clearly isn't meant as a live transparency channel for THIS shape.
    Confirmed on CHARACTER/p0001_j06's main body shape ("fuku"): the torso
    was ~83% covered by such texels and rendered almost entirely invisible.
    See docs/bcmdl_model_viewer.md. `uvs` must already be the UV set this
    texture stage actually samples (see `_tex_coord_indices()`) - NOT
    necessarily `sh['uvs']` (uv0)."""
    if not uvs:
        return False
    if texname not in _cache:
        tex = next((t for t in cg.textures() if t['name'] == texname and t.get('ok')), None)
        _cache[texname] = None if not tex else (
            ctr_texture.decode(tex['_raw'], tex['width'], tex['height'], tex['format_id']),
            tex['width'], tex['height'])
    cached = _cache[texname]
    if not cached:
        return False
    rgba, w, h = cached
    n = len(uvs) // 2
    if not n:
        return False
    low = 0
    for k in range(n):
        u, v = uvs[k * 2], uvs[k * 2 + 1]
        x = int(u * w) % w
        y = int((1 - v) * h) % h
        if rgba[(y * w + x) * 4 + 3] < 64:
            low += 1
    return (low / n) > threshold


def attach_shape_materials(cg, geo, ext_tex_names=None, tex_cg=None):
    """Annotate each shape dict of `geo` (cg.geometry()) in place with its
    material's textures/textureBlend/side/textureUV/alphaTest, all read from
    the model's structures (see the per-field comments below).
    `ext_tex_names`/`tex_cg`: for CGFX whose textures live in ANOTHER CGFX
    (map parts - see `_materials()` and mappack.py); `tex_cg` is the CGFX
    that actually holds those textures (only used by the opaqueBase fallback)."""
    shp_tex, shp_alpha, shp_side, shp_coord, shp_blend = _shape_textures(cg, len(geo['shapes']), ext_tex_names)
    holes_cache = {}
    # vertexColor: how the per-vertex `colors` enter the pixel color, read
    # from the material's TexEnv (`_tex_env_vertex_color_mode()`); only
    # attached when the shape actually has a color attribute.
    for sh, vc in zip(geo['shapes'], _shape_vertex_color_modes(cg, len(geo['shapes']))):
        if vc and sh.get('colors'):
            sh['vertexColor'] = vc
    for sh, tn, at, side, coord, blend in zip(geo['shapes'], shp_tex, shp_alpha, shp_side, shp_coord, shp_blend):
        if tn:
            sh['textures'] = tn
            sh['texture'] = tn[0]          # back-compat: primary stage
            # textureBlend[i]: 'base' (stage 0) | 'blend' | 'multiply' |
            # 'add' | 'unused' - decoded from the material's real TexEnv
            # combiner (_tex_env_mapper_roles()). 'unused' means no combiner
            # stage samples this texture at all (most likely a normal/
            # shading map input to a separate compiled shader we don't
            # emulate) - the caller must not render it as an overlay.
            if blend is not None:
                sh['textureBlend'] = blend
            if side is not None:
                sh['side'] = side          # 'front' | 'back' | 'double', see _cull_mode()
            # uvChannel[i] (0/1/2) is which of sh['uvs']/['uvs1']/['uvs2']
            # texture stage i actually samples - see _tex_coord_indices().
            # NOT necessarily uv{i}: e.g. a material's primary (stage 0)
            # texture can sample uv1 while stage 1 samples uv0.
            if coord is not None:
                sh['textureUV'] = coord
            base_uv_key = ('uvs', 'uvs1', 'uvs2')[coord[0]] if coord else 'uvs'
            base_uvs = sh.get(base_uv_key)
            if at is not None:
                sh['alphaTest'] = at
            elif sh.get('ok') and _base_texture_mostly_holes(tex_cg or cg, base_uvs, tn[0], holes_cache):
                # fallback heuristic only reached when the material's real
                # GfxAlphaTest command pair couldn't be located - see
                # _alpha_test()/_base_texture_mostly_holes().
                sh['opaqueBase'] = True


def read_model(path):
    """High-level: path -> {structure, geometry, textures, materials}.

    A `.pack.lz` file holds only a `SkeletalAnims` dict (no `Models`/
    `Textures`) - the actual geometry+textures live in the sibling
    `.bcmdl.lz` (verified across CHARACTER/MONSTER/BATTLE; see
    docs/bcmdl_model_viewer.md). If called with a `.pack.lz` path,
    transparently redirect to that sibling so the viewer shows a real
    model regardless of which file the user picked from the list
    (previously this silently returned empty geometry/textures)."""
    if path.endswith('.pack.lz'):
        sibling = path[:-len('.pack.lz')] + '.bcmdl.lz'
        if os.path.isfile(sibling):
            path = sibling
    cg = get_cgfx(path)
    texs = [{k: v for k, v in t.items() if not k.startswith('_')}
            for t in cg.textures()]
    geo = cg.geometry()
    attach_shape_materials(cg, geo)
    return {
        'structure': cg.structure(),
        'geometry': geo,
        'textures': texs,
        'materials': [{'name': n, 'textures': t, 'alphaTest': at, 'side': side, 'coordIdx': coord,
                       'textureBlend': ['base' if i == 0 else roles.get(i, 'unused') for i in range(len(t))]}
                      for n, t, at, side, coord, roles in _materials(cg)],
        'skeleton': cg.skeleton_bones(),
        'anims': _sibling_anim_names(path),
        'animList': list_animations(path),
    }


def _anim_pack_path(path):
    """The .pack.lz next to a .bcmdl.lz holds the skeletal animations (CANM
    entries in its SkeletalAnims dict), or None if there isn't one."""
    if not path.endswith('.bcmdl.lz'):
        return None
    pack = path[:-len('.bcmdl.lz')] + '.pack.lz'
    return pack if os.path.isfile(pack) else None


def _sibling_anim_names(path):
    """Names of the .pack.lz's SkeletalAnims clips (for the info panel)."""
    pack = _anim_pack_path(path)
    if not pack:
        return []
    try:
        cg = get_cgfx(pack)
        return [n for n, _ in cg.data_dicts().get('SkeletalAnims', [])]
    except Exception:
        return []


def list_animations(path):
    """[{name, frames}, ...] for the .pack.lz's SkeletalAnims clips, for the
    viewer's animation dropdown (frame count so it can show clip length
    without a second round trip)."""
    pack = _anim_pack_path(path)
    if not pack:
        return []
    try:
        cg = get_cgfx(pack)
        return [{'name': n, 'frames': cg.f32(off + 0x14)}
                for n, off in cg.data_dicts().get('SkeletalAnims', []) if off]
    except Exception:
        return []


# ---- CANM (skeletal animation) sample-track scan ---------------------------
#
# See docs/canm_skeletal_animation_investigation.md for the full derivation.
# Summary: a CANM clip's `SkeletalAnims` entry has a nested DICT at +0x28
# keyed by bone name -> per-bone "AnimBoneTransform" blob. That blob's exact
# field layout (which of Scale/Rotation/Translation are constant vs. sampled,
# and the various small integer/flag fields around them) is NOT fully
# decoded. What IS confirmed: every *sampled* track (as opposed to a bone
# whose transform is constant for the whole clip) is preceded by a 16-byte
# header `[u32 0, f32 frameCount, u32 0, u32 0]` where frameCount matches the
# clip's own +0x14 field, and is immediately followed by tightly packed
# per-frame samples with no padding between the header and frame 0 or
# between frames - so we scan for that header signature rather than trying
# to compute offsets from the (still unclear) surrounding flag fields. Two
# sample shapes are seen: 20 bytes/frame = quaternion (x,y,z,w) with a
# trailing zero pad -> rotation; 16 bytes/frame = (x,y,z) with a trailing
# zero pad -> translation. (Scale tracks were not observed to be sampled in
# the clips checked so far - bones only ever showed 0, 1 (rotation), or 2
# (rotation+translation) sampled tracks; scale is presumably always constant
# and stays undecoded, so animated playback keeps the bind-pose scale.)
# Sample count is frameCount+1 (a closing frame equal to frame 0, for a
# seamless loop) with sometimes one extra duplicate frame of padding after
# that - we only use frameCount+1 samples and ignore anything past that.

def _canm_find_tracks(cg, start, end, frames):
    """[(bone-relative header offset, is_constant), ...] of every
    sample-track header in [start, end) - i.e. every occurrence of the
    `[0, frames, 0, IsConstant]` 16-byte signature (StartFrame=0,
    EndFrame=frames, CurveRelPtr=0 - unused/not followed, see the module
    docstring above - IsConstant=0 or 1), non-overlapping.

    FALLBACK ONLY as of the direct-pointer decode below
    (`_canm_quat_transform_headers`) - kept for any bone entry whose
    PrimitiveType isn't one of the two known values (5 or 8), which has
    never actually been observed. Originally this WAS the primary
    PrimitiveType==8 decode path, but it has a real flaw a raw byte scan
    can't avoid: when a clip's frame count is exactly 0.0 (a single held
    pose, e.g. p0492_idle), "header ~= [0, frames=0.0, 0, 0/1]" matches
    almost any all-zero padding bytes too (since frames=0.0 IS near-zero),
    so the scan can latch onto padding before ever reaching the real
    header - which is what made p0492_idle's fixed pose never display.
    See docs/canm_skeletal_animation_investigation.md."""
    out = []
    p = start
    while p + 16 <= end:
        if (cg.u32(p) == 0 and abs(cg.f32(p + 4) - frames) < 1e-3
                and cg.u32(p + 8) == 0 and cg.u32(p + 12) in (0, 1)):
            out.append((p, cg.u32(p + 12) == 1))
            p += 16
        else:
            p += 4
    return out


def _canm_quat_transform_headers(cg, bo):
    """[(channel_header_offset, is_constant), ...] for a
    GfxAnimQuatTransform bone entry (PrimitiveType==8), read directly from
    the structure instead of scanning for a byte-shape signature: the
    bone's Flags word (bo+0x00, GfxAnimQuatTransformFlags) says which of
    Rotation/Translation/Scale exist at all (Inexistent bits 4/3/5), and
    the 3 self-rel pointers at bo+0x0c/+0x10/+0x14 - in that literal file
    order, Rotation/Translation/Scale - each point at one channel's own
    16-byte header (see _canm_decode_track). This is what
    `_canm_find_tracks` above used to approximate by scanning; the direct
    read has none of its failure modes (spurious zero-padding matches,
    ambiguous "which header comes first" ordering) because there is
    nothing to guess - every offset here is a real, typed field."""
    flags = cg.u32(bo)
    out = []
    for slot_off, inexistent_bit in ((0x0c, 1 << 4), (0x10, 1 << 3), (0x14, 1 << 5)):
        if flags & inexistent_bit:
            continue
        L = cg.ref(bo + slot_off)
        if not L:
            continue
        out.append((L, cg.u32(L + 0x0c) != 0))
    return out


def _canm_decode_track(cg, hdr, is_constant, limit, nsamples):
    """Try to decode the sample array right after a track header at `hdr`
    (data starts at hdr+16, bounded by `limit`) as either a quaternion
    rotation track or a Vector3 translation track. Returns
    ('rotation'|'translation'|None, [[...], ...] or None) - the returned
    list always has exactly `nsamples` entries: for a constant channel
    (`is_constant`), the single real sample in the file is repeated
    `nsamples` times so callers don't need a separate "this track never
    changes" case."""
    data = hdr + 16
    avail = limit - data
    want = 1 if is_constant else nsamples
    n20 = min(avail // 20, want)
    if n20 > 0:
        ok = True
        samples = []
        for i in range(n20):
            o = data + i * 20
            qx, qy, qz, qw, pad = struct.unpack_from('<5f', cg.d, o)
            norm = (qx * qx + qy * qy + qz * qz + qw * qw) ** 0.5
            if abs(pad) > 1e-6 or abs(norm - 1.0) > 0.02:
                ok = False
                break
            samples.append([qx, qy, qz, qw])
        if ok:
            if is_constant:
                samples = samples * nsamples
            return 'rotation', samples
    n16 = min(avail // 16, want)
    if n16 > 0:
        ok = True
        samples = []
        for i in range(n16):
            o = data + i * 16
            x, y, z, pad = struct.unpack_from('<4f', cg.d, o)
            if abs(pad) > 1e-6:
                ok = False
                break
            samples.append([x, y, z])
        if ok:
            if is_constant:
                samples = samples * nsamples
            # A 16-byte-per-frame track whose (x,y,z) sits near (1,1,1) on
            # every single sample is a Scale track, not Translation - real
            # bone translations in this skeleton's local space are all well
            # under 1.0 in magnitude (see docs/canm_skeletal_animation_
            # investigation.md), so (1,1,1) can never be a genuine position.
            # p0053's clips (e.g. p0053_wait) contain many of these; without
            # this check they were misread as huge (1,1,1) position offsets,
            # visibly tearing the skeleton apart during playback.
            if all(abs(x - 1.0) < 0.3 and abs(y - 1.0) < 0.3 and abs(z - 1.0) < 0.3
                   for x, y, z in samples):
                return 'scale', samples
            return 'translation', samples
    return None, None


# ---- GfxAnimTransform (Euler + Hermite/StepLinear compressed curves) ------
#
# Some clips (e.g. p0051_idle/_dash/_wait - reported as "won't play") encode
# their per-bone transform as CtrGfx's `GfxAnimTransform` (PrimitiveType==5:
# 9 independently-keyed Euler-angle/translation float curves) instead of the
# simpler `GfxAnimQuatTransform` (PrimitiveType==8: one packed per-frame
# quaternion+vec3 sample array) that `_canm_find_tracks`/`_canm_decode_track`
# above were built for. The byte-signature scan those use never matches
# PrimitiveType==5 data (it's genuinely a different, compressed encoding -
# sparse Hermite keyframes, not one sample per frame), so those bones
# silently decoded to 0 tracks. This isn't a bug in the scanner; it's a
# format the old code never attempted, exactly as flagged as future work in
# docs/canm_skeletal_animation_investigation.md.
#
# Derived by fetching gdkchan/SPICA (the reference CTR/CGFX decoder this
# project's CLAUDE.md points to) - `SPICA/Formats/CtrGfx/Animation/
# GfxAnimTransform.cs`, `GfxFloatKeyFrameGroup.cs`, `GfxAnimTransformFlags.cs`,
# `SPICA/Formats/Common/KeyFrameQuantization*.cs`, and the evaluator in
# `SPICA.Rendering/Animation/SkeletalAnimation.cs` (`H3DFloatKeyFrameGroup.
# GetFrameValue()` + `Interpolation.Herp()` + `Bone.CalculateQuaternion()`) -
# then confirmed byte-for-byte against p0051.pack.lz's `p0051_idle` clip (see
# docs/canm_skeletal_animation_investigation.md for the verification dump).
#
# Per-bone entry layout (bone_off = `bo` from read_dict(off+0x28), same
# entry read_animation() already uses for the QuatTransform scan):
#   +0x00  u32 Flags   - GfxAnimQuatTransformFlags (PrimitiveType 8) or
#                         GfxAnimTransformFlags (PrimitiveType 5); which bits
#                         mean what depends on PrimitiveType, see below
#   +0x08  u32 PrimitiveType (5 = Transform/Euler, 8 = QuatTransform)
#   +0x0c  content - for PrimitiveType 5, 10 consecutive 4-byte slots
#          (ScaleX/Y/Z, RotationX/Y/Z, <unused>, TranslationX/Y/Z - index 6
#          is a reserved/skipped slot per GfxAnimTransform.cs, always present
#          as a 4-byte gap in the file but never assigned to a channel)
#
# GfxAnimTransformFlags bit layout (from GfxAnimTransformFlags.cs), 2 bits
# per channel starting at bit 6: bit (6+i)=IsConstant, bit (16+i)=Inexistent,
# for i in 0..8 over [ScaleX,ScaleY,ScaleZ,RotX,RotY,RotZ,RotW(unused),
# TransX,TransY,TransZ]. A channel entirely absent from the clip has its
# Inexistent bit set and its slot is 0/unused. A channel with only ONE value
# for the whole clip has its Constant bit set and its slot IS the value
# itself (an inline float, not a pointer). Otherwise the slot is a self-rel
# pointer to a `GfxFloatKeyFrameGroup`.
#
# `GfxFloatKeyFrameGroup` (at the resolved slot pointer, call it L):
#   +0x00 float StartFrame  +0x04 float EndFrame
#   +0x08 u8 PreRepeat  +0x09 u8 PostRepeat  +0x0a u16 Padding
#   +0x0c u32 CurveFlags (bit1=IsConstantValue, bit2=IsQuantizedCurve)
#   +0x10 if IsConstantValue: float Value (done, no curve)
#         else: i32 CurveCount, then a self-rel pointer (at +0x14) to the
#         actual curve descriptor (call it L2)
# `L2` (the curve descriptor):
#   +0x00 float StartFrame  +0x04 float EndFrame  +0x08 u32 FormatFlags
#   +0x0c i32 KeysCount     +0x10 float InvDuration
#   Quantization = FormatFlags >> 5 (see KeyFrameQuantization enum below)
#   +0x14: ValueScale/ValueOffset/FrameScale (3 floats), OMITTED entirely
#          for Quantization in {Hermite128, UnifiedHermite96, StepLinear64}
#          (those already store frame/value as plain floats, so scale=1/
#          offset=0/frameScale=1 and the fields are simply not in the file)
#   then KeysCount keyframes, tightly packed, each quantization-specific size
#
# Only KeyFrameQuantization.Hermite128 (enum 0, the simplest/least-quantized
# form: frame/value/inSlope/outSlope all plain float32) has actually been
# observed in this ROM's clips so far (verified against p0051_idle's
# Center bone TranslationY/Z curves). The other 7 packed forms are
# implemented from the reference for completeness/robustness but are
# UNTESTED against real DQ7 data - if a clip's `p` advances past its
# curve's byte range (garbage keys, exception, or visibly wrong motion),
# suspect a wrong quantization decode here first.
_GFX_TRANSFORM_CHANNELS = [
    # (constant_bit, inexistent_bit, slot_index) - order matches
    # GfxAnimTransformFlags.cs: Scale X/Y/Z, Rotation X/Y/Z, <gap>,
    # Translation X/Y/Z. Scale is intentionally not decoded here (see
    # 'rotation'/'translation' below) - character clips essentially never
    # animate bone scale, and misreading one as a real channel is exactly
    # the kind of "1,1,1 constant scale mistaken for a real value" bug this
    # module already had to fix once for p0053 (see git history) - so we'd
    # rather silently ignore a hypothetical scale curve than risk decoding
    # it wrong.
    None, None, None,
    (1 << 9, 1 << 19, 3), (1 << 10, 1 << 20, 4), (1 << 11, 1 << 21, 5),
    None,
    (1 << 13, 1 << 23, 7), (1 << 14, 1 << 24, 8), (1 << 15, 1 << 25, 9),
]
_GFX_ROTATION_AXES = (3, 4, 5)
_GFX_TRANSLATION_AXES = (7, 8, 9)


def _sext(v, bits):
    m = 1 << (bits - 1)
    return (v ^ m) - m


def _gfx_read_keyframe(cg, quant, p):
    """(frame, value, inSlope, outSlope, bytesConsumed) for one keyframe of
    the given KeyFrameQuantization at absolute offset `p` - direct port of
    SPICA's KeyFrameQuantizationHelper.Read*() functions."""
    if quant == 0:      # Hermite128
        frame, value, ins, outs = struct.unpack_from('<4f', cg.d, p)
        return frame, value, ins, outs, 16
    if quant == 1:      # Hermite64
        frameval = cg.u32(p)
        ins, outs = struct.unpack_from('<2h', cg.d, p + 4)
        frame = frameval & 0xfff
        value = (frameval >> 12) & 0xfffff
        return frame, value, ins / 256.0, outs / 256.0, 8
    if quant == 2:      # Hermite48
        frame = cg.u8(p)
        value = cg.u16(p + 1)
        b = cg.d[p + 3:p + 6]
        slopes = b[0] | (b[1] << 8) | (b[2] << 16)
        ins = _sext(slopes & 0xfff, 12)
        outs = _sext((slopes >> 12) & 0xfff, 12)
        return frame, value, ins / 32.0, outs / 32.0, 6
    if quant == 3:      # UnifiedHermite96
        frame, value, ins = struct.unpack_from('<3f', cg.d, p)
        return frame, value, ins, ins, 12
    if quant == 4:      # UnifiedHermite48
        frame_raw = cg.u16(p)
        value = cg.u16(p + 2)
        ins_raw = struct.unpack_from('<h', cg.d, p + 4)[0]
        return frame_raw / 32.0, value, ins_raw / 256.0, ins_raw / 256.0, 6
    if quant == 5:      # UnifiedHermite32
        frame = cg.u8(p)
        b = cg.d[p + 1:p + 4]
        valslope = b[0] | (b[1] << 8) | (b[2] << 16)
        value = valslope & 0xfff
        slope = _sext((valslope >> 12) & 0xfff, 12) / 32.0
        return frame, value, slope, slope, 4
    if quant == 6:      # StepLinear64
        frame, value = struct.unpack_from('<2f', cg.d, p)
        return frame, value, 0.0, 0.0, 8
    if quant == 7:      # StepLinear32
        frameval = cg.u32(p)
        return frameval & 0xfff, (frameval >> 12) & 0xfffff, 0.0, 0.0, 4
    raise ValueError(f'unknown KeyFrameQuantization {quant}')


def _gfx_float_keyframe_group(cg, slot_pos, constant):
    """[(frame, value, inSlope, outSlope), ...] for one GfxAnimTransform
    channel slot at `slot_pos` (see layout notes above). `constant` comes
    from the bone's top-level Flags word. Empty list if the pointer is null/
    out of range (treated as "no curve", channel falls back to 0.0 - see
    _gfx_eval_axis)."""
    if constant:
        return [(0.0, cg.f32(slot_pos), 0.0, 0.0)]
    L = cg.ref(slot_pos)
    if not L:
        return []
    curve_flags = cg.u32(L + 0x0c)
    if curve_flags & 2:               # IsConstantValue
        return [(0.0, cg.f32(L + 0x10), 0.0, 0.0)]
    L2 = cg.ref(L + 0x14)
    if not L2:
        return []
    format_flags = cg.u32(L2 + 0x08)
    keys_count = cg.i32(L2 + 0x0c)
    quant = format_flags >> 5
    p = L2 + 0x14
    if quant not in (0, 3, 6):         # Hermite128/UnifiedHermite96/StepLinear64 store plain floats
        value_scale, value_offset, frame_scale = struct.unpack_from('<3f', cg.d, p)
        p += 12
    else:
        value_scale, value_offset, frame_scale = 1.0, 0.0, 1.0
    keys = []
    for _ in range(max(0, keys_count)):
        frame, value, ins, outs, size = _gfx_read_keyframe(cg, quant, p)
        keys.append((frame * frame_scale, value * value_scale + value_offset, ins, outs))
        p += size
    return keys


def _gfx_herp(lhs, rhs, ls, rs, diff, weight):
    """SPICA.Math3D.Interpolation.Herp() - cubic Hermite spline segment."""
    result = lhs + (lhs - rhs) * (2 * weight - 3) * weight * weight
    result += (diff * (weight - 1)) * (ls * (weight - 1) + rs * weight)
    return result


def _gfx_eval_axis(keys, frame):
    """H3DFloatKeyFrameGroup.GetFrameValue() - evaluate one Euler/position
    axis's keyframe list at a (possibly fractional) frame number. Missing
    axis (no keys at all - inexistent channel) evaluates to 0.0."""
    if not keys:
        return 0.0
    if len(keys) == 1:
        return keys[0][1]
    lhs, rhs = keys[0], keys[-1]
    for kf in keys:
        if kf[0] <= frame:
            lhs = kf
        if kf[0] >= frame and kf[0] < rhs[0]:
            rhs = kf
    if lhs[0] == rhs[0]:
        return lhs[1]
    frame_diff = frame - lhs[0]
    weight = frame_diff / (rhs[0] - lhs[0])
    return _gfx_herp(lhs[1], rhs[1], lhs[3], rhs[2], frame_diff, weight)


def _gfx_euler_to_quat(ex, ey, ez):
    """SkeletalAnimation.Bone.CalculateQuaternion() - DQ7/SPICA's specific
    (non-standard-library) Euler->quaternion composition; must match this
    exactly, not a generic XYZ/ZYX convention, or bones rotate wrong."""
    sx, sy, sz = math.sin(ex * 0.5), math.sin(ey * 0.5), math.sin(ez * 0.5)
    cx, cy, cz = math.cos(ex * 0.5), math.cos(ey * 0.5), math.cos(ez * 0.5)
    x = cz * sx * cy - sz * cx * sy
    y = cz * cx * sy + sz * sx * cy
    z = sz * cx * cy - cz * sx * sy
    w = cz * cx * cy + sz * sx * sy
    return [x, y, z, w]


def _gfx_transform_bone_tracks(cg, bo, nsamples):
    """{'rotation': [[x,y,z,w],...], 'translation': [[x,y,z],...]} baked at
    integer frames 0..nsamples-1 for one PrimitiveType==5 (GfxAnimTransform)
    bone entry at `bo`. Scale is intentionally not decoded (see
    _GFX_TRANSFORM_CHANNELS). Whichever of rotation/translation has every
    axis Inexistent is omitted (bone keeps its bind pose for that channel,
    same convention as the QuatTransform path)."""
    flags = cg.u32(bo)
    axes_cache = {}

    def axis_keys(idx):
        if idx not in axes_cache:
            cbit, ibit, slot = _GFX_TRANSFORM_CHANNELS[idx]
            if flags & ibit:
                axes_cache[idx] = None
            else:
                axes_cache[idx] = _gfx_float_keyframe_group(
                    cg, bo + 0x0c + 4 * slot, bool(flags & cbit))
        return axes_cache[idx]

    tracks = {}
    if any(not (flags & _GFX_TRANSFORM_CHANNELS[i][1]) for i in _GFX_ROTATION_AXES):
        rx, ry, rz = (axis_keys(i) for i in _GFX_ROTATION_AXES)
        tracks['rotation'] = [
            _gfx_euler_to_quat(_gfx_eval_axis(rx, f), _gfx_eval_axis(ry, f), _gfx_eval_axis(rz, f))
            for f in range(nsamples)
        ]
    if any(not (flags & _GFX_TRANSFORM_CHANNELS[i][1]) for i in _GFX_TRANSLATION_AXES):
        tx, ty, tz = (axis_keys(i) for i in _GFX_TRANSLATION_AXES)
        tracks['translation'] = [
            [_gfx_eval_axis(tx, f), _gfx_eval_axis(ty, f), _gfx_eval_axis(tz, f)]
            for f in range(nsamples)
        ]
    return tracks


def read_animation(bcmdl_path, clip_name):
    """{name, frames, tracks: {bone_name: {rotation: [[x,y,z,w],...]}
    and/or {translation: [[x,y,z],...]} and/or {scale: [[x,y,z],...]}}} for
    one SkeletalAnims clip in the .pack.lz next to `bcmdl_path`. Bones not in
    `tracks` (or missing a rotation/translation key) keep their bind pose for
    that channel - most bones in a clip are static; see the module docstring
    above the scan helpers. `scale` tracks are decoded but intentionally not
    applied by the viewer (see _canm_decode_track) - they're kept in the
    result only so callers can tell a bone had one, not to be rendered as a
    position. Raises KeyError if the clip isn't found."""
    pack = _anim_pack_path(bcmdl_path)
    if not pack:
        raise KeyError(clip_name)
    cg = get_cgfx(pack)
    anims = dict(cg.data_dicts().get('SkeletalAnims', []))
    off = anims.get(clip_name)
    if not off:
        raise KeyError(clip_name)
    frames = cg.f32(off + 0x14)
    nsamples = int(round(frames)) + 1
    bones = sorted(cg.read_dict(off + 0x28), key=lambda kv: kv[1])
    tracks = {}
    for i, (bname, bo) in enumerate(bones):
        # The last bone in a clip has no next-bone offset to bound its scan
        # range, so it fell back to a fixed +0x600 guess - which, for a
        # small pack.lz where the last bone's real data block is smaller
        # than that, reads past EOF and crashes (struct.error). Found via
        # an exhaustive scan of every CHARACTER clip while investigating
        # p0051 (see docs/canm_skeletal_animation_investigation.md) -
        # affected ~240 clips across many characters, unrelated to the
        # GfxAnimTransform work below. Clamp to the actual buffer length.
        end = bones[i + 1][1] if i + 1 < len(bones) else min(bo + 0x600, len(cg.d))
        # +0x08 is GfxPrimitiveType (5=Transform/Euler+Hermite curves,
        # 8=QuatTransform/packed per-frame quaternion samples) - see
        # docs/canm_skeletal_animation_investigation.md and the
        # _gfx_transform_bone_tracks()/_canm_quat_transform_headers()
        # docstrings above for how these were derived from the reference
        # decoder. Only PrimitiveType 5 and 8 have been observed in DQ7's
        # clips; anything else falls back to the old raw-byte scan
        # (harmless - it'll just find 0 tracks, same as before either
        # direct-decode path existed).
        prim_type = cg.u32(bo + 8)
        if prim_type == 5:
            bone_tracks = _gfx_transform_bone_tracks(cg, bo, nsamples)
        elif prim_type == 8:
            bone_tracks = {}
            for hdr, is_constant in _canm_quat_transform_headers(cg, bo):
                kind, samples = _canm_decode_track(cg, hdr, is_constant, len(cg.d), nsamples)
                if kind:
                    bone_tracks[kind] = samples
        else:
            bone_tracks = {}
            hdrs = _canm_find_tracks(cg, bo, end, frames)
            for j, (hdr, is_constant) in enumerate(hdrs):
                limit = hdrs[j + 1][0] if j + 1 < len(hdrs) else end
                kind, samples = _canm_decode_track(cg, hdr, is_constant, limit, nsamples)
                if kind:
                    bone_tracks[kind] = samples
        if bone_tracks:
            tracks[bname] = bone_tracks
    return {'name': clip_name, 'frames': frames, 'tracks': tracks}
