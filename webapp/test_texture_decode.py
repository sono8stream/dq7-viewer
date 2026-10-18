"""
Sanity check for webapp/ctr_texture.py channel order + bit layout.

Face / skin textures must come out warm (avg R > avg B). This is the
regression guard for the R/B swap bug in the 16-bit formats (DQ7 packs
RGB565 / RGBA5551 / RGBA4 with R in the HIGH bits, unlike SPICA's
helpers). Sea / sky map textures (ETC1) must come out cool (avg B > avg R):
guard for the ETC1 R/B swap (see ctr_texture._etc1_tile).
Run: python3 webapp/test_texture_decode.py
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import bcmdl  # noqa: E402
import ctr_texture  # noqa: E402
import mappack  # noqa: E402

_ROM_DIR = os.environ.get('DQ7_ROM_DIR') or os.path.join(_HERE, '..', 'rom')
_EXTRACTED = os.path.join(_ROM_DIR, 'extracted')

# (model, texture-name-substring, expectation)
CASES = [
    ('CHARACTER/p0003_j00.bcmdl.lz', 'kao', 'warm'),   # Keifa face (RGB565)
    ('CHARACTER/p0001_j00.bcmdl.lz', 'face', 'warm'),  # Hero face (RGBA5551)
    ('CHARACTER/p0001_j00.bcmdl.lz', 'e0', 'warm'),    # eyes (skin-ish)
]

# (map pack, exact texture name in its shared texture CGFX, expectation)
MAP_CASES = [
    ('MAP/MAPDATA/c01nout.pack.lz', 'c01umi1', 'cool'),    # sea (ETC1)
    ('MAP/MAPDATA/c01nout.pack.lz', 'x08sora01', 'cool'),  # sky backdrop (ETC1)
]


def avg_rgb(rgba, n):
    r = sum(rgba[i] for i in range(0, n * 4, 4))
    g = sum(rgba[i] for i in range(1, n * 4, 4))
    b = sum(rgba[i] for i in range(2, n * 4, 4))
    return r // n, g // n, b // n


def _check_rgba8_order():
    """RGBA8 (fmt 0) is stored little-endian ABGR -> bytes [A,B,G,R].
    Guards the R/B swap that hit SCREENTEX .fpt.lz atlases (all RGBA8)."""
    px = bytes([0x11, 0x22, 0x33, 0x44])  # A=0x11 B=0x22 G=0x33 R=0x44
    out = ctr_texture.decode(px, 1, 1, 0)
    ok = tuple(out) == (0x44, 0x33, 0x22, 0x11)
    print(f"  {'OK  ' if ok else 'FAIL'} RGBA8 byte order -> RGBA={tuple(out)} "
          f"expect (68, 51, 34, 17)")
    return 0 if ok else 1


def _check_numpy_matches_python(max_per_format=6):
    """The numpy fast path must give exactly the pure-Python decoder's bytes.
    Samples textures of every format found in some map packs and models."""
    if ctr_texture._np is None:
        print('  SKIP numpy path: numpy not installed')
        return 0
    import glob
    files = (sorted(glob.glob(os.path.join(_EXTRACTED, 'MAP', 'MAPDATA', 'wld_n0*a.pack.lz')))[:3]
             + sorted(glob.glob(os.path.join(_EXTRACTED, 'MAP', 'MAPDATA', 'c0*nout.pack.lz')))[:2]
             + sorted(glob.glob(os.path.join(_EXTRACTED, 'CHARACTER', '*.bcmdl.lz')))[:40]
             + sorted(glob.glob(os.path.join(_EXTRACTED, 'MONSTER', '*.bcmdl.lz')))[:40])
    seen, fails = {}, 0
    for path in files:
        if path.endswith('.pack.lz'):
            mp = mappack.load(path)
            cgs = [mp.texture_cgfx()]
        else:
            cgs = [bcmdl.Cgfx(bcmdl.load_bcmdl_bytes(path))]
        for cg in cgs:
            for t in (cg.textures() if cg else []):
                f = t.get('format_id')
                if not t.get('ok') or seen.get(f, 0) >= max_per_format:
                    continue
                seen[f] = seen.get(f, 0) + 1
                args = (t['_raw'], t['width'], t['height'], f)
                if ctr_texture.decode(*args) != ctr_texture.decode_py(*args):
                    print(f"  FAIL numpy != python: {os.path.basename(path)} {t['name']} {t['format']}")
                    fails += 1
    # every format (also those no sampled file uses), random data, sizes that
    # are not multiples of the 8x8 tile
    rnd = random.Random(7)
    for f in range(len(ctr_texture.FMT_NAMES)):
        for w, h in ((16, 8), (24, 40), (20, 12)):
            tw, th = (w + 7) // 8 * 8, (h + 7) // 8 * 8
            raw = bytes(rnd.getrandbits(8) for _ in range(ctr_texture.min_bytes(tw, th, f)))
            if ctr_texture.decode(raw, w, h, f) != ctr_texture.decode_py(raw, w, h, f):
                print(f'  FAIL numpy != python: random {ctr_texture.FMT_NAMES[f]} {w}x{h}')
                fails += 1
    print(f"  {'OK  ' if not fails else 'FAIL'} numpy path == python path (all formats on random data) for formats "
          + ', '.join(f'{ctr_texture.FMT_NAMES[f]}x{n}' for f, n in sorted(seen.items())))
    return fails


def main():
    fails = _check_rgba8_order()
    fails += _check_numpy_matches_python()
    for rel, needle, expect in CASES:
        path = os.path.join(_EXTRACTED, *rel.split('/'))
        if not os.path.isfile(path):
            print(f'  SKIP {rel}: not extracted')
            continue
        cg = bcmdl.Cgfx(bcmdl.load_bcmdl_bytes(path))
        tex = next((t for t in cg.textures()
                    if t.get('ok') and needle in t['name']), None)
        if not tex:
            print(f'  FAIL {rel}: no ok texture matching {needle!r}')
            fails += 1
            continue
        rgba = ctr_texture.decode(tex['_raw'], tex['width'], tex['height'],
                                  tex['format_id'])
        n = tex['width'] * tex['height']
        r, g, b = avg_rgb(rgba, n)
        ok = (r > b) if expect == 'warm' else (b > r)
        print(f"  {'OK  ' if ok else 'FAIL'} {rel} [{tex['name']} {tex['format']}] "
              f"avgRGB=({r},{g},{b}) expect {expect}")
        if not ok:
            fails += 1

    for rel, name, expect in MAP_CASES:
        path = os.path.join(_EXTRACTED, *rel.split('/'))
        if not os.path.isfile(path):
            print(f'  SKIP {rel}: not extracted')
            continue
        cg = mappack.load(path).texture_cgfx()
        tex = next((t for t in cg.textures() if t.get('ok') and t['name'] == name), None)
        if not tex:
            print(f'  FAIL {rel}: no ok texture {name!r}')
            fails += 1
            continue
        rgba = ctr_texture.decode(tex['_raw'], tex['width'], tex['height'],
                                  tex['format_id'])
        r, g, b = avg_rgb(rgba, tex['width'] * tex['height'])
        ok = (r > b) if expect == 'warm' else (b > r)
        print(f"  {'OK  ' if ok else 'FAIL'} {rel} [{name} {tex['format']}] "
              f"avgRGB=({r},{g},{b}) expect {expect}")
        if not ok:
            fails += 1

    if fails:
        print(f'\n{fails} failure(s) - texture channel order is wrong')
        sys.exit(1)
    print('\ntexture decode channel-order OK')


if __name__ == '__main__':
    main()
