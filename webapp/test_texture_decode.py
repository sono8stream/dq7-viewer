"""
Sanity check for webapp/ctr_texture.py channel order + bit layout.

Face / skin textures must come out warm (avg R > avg B). This is the
regression guard for the R/B swap bug in the 16-bit formats (DQ7 packs
RGB565 / RGBA5551 / RGBA4 with R in the HIGH bits, unlike SPICA's
helpers). Run: python3 webapp/test_texture_decode.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import bcmdl  # noqa: E402
import ctr_texture  # noqa: E402

_EXTRACTED = os.path.join(_HERE, '..', 'rom', 'extracted')

# (model, texture-name-substring, expectation)
CASES = [
    ('CHARACTER/p0003_j00.bcmdl.lz', 'kao', 'warm'),   # Keifa face (RGB565)
    ('CHARACTER/p0001_j00.bcmdl.lz', 'face', 'warm'),  # Hero face (RGBA5551)
    ('CHARACTER/p0001_j00.bcmdl.lz', 'e0', 'warm'),    # eyes (skin-ish)
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


def main():
    fails = _check_rgba8_order()
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

    if fails:
        print(f'\n{fails} failure(s) - texture channel order is wrong')
        sys.exit(1)
    print('\ntexture decode channel-order OK')


if __name__ == '__main__':
    main()
