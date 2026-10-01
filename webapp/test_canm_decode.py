"""
Regression tests for webapp/bcmdl.py's CANM skeletal-animation decoding.

Guards several real bugs found across one investigation (see
docs/canm_skeletal_animation_investigation.md for the full derivation):

  1. p0053: a constant-(1,1,1) Scale track being misread as a Translation,
     which set a bone's position to (1,1,1) - larger than the whole
     skeleton - tearing it apart during playback (e.g. p0053_wait).
  2. p0051 idle/dash/wait (and others): bones using GfxAnimTransform
     (PrimitiveType==5, Euler-angle Hermite-compressed curves) silently
     decoded to 0 tracks, because the scanner only recognized
     GfxAnimQuatTransform (PrimitiveType==8, packed per-frame samples).
  3. p0492_idle (and similar single-fixed-pose clips, frames==0.0): a
     Constant channel (GfxAnimQuatTransform's IsConstant==1, one sample for
     the whole clip) was never matched by the old byte-shape scan, and for
     frames==0.0 specifically the scan could latch onto unrelated all-zero
     padding bytes before ever reaching the real header - so the pose
     silently fell back to raw bind pose (nothing visibly happened).
     Fixed by resolving GfxAnimQuatTransform's 3 channel pointers directly
     from the structure (_canm_quat_transform_headers) instead of
     scanning, and (webapp/static/model.js) guarding frames==0 so the
     client doesn't compute `x % 0` (NaN) when picking a sample index.

...and a crash found while regression-testing #2: read_animation() used a
fixed "+0x600" guess for the last bone's byte range, which read past EOF
(struct.error) for small pack.lz files.

  4. Clicking a '.pack.lz' entry in the model viewer rendered an empty
     model (no geometry, no textures): a .pack.lz holds only a
     SkeletalAnims dict, the real Models/Textures/LUTS live in the
     sibling .bcmdl.lz. This was a day-one bug (present since the model
     viewer's first commit) in server.py's kind classification, not a
     regression. Fixed by having read_model() redirect .pack.lz ->
     .bcmdl.lz transparently.

Run: python3 webapp/test_canm_decode.py
Slow exhaustive scan of every CHARACTER clip (~10 min - this is literally
how the +0x600 crash above was found, so it's kept as an opt-in sweep
rather than thrown away after the fix):
  python3 webapp/test_canm_decode.py --all
"""
import argparse
import glob
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import bcmdl  # noqa: E402

_EXTRACTED = os.path.join(_HERE, '..', 'rom', 'extracted')


def _path(rel):
    return os.path.join(_EXTRACTED, *rel.split('/'))


def _check_p0053_scale_not_translation():
    """No 'translation' track may ever be a constant (1,1,1) - real bone
    offsets in this skeleton are all well under 1.0 in magnitude, so such a
    track must be a Scale channel misclassified as Translation."""
    path = _path('CHARACTER/p0053.bcmdl.lz')
    if not os.path.isfile(path):
        print('  SKIP p0053 scale/translation split: not extracted')
        return 0
    anim = bcmdl.read_animation(path, 'p0053_wait')
    bad = []
    saw_scale = False
    for bname, tr in anim['tracks'].items():
        if 'scale' in tr:
            saw_scale = True
        t = tr.get('translation')
        if t and all(abs(x - 1) < 0.3 and abs(y - 1) < 0.3 and abs(z - 1) < 0.3
                      for x, y, z in t):
            bad.append(bname)
    ok = not bad and saw_scale
    print(f"  {'OK  ' if ok else 'FAIL'} p0053_wait scale/translation split "
          f"(bogus-translation bones={bad}, saw_scale_track={saw_scale})")
    return 0 if ok else 1


def _check_gfx_transform_tracks():
    """GfxAnimTransform (PrimitiveType==5) bones must decode real
    rotation/translation curves, not silently fall back to 0 tracks."""
    path = _path('CHARACTER/p0051.bcmdl.lz')
    if not os.path.isfile(path):
        print('  SKIP p0051 GfxAnimTransform decode: not extracted')
        return 0
    fails = 0
    for clip in ('p0051_idle', 'p0051_dash', 'p0051_wait'):
        anim = bcmdl.read_animation(path, clip)
        n = len(anim['tracks'])
        ok = n > 0
        print(f"  {'OK  ' if ok else 'FAIL'} {clip} tracks={n} (expect > 0)")
        fails += 0 if ok else 1
    return fails


def _check_hermite_keyframe_values():
    """Pins the Hermite128 curve decode against hand-verified raw bytes
    (see docs/canm_skeletal_animation_investigation.md): p0051_idle's
    Center bone TranslationY curve has exactly 3 keys, at frames 0/39/60."""
    path = _path('CHARACTER/p0051.bcmdl.lz')
    if not os.path.isfile(path):
        print('  SKIP Hermite128 keyframe values: not extracted')
        return 0
    anim = bcmdl.read_animation(path, 'p0051_idle')
    ty = anim['tracks']['Center']['translation']
    expect = {0: 1.1451499462127686, 39: 1.1456400156021118, 60: 1.1451499462127686}
    fails = 0
    for f, v in expect.items():
        got = ty[f][1]
        ok = abs(got - v) < 1e-4
        print(f"  {'OK  ' if ok else 'FAIL'} Center.translation[{f}].y={got:.6f} "
              f"expect {v:.6f}")
        fails += 0 if ok else 1
    return fails


def _check_normalized_quaternions_and_no_nan():
    """Every decoded rotation sample must be a valid unit quaternion, and no
    NaN/Inf may appear anywhere - a generic guard (not tied to one specific
    bug) against future decode mistakes in either code path."""
    cases = [
        ('CHARACTER/p0051.bcmdl.lz', 'p0051_idle'),
        ('CHARACTER/p0053.bcmdl.lz', 'p0053_wait'),
        ('CHARACTER/p0003_j00.bcmdl.lz', 'p0003_j00_idle'),
    ]
    fails = 0
    for rel, clip in cases:
        path = _path(rel)
        if not os.path.isfile(path):
            print(f'  SKIP {clip}: not extracted')
            continue
        anim = bcmdl.read_animation(path, clip)
        bad_norm = bad_nan = 0
        for tr in anim['tracks'].values():
            for s in tr.get('rotation', []):
                if any(math.isnan(v) or math.isinf(v) for v in s):
                    bad_nan += 1
                    continue
                norm = sum(v * v for v in s) ** 0.5
                if abs(norm - 1.0) > 0.05:
                    bad_norm += 1
            for s in tr.get('translation', []) + tr.get('scale', []):
                if any(math.isnan(v) or math.isinf(v) for v in s):
                    bad_nan += 1
        ok = bad_norm == 0 and bad_nan == 0
        print(f"  {'OK  ' if ok else 'FAIL'} {clip} quaternion norm/NaN check "
              f"(bad_norm={bad_norm}, bad_nan={bad_nan})")
        fails += 0 if ok else 1
    return fails


def _check_constant_pose_clip():
    """p0492_idle (frames=0.0, a single held pose): the old byte-scan
    either missed Constant channels entirely, or - specifically for a
    frames==0.0 clip - could latch onto unrelated all-zero padding before
    reaching the real header, so the pose never showed. Direct pointer
    resolution (_canm_quat_transform_headers) must recover it."""
    path = _path('CHARACTER/p0492.bcmdl.lz')
    if not os.path.isfile(path):
        print('  SKIP p0492_idle constant-pose decode: not extracted')
        return 0
    anim = bcmdl.read_animation(path, 'p0492_idle')
    tr = anim['tracks'].get('polymsh_detached', {})
    t = tr.get('translation')
    ok = bool(t) and len(t) == 1 and abs(t[0][1] - 1.5885900259017944) < 1e-4
    print(f"  {'OK  ' if ok else 'FAIL'} p0492_idle constant translation "
          f"={t} expect [[0.034849, 1.588590, 0.196232]]")
    return 0 if ok else 1


def _check_last_bone_no_crash():
    """p0074_idle used to raise struct.error decoding its last bone (the
    +0x600 range guess overran a small file's EOF)."""
    path = _path('CHARACTER/p0074.bcmdl.lz')
    if not os.path.isfile(path):
        print('  SKIP p0074_idle no-crash: not extracted')
        return 0
    try:
        bcmdl.read_animation(path, 'p0074_idle')
        ok = True
    except Exception as e:
        ok = False
        print(f'  FAIL p0074_idle raised {e!r}')
    if ok:
        print('  OK   p0074_idle decodes without crashing')
    return 0 if ok else 1


def _check_pack_lz_redirects_to_bcmdl_geometry():
    """read_model('*.pack.lz') must return real geometry/textures, not empty
    ones. A .pack.lz file holds ONLY a SkeletalAnims dict (no Models/
    Textures/LUTS) - verified across CHARACTER/MONSTER/BATTLE - the actual
    geometry+textures live in the sibling .bcmdl.lz. This was a day-one bug
    in webapp/server.py's list_model_files() (present since the model
    viewer's very first commit, fc01c2f): its docstring/kind logic claimed
    the opposite ("'pack' (has full geometry)"), so clicking a .pack.lz
    entry in the viewer silently rendered an empty model with no textures.
    Fixed by having bcmdl.read_model() transparently redirect a .pack.lz
    path to its .bcmdl.lz sibling."""
    ok = True
    for rel in ('CHARACTER/p0003_j00.pack.lz', 'BATTLE/b0003_j00.pack.lz'):
        path = _path(rel)
        if not os.path.isfile(path):
            print(f'  SKIP {rel}: not extracted')
            continue
        result = bcmdl.read_model(path)
        n_tex = len(result.get('textures') or [])
        n_shapes = len((result.get('geometry') or {}).get('shapes') or [])
        if n_tex == 0 or n_shapes == 0:
            ok = False
            print(f'  FAIL {rel}: read_model() returned {n_tex} textures, '
                  f'{n_shapes} shapes (expected >0 of each - .pack.lz redirect '
                  f'to sibling .bcmdl.lz is broken)')
        else:
            print(f'  OK   {rel}: read_model() returned {n_tex} textures, {n_shapes} shapes')
    return 0 if ok else 1


def _scan_all_character_clips():
    """Exhaustive: every SkeletalAnims clip of every CHARACTER/*.bcmdl.lz
    must decode without raising. Slow (~10 min, ~11000 clips) - this sweep
    is what actually found the +0x600 overrun bug, so it earns its keep as
    an opt-in full pass rather than a one-off scratch script."""
    files = sorted(glob.glob(os.path.join(_EXTRACTED, 'CHARACTER', '*.bcmdl.lz')))
    errs = 0
    checked = 0
    for path in files:
        pack = bcmdl._anim_pack_path(path)
        if not pack:
            continue
        try:
            anims = bcmdl.list_animations(path)
        except Exception as e:
            print(f'  FAIL {path}: list_animations raised {e!r}')
            errs += 1
            continue
        for a in anims:
            checked += 1
            try:
                bcmdl.read_animation(path, a['name'])
            except Exception as e:
                print(f"  FAIL {path} {a['name']}: {e!r}")
                errs += 1
    print(f'  checked {checked} clips across {len(files)} files, {errs} error(s)')
    return 0 if errs == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true',
                     help='also run the slow exhaustive all-CHARACTER-clips scan')
    args = ap.parse_args()

    fails = 0
    fails += _check_p0053_scale_not_translation()
    fails += _check_gfx_transform_tracks()
    fails += _check_hermite_keyframe_values()
    fails += _check_normalized_quaternions_and_no_nan()
    fails += _check_constant_pose_clip()
    fails += _check_last_bone_no_crash()
    fails += _check_pack_lz_redirects_to_bcmdl_geometry()
    if args.all:
        fails += _scan_all_character_clips()

    if fails:
        print(f'\n{fails} failure(s) - CANM animation decode regressed')
        sys.exit(1)
    print('\nCANM animation decode OK')


if __name__ == '__main__':
    main()
