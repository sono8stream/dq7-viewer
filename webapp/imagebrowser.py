"""
RomFS-wide image browser: enumerate every image-bearing file under
rom/extracted/ and decode any of them to PNG.

Image containers handled:
  *.bctex / *.bctex.lz  - CGFX with a Textures dict (single/few TXOB)
  *.bcmdl / *.bcmdl.lz   - CGFX model, textures embedded as TXOB
  *.dmp                  - standalone "DMP\\0"/"DMP\\3" texture dump
                          (8x8 swizzled, header has fmt + WxH + bufWxH)
  *.fpt                  - FPT0 archive; entries that are DMP dumps
  *.fpt.lz              - "type 0x40" LZ+Huffman-compressed FPT0 archive
                          (SCREENTEX/: job portraits, atlases, endroll...).
                          Tiled ones (texNNN.dmp grid + size.dat) are also
                          exposed as a single stitched "@assembled" image.
"""
import collections
import os
import struct
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
_ROM_DIR = os.environ.get('DQ7_ROM_DIR') or os.path.join(_ROOT, 'rom')
_ROMFS = os.path.join(_ROM_DIR, 'extracted')

import sys
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import ctr_texture  # noqa: E402
import bcmdl  # noqa: E402
from fpt_lz import decompress_fpt_lz  # noqa: E402

_CGFX_EXTS = ('.bctex.lz', '.bctex', '.bcmdl.lz', '.bcmdl')
_FPT_IMG_DIRS = ('LAYOUTTEX',)     # dirs whose .fpt archives hold .dmp textures
# dirs whose *.fpt.lz (type-0x40 compressed FPT0) archives hold .dmp textures
_FPTLZ_IMG_DIRS = ('SCREENTEX', 'LAYOUTTEX')
_ASSEMBLED = '@assembled'          # synthetic entry name for a stitched tile grid

_tree_cache = None


def _kind(name):
    if name.endswith(('.bctex.lz', '.bctex')):
        return 'bctex'
    if name.endswith(('.bcmdl.lz', '.bcmdl')):
        return 'bcmdl'
    if name.endswith('.dmp'):
        return 'dmp'
    if name.endswith('.fpt.lz'):
        return 'fptlz'
    if name.endswith('.fpt'):
        return 'fpt'
    return None


def build_tree():
    """{ 'DIR/sub': [ {name, path, kind, size}, ... ], ... }  (path is
    romfs-relative, '/'-joined)."""
    global _tree_cache
    if _tree_cache is not None:
        return _tree_cache
    groups = {}
    for root, dirs, files in os.walk(_ROMFS):
        dirs.sort()
        rel = os.path.relpath(root, _ROMFS).replace(os.sep, '/')
        if rel == '.':
            rel = ''
        for fn in sorted(files):
            k = _kind(fn)
            if not k:
                continue
            if k == 'fpt' and (rel.split('/')[0] not in _FPT_IMG_DIRS):
                continue
            if k == 'fptlz' and (rel.split('/')[0] not in _FPTLZ_IMG_DIRS):
                continue
            full = os.path.join(root, fn)
            grp = rel or '(root)'
            groups.setdefault(grp, []).append({
                'name': fn,
                'path': (rel + '/' + fn) if rel else fn,
                'kind': k,
                'size': os.path.getsize(full),
            })
    _tree_cache = groups
    return groups


def _safe_full(relpath):
    if not relpath or '..' in relpath.split('/'):
        raise ValueError('invalid path')
    full = os.path.normpath(os.path.join(_ROMFS, relpath))
    if not full.startswith(_ROMFS + os.sep):
        raise ValueError('invalid path')
    if not os.path.isfile(full):
        raise FileNotFoundError(relpath)
    return full


def _fpt_entries(data):
    """Minimal FPT0 walk -> [(name, bytes), ...]."""
    if data[:4] != b'FPT0':
        return []
    file_count = struct.unpack_from('<I', data, 8)[0]
    temp_count = struct.unpack_from('<I', data, 0xC)[0]
    entries_start = 0x10
    data_start = entries_start + file_count * 0x20 + temp_count * 0x40
    out = []
    for i in range(file_count):
        off = entries_start + i * 0x20
        if off + 0x20 > len(data):
            break
        name = data[off:off + 0x10].rstrip(b'\x00').decode('ascii', 'replace')
        msg_off = struct.unpack_from('<I', data, off + 0x14)[0]
        msg_len = struct.unpack_from('<I', data, off + 0x18)[0]
        s = data_start + msg_off
        if 0 <= msg_off and s + msg_len <= len(data):
            out.append((name, data[s:s + msg_len]))
    return out


# LZ-decompressing a .fpt.lz is ~0.8 s of pure-Python bit-twiddling, and the
# browser hits /api/img/list once + /api/img/png once *per tile* for the same
# archive (20+ requests). Cache the parsed member list keyed by (path, mtime,
# size) so an archive is decompressed at most once. Small LRU: entries hold the
# decompressed bytes, a few hundred KB each.
_ENTRIES_CACHE = collections.OrderedDict()   # sig -> [(name, bytes), ...]
_ASSEMBLED_CACHE = collections.OrderedDict()  # sig -> (png_bytes, W, H) or None
_CACHE_MAX = 12
_CACHE_LOCK = threading.Lock()


def _sig(full):
    st = os.stat(full)
    return (full, st.st_mtime_ns, st.st_size)


def _cache_get(cache, key):
    with _CACHE_LOCK:
        if key in cache:
            cache.move_to_end(key)
            return cache[key], True
    return None, False


def _cache_put(cache, key, val):
    with _CACHE_LOCK:
        cache[key] = val
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def _img_entries(full, kind):
    """Read a .fpt / .fpt.lz file -> [(name, bytes), ...] of its members.
    Result is cached per (path, mtime, size)."""
    key = _sig(full)
    hit, ok = _cache_get(_ENTRIES_CACHE, key)
    if ok:
        return hit
    with open(full, 'rb') as f:
        data = f.read()
    if kind == 'fptlz':
        data = decompress_fpt_lz(data)
    entries = _fpt_entries(data)
    _cache_put(_ENTRIES_CACHE, key, entries)
    return entries


def _assembled_cached(full, entries):
    """_assemble_tiles(entries) -> (png_bytes, W, H) or None, cached per file.
    (list_images needs W/H, image_png needs the bytes; both would otherwise
    re-decode every tile.)"""
    key = _sig(full)
    hit, ok = _cache_get(_ASSEMBLED_CACHE, key)
    if ok:
        return hit
    res = _assemble_tiles(entries)
    if res is None:
        val = None
    else:
        import io as _io
        buf = _io.BytesIO()
        res[0].save(buf, 'PNG')
        val = (buf.getvalue(), res[1], res[2])
    _cache_put(_ASSEMBLED_CACHE, key, val)
    return val


def _assemble_tiles(entries):
    """entries: [(name, bytes)]. If they look like a `texNNN.dmp` grid plus
    a `size.dat` ("W,H"), stitch them into one RGBA PIL image.
    -> (image, W, H) or None."""
    import re
    from PIL import Image
    size = None
    tiles = {}
    for name, body in entries:
        if name == 'size.dat':
            try:
                nums = body.decode('ascii', 'replace').replace('\r', ',').replace('\n', ',').split(',')
                size = (int(nums[0]), int(nums[1]))
            except (ValueError, IndexError):
                pass
            continue
        m = re.match(r'tex(\d+)\.dmp$', name)
        if not m:
            continue
        info = ctr_texture.dmp_info(body)
        if not info:
            continue
        fid, tw, th, bw, bh = info
        need = ctr_texture.min_bytes(bw, bh, fid)
        if len(body) < 0x10 + need:
            continue
        rgba = ctr_texture.decode(body[0x10:0x10 + need], bw, bh, fid)
        im = Image.frombytes('RGBA', (bw, bh), rgba)
        if (bw, bh) != (tw, th):
            im = im.crop((0, 0, tw, th))
        tiles[int(m.group(1))] = im
    if not tiles:
        return None
    tw, th = next(iter(tiles.values())).size
    if size:
        W, H = size
    else:
        n = max(tiles) + 1
        cols = max(1, int(n ** 0.5))
        W, H = cols * tw, ((n + cols - 1) // cols) * th
    cols = max(1, W // tw)
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for i, im in tiles.items():
        canvas.paste(im, ((i % cols) * tw, (i // cols) * th))
    return canvas, W, H


def list_images(relpath):
    """[{name, width, height, format}] for the image(s) in this file."""
    full = _safe_full(relpath)
    k = _kind(os.path.basename(full))
    if k in ('bctex', 'bcmdl'):
        cg = bcmdl.get_cgfx(full)
        return [{'name': t['name'], 'width': t['width'], 'height': t['height'],
                 'format': t['format'], 'ok': t['ok']}
                for t in cg.textures()]
    if k == 'dmp':
        with open(full, 'rb') as f:
            data = f.read()
        info = ctr_texture.dmp_info(data)
        if not info:
            return []
        fid, w, h, _, _ = info
        return [{'name': os.path.basename(full), 'width': w, 'height': h,
                 'format': ctr_texture.FMT_NAMES[fid] if fid < len(ctr_texture.FMT_NAMES) else '?',
                 'ok': True}]
    if k in ('fpt', 'fptlz'):
        try:
            entries = _img_entries(full, k)
        except Exception:
            return []
        out = []
        assembled = _assembled_cached(full, entries)
        if assembled is not None:
            _png, w, h = assembled
            out.append({'name': _ASSEMBLED, 'width': w, 'height': h,
                        'format': 'RGBA8 (tiled)', 'ok': True})
        for name, body in entries:
            info = ctr_texture.dmp_info(body)
            if not info:
                continue
            fid, w, h, _, _ = info
            out.append({'name': name, 'width': w, 'height': h,
                        'format': ctr_texture.FMT_NAMES[fid] if fid < len(ctr_texture.FMT_NAMES) else '?',
                        'ok': True})
        return out
    return []


def image_png(relpath, name):
    """Decode one named image within the file to PNG bytes (or None)."""
    full = _safe_full(relpath)
    k = _kind(os.path.basename(full))
    if k in ('bctex', 'bcmdl'):
        cg = bcmdl.get_cgfx(full)
        return cg.texture_png(name)
    if k == 'dmp':
        with open(full, 'rb') as f:
            return ctr_texture.dmp_to_png(f.read())
    if k in ('fpt', 'fptlz'):
        entries = _img_entries(full, k)
        if name == _ASSEMBLED:
            res = _assembled_cached(full, entries)
            return res[0] if res is not None else None
        for ename, body in entries:
            if ename == name:
                return ctr_texture.dmp_to_png(body)
    return None
