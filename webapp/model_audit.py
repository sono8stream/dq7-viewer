"""Batch structural audit for CHARACTER/MONSTER .bcmdl.lz models.

Written 2026-09-21 after a run of individually-reported bcmdl.py bugs
(wrong UV channel, false-positive decal overlay, ...) that each required a
fresh manual investigation to spot. Instead of waiting for the next visual
report, this script re-runs the SAME structural checks bcmdl.py already
knows how to do (AlphaTest/CullMode/SourceCoordIndex/TexEnv-combiner scans,
animation track decode) across every model in rom/extracted/ and prints
anything that looks off, so problems can be found and triaged in bulk
instead of one bug report at a time. See docs/bcmdl_model_viewer.md,
2026-09-21 "モデル一括監査ツール" for how/when to use this.

Every check here reads an actual field the model specifies (AlphaTest,
CullMode, SourceCoordIndex, TexEnv combiner sources/modes) - none of them
guess from what a texture's pixels happen to look like. See
docs/bcmdl_model_viewer.md, 2026-09-21 "TexEnvコンバイナ構造を読む根本修正"
for why an earlier version of this file's decal check (based on how opaque
a texture's pixels were) was replaced.

Usage: python3 webapp/model_audit.py [--dir CHARACTER|MONSTER|both] [--anims]
`--anims` also decodes every animation clip of every model (slower, ~30s for
all CHARACTER files) to flag clips that claim >2 frames but have zero
sampled bone tracks (see docs, "動かないアニメクリップの扱い" - NOT
necessarily a bug, some clips are genuinely static, but worth a human
glance in bulk rather than only ever noticed one character at a time).
"""

import argparse
import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import bcmdl  # noqa: E402


def _materials_findings(path):
    """Flag materials where a structural scan (AlphaTest/CullMode/TexEnv)
    found nothing at all - a real parse gap (e.g. an unexpected CGFX
    revision), worth a human look. A material with secondary textures that
    ALL end up 'unused' is NOT flagged here: `_tex_env_mapper_roles()`
    finding no stage referencing a given texture unit is itself the
    structural answer (see docs, "TexEnvコンバイナ構造を読む根本修正"), not
    evidence the scan failed."""
    out = []
    try:
        cg = bcmdl.get_cgfx(path)
        mats = bcmdl._materials(cg)
    except Exception as e:
        return [f'materials parse exception: {type(e).__name__}: {e}']
    for name, textures, alpha, side, coord, roles in mats:
        if alpha is None:
            out.append(f'material {name!r}: AlphaTest scan found nothing (using opaqueBase fallback)')
        if side is None:
            out.append(f'material {name!r}: CullMode scan found nothing (defaulting to double-sided)')
    return out


def _uv_findings(path):
    """Flag shapes whose ACTUAL base-texture uv set (per textureUV[0]) is
    degenerate (near-zero span in either axis) despite having many
    vertices - the signature of the p0006_j09 'huku' bug, kept as a
    regression/new-case guard even where SourceCoordIndex itself decodes
    cleanly."""
    out = []
    try:
        r = bcmdl.read_model(path)
    except Exception as e:
        return [f'read_model exception: {type(e).__name__}: {e}']
    for sh in r['geometry']['shapes']:
        if not sh.get('ok') or not sh.get('textures'):
            continue
        coord = sh.get('textureUV')
        key = ('uvs', 'uvs1', 'uvs2')[coord[0]] if coord else 'uvs'
        uvs = sh.get(key)
        nv = (sh.get('vcount') or 0)
        if not uvs or nv < 20:
            continue
        us = uvs[0::2]
        vs = uvs[1::2]
        uspan = max(us) - min(us)
        vspan = max(vs) - min(vs)
        if uspan < 0.15 or vspan < 0.15:
            out.append(f"shape {sh.get('name') or sh.get('offset')} ({nv}v, tex {sh['textures'][0]!r}): "
                        f"base uv span u={uspan:.3f} v={vspan:.3f} looks degenerate")
    return out


def _anim_findings(path):
    out = []
    try:
        anims = bcmdl.list_animations(path)
    except Exception as e:
        return [f'list_animations exception: {type(e).__name__}: {e}']
    for a in anims:
        if (a.get('frames') or 0) <= 2:
            continue  # too short to expect real motion either way
        try:
            data = bcmdl.read_animation(path, a['name'])
        except Exception as e:
            out.append(f"anim {a['name']!r} (frames={a['frames']}): decode exception {type(e).__name__}: {e}")
            continue
        if not data['tracks']:
            out.append(f"anim {a['name']!r} (frames={a['frames']}): 0 sampled bone tracks (static clip?)")
    return out


def audit(paths, check_anims=False):
    total = 0
    flagged = 0
    for p in paths:
        total += 1
        findings = _materials_findings(p) + _uv_findings(p)
        if check_anims:
            findings += _anim_findings(p)
        if findings:
            flagged += 1
            print(f'=== {p}')
            for f in findings:
                print(f'  {f}')
    print(f'\n{flagged}/{total} files flagged')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dir', choices=['CHARACTER', 'MONSTER', 'both'], default='both')
    ap.add_argument('--anims', action='store_true', help='also decode every animation clip (slower)')
    ap.add_argument('--limit', type=int, default=0, help='only check the first N files (0 = all)')
    args = ap.parse_args()

    root = os.path.join(_HERE, '..', 'rom', 'extracted')
    dirs = ['CHARACTER', 'MONSTER'] if args.dir == 'both' else [args.dir]
    paths = []
    for d in dirs:
        paths += sorted(glob.glob(os.path.join(root, d, '*.bcmdl.lz')))
    if args.limit:
        paths = paths[:args.limit]
    audit(paths, check_anims=args.anims)


if __name__ == '__main__':
    main()
