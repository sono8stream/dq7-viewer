"""
Script file inspector and GUI

Usage:
  - Run GUI: python script\script_viewer.py
  - Test parse all sample files (non-GUI): python script\script_viewer.py --test

Places a simple Tkinter GUI under which you can open script files and
browse the hierarchy: script -> scriptgroup -> scriptobject -> handlers -> blocks

This is a lightweight tool built from the observed format in `script/README.md`.
"""

import os
import sys
import struct
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Dict, Any, Optional
import importlib.util


def read_u32(b: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<I', b, offset)[0]


def parse_script(path: str) -> Dict[str, Any]:
    """Parse top-level script file and return a nested structure.

    The function is defensive: it uses header fields when available and
    falls back to reasonable defaults.
    """
    res = {'path': path, 'groups': [], 'header': {}}
    with open(path, 'rb') as f:
        data = f.read()
    # keep raw bytes for deferred/lightweight on-demand parsing
    res['raw'] = data
    size = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size:
            return b''
        return data[off:off + length]

    # top header: 0x00..0x0f tag, 0x10..0x13 group_count,
    # 0x14..0x17 header_size, 0x18..0x1b group_ref_size
    tag = read_at(0, 0x10).rstrip(b'\x00').decode('ascii', errors='replace')
    group_count = read_u32(data, 0x10) if size >= 0x14 else 0
    header_size = read_u32(data, 0x14) if size >= 0x18 else 0x20
    group_ref_size = read_u32(data, 0x18) if size >= 0x1c else 0
    res['header'] = {
        'tag': tag,
        'group_count': group_count,
        'header_size': header_size,
        'group_ref_size': group_ref_size,
    }

    # group reference area starts at 0x20
    ref_start = 0x20
    # If group_ref_size is missing/zero, try to compute from group_count
    if not group_ref_size and group_count:
        # each entry is 8 bytes
        guessed = group_count * 8
        # clamp to available data
        group_ref_size = min(guessed, max(0, size - ref_start))
    # safety clamp: avoid insane sizes that hang the parser
    MAX_REF_BYTES = 1024 * 1024  # 1 MiB
    if group_ref_size > MAX_REF_BYTES:
        print(
            f"Warning: group_ref_size too large ({group_ref_size}), clamping to {MAX_REF_BYTES}")
        group_ref_size = MAX_REF_BYTES
    ref_bytes = read_at(ref_start, group_ref_size)
    group_entries = []
    # group offsets in the top-level table are relative to the top header_size (per README)
    for i in range(0, len(ref_bytes), 8):
        ent = ref_bytes[i:i + 8]
        if len(ent) < 8:
            break
        off_rel = struct.unpack_from('<I', ent, 0)[0]
        sz = struct.unpack_from('<I', ent, 4)[0]
        # treat an all-zero entry as terminator
        if off_rel == 0 and sz == 0:
            break
        # compute absolute offset: top header_size + relative offset
        abs_off = header_size + off_rel
        # skip entries that point outside file
        if abs_off >= size:
            # print(f"Skipping group entry out of range: abs_off {abs_off}")
            continue
        group_entries.append({'offset': abs_off, 'size': sz})

    # parse each group header only (lightweight) to avoid expensive deep parsing
    def is_plausible_group_header(data: bytes, off: int) -> bool:
        size_buf = len(data)
        if off < 0 or off + 0x18 > size_buf:
            return False
        try:
            tag = data[off:off + 0x10].rstrip(b'\x00')
            if not tag:
                return False
            # avoid matching the top-level header at offset 0
            if off == 0:
                return False
            # tag should be printable ascii-ish
            if any(b < 0x20 or b > 0x7e for b in tag):
                return False
            obj_count = read_u32(data, off + 0x10)
            header_size = read_u32(data, off + 0x14)
            # sanity checks
            if obj_count < 0 or obj_count > 10000:
                return False
            if header_size < 0x10 or header_size > 0x10000:
                return False
            return True
        except Exception:
            return False

    for ge in group_entries:
        goff = ge['offset']
        gsize = ge['size']
        # try header at recorded offset first
        gh = parse_group_header(data, goff, gsize)
        if not is_plausible_group_header(data, goff):
            # scan nearby region for a plausible header (±0x40 bytes)
            found = None
            for delta in range(-0x40, 0x41, 4):
                cand = goff + delta
                if cand < 0 or cand + 0x18 > len(data):
                    continue
                if is_plausible_group_header(data, cand):
                    found = cand
                    break
            if found is not None:
                goff = found
                gh = parse_group_header(data, goff, gsize)
        # Additional heuristic: probe common misalignments (-16, -32, -0x30) to find smaller headers
        if gh.get('header_size', 0) > 0x40 or gh.get('obj_count', 0) > 8:
            for delta in (-16, -32, -48, -64, 16, 32):
                cand = goff + delta
                if cand <= 0 or cand + 0x14 > len(data):
                    continue
                cand_h = parse_group_header(data, cand, gsize)
                # prefer header_size == 0x30 or small obj_count
                if cand_h.get('header_size') == 0x30 or cand_h.get('obj_count') in (1,):
                    goff = cand
                    gh = cand_h
                    break
        # include raw offset/size
        gh['offset'] = goff
        gh['size'] = gsize
        res['groups'].append(gh)

    # If we found fewer groups than header.group_count, try a fallback scan to locate plausible group headers
    if res['header'].get('group_count') and len(res['groups']) < res['header'].get('group_count'):
        needed = res['header'].get('group_count') - len(res['groups'])
        found_offsets = [g['offset'] for g in res['groups']]
        scanned = 0
        for cand in range(0x20, size - 0x20, 4):
            if cand in found_offsets or cand == 0:
                continue
            if is_plausible_group_header(data, cand):
                gh = parse_group_header(data, cand, 0)
                gh['offset'] = cand
                gh['size'] = 0
                res['groups'].append(gh)
                found_offsets.append(cand)
                needed -= 1
                if needed <= 0:
                    break
            scanned += 1
            # avoid scanning too long
            if scanned > 5000:
                break

    return res


def parse_group(data: bytes, start: int, size: int) -> Dict[str, Any]:
    size_buf = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size_buf:
            return b''
        return data[off:off + length]

    tag = read_at(start, 0x10).rstrip(
        b'\x00').decode('ascii', errors='replace')
    obj_count = read_u32(data, start + 0x10) if start + 0x14 <= size_buf else 0
    header_size = read_u32(data, start + 0x14) if start + \
        0x18 <= size_buf else 0x20
    obj_ref_size = read_u32(data, start + 0x18) if start + \
        0x1c <= size_buf else 0
    ref_start = start + 0x20
    # If obj_ref_size is missing, try using obj_count
    if not obj_ref_size and obj_count:
        guessed = obj_count * 8
        obj_ref_size = min(guessed, max(0, size_buf - ref_start))
    if obj_ref_size > 1024 * 1024:
        print(
            f"Warning: obj_ref_size too large ({obj_ref_size}) at group {start}, clamping")
        obj_ref_size = 1024 * 1024
    ref_bytes = read_at(ref_start, obj_ref_size)
    obj_entries = []
    for i in range(0, len(ref_bytes), 8):
        ent = ref_bytes[i:i + 8]
        if len(ent) < 8:
            break
        off = struct.unpack_from('<I', ent, 0)[0]
        sz = struct.unpack_from('<I', ent, 4)[0]
        # offsets in the group's ref table are relative to the group's header_size
        abs_off = start + header_size + off
        # treat all-zero as terminator
        if off == 0 and sz == 0:
            break
        # skip out-of-range entries
        if abs_off < 0 or abs_off >= size_buf:
            # silently skip invalid
            continue
        obj_entries.append({'offset': abs_off, 'size': sz})

    group = {
        'tag': tag,
        'start': start,
        'size': size,
        'obj_count': obj_count,
        'header_size': header_size,
        'obj_ref_size': obj_ref_size,
        'objects': []
    }

    for oe in obj_entries:
        o = parse_object(data, oe['offset'], oe['size'])
        group['objects'].append(o)
    return group


def parse_group_header(data: bytes, start: int, size: int) -> Dict[str, Any]:
    """Lightweight parse of group header: returns tag and obj_count without parsing objects."""
    size_buf = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size_buf:
            return b''
        return data[off:off + length]

    tag = read_at(start, 0x10).rstrip(
        b'\x00').decode('ascii', errors='replace')
    obj_count = 0
    header_size = 0x20
    obj_ref_size = 0
    if start + 0x14 <= size_buf:
        try:
            obj_count = read_u32(data, start + 0x10)
        except Exception:
            obj_count = 0
    if start + 0x18 <= size_buf:
        try:
            header_size = read_u32(data, start + 0x14)
        except Exception:
            header_size = 0x20
    if start + 0x1c <= size_buf:
        try:
            obj_ref_size = read_u32(data, start + 0x18)
        except Exception:
            obj_ref_size = 0

    # If obj_ref_size missing but obj_count present, guess size
    if not obj_ref_size and obj_count:
        guessed = obj_count * 8
        obj_ref_size = guessed

    return {'tag': tag, 'obj_count': obj_count, 'header_size': header_size, 'obj_ref_size': obj_ref_size}


def parse_group_objects_header(data: bytes, start: int, size: int) -> List[Dict[str, Any]]:
    """Lightweight parse: return list of object headers (offset,size,tag,proc_count).

    This does not parse procedures; it only reads the group's object reference table
    and for each object reads the tag and proc_count from that object's header.
    """
    size_buf = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size_buf:
            return b''
        return data[off:off + length]

    objects = []
    # read obj_count and header fields from group header (strict per README)
    obj_count = read_u32(data, start + 0x10) if (start +
                                                 0x14) <= size_buf else 0
    header_size = read_u32(
        data, start + 0x14) if (start + 0x18) <= size_buf else 0x20
    obj_ref_size = read_u32(
        data, start + 0x18) if (start + 0x1c) <= size_buf else 0

    ref_start = start + 0x20
    # Determine number of entries strictly from obj_ref_size when present, else from obj_count
    entries_count = 0
    if obj_ref_size and obj_ref_size >= 8:
        entries_count = obj_ref_size // 8
    elif obj_count and obj_count > 0:
        entries_count = obj_count

    # clamp to what's available in the file
    max_possible = max(0, (size_buf - ref_start) // 8)
    if entries_count > max_possible:
        entries_count = max_possible

    for i in range(entries_count):
        off = read_u32(data, ref_start + i * 8)
        sz = read_u32(data, ref_start + i * 8 + 4)
        # stop if completely zero (common terminator)
        if off == 0 and sz == 0:
            break
        # offsets in object ref table are relative to the group's header_size
        abs_off = start + header_size + off
        # validate absolute offset/size
        if abs_off < 0 or abs_off >= size_buf:
            # skip invalid offset
            print(
                f"Skipping invalid object entry in group at {start}: abs_offset {abs_off} out of range (raw {off})")
            continue
        if sz < 0 or (sz != 0 and abs_off + sz > size_buf):
            # accept sz==0 (meaning unknown/variable), otherwise skip
            if sz != 0:
                print(
                    f"Skipping object entry with invalid size in group at {start}: abs_offset {abs_off} size {sz}")
                continue
        tag = read_at(abs_off, 0x10).rstrip(
            b'\x00').decode('ascii', errors='replace')
        proc_count = read_u32(
            data, abs_off + 0x10) if (abs_off + 0x14) <= size_buf else 0
        objects.append({'offset': abs_off, 'size': sz,
                       'tag': tag, 'proc_count': proc_count})

    # If header.obj_count exists but we found fewer entries, print a note
    if obj_count and len(objects) != obj_count:
        print(
            f"Note: group at {start}: header.obj_count={obj_count} but parsed objects={len(objects)}")

    return objects


def parse_object(data: bytes, start: int, size: int) -> Dict[str, Any]:
    size_buf = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size_buf:
            return b''
        return data[off:off + length]

    tag = read_at(start, 0x10).rstrip(
        b'\x00').decode('ascii', errors='replace')
    proc_count = read_u32(data, start + 0x10) if start + \
        0x14 <= size_buf else 0
    header_size = read_u32(data, start + 0x14) if start + \
        0x18 <= size_buf else 0x20
    proc_ref_size = read_u32(
        data, start + 0x18) if start + 0x1c <= size_buf else 0
    ref_start = start + 0x20
    if not proc_ref_size and proc_count:
        guessed = proc_count * 8
        proc_ref_size = min(guessed, max(0, size_buf - ref_start))
    if proc_ref_size > 1024 * 1024:
        print(
            f"Warning: proc_ref_size too large ({proc_ref_size}) at object {start}, clamping")
        proc_ref_size = 1024 * 1024
    ref_bytes = read_at(ref_start, proc_ref_size)
    proc_entries = []
    for i in range(0, len(ref_bytes), 8):
        ent = ref_bytes[i:i + 8]
        if len(ent) < 8:
            break
        off = struct.unpack_from('<I', ent, 0)[0]
        sz = struct.unpack_from('<I', ent, 4)[0]
        # stop if all-zero terminator
        if off == 0 and sz == 0:
            break
        abs_off = start + header_size + off
        if abs_off < 0 or abs_off >= size_buf:
            # skip invalid
            print(
                f"Skipping invalid procedure entry in object at {start}: abs_offset {abs_off} out of range (raw {off})")
            continue
        proc_entries.append({'offset': abs_off, 'size': sz})

    # unknown area: spec mentions a 0x30-byte region after header in many files
    unknown_area = read_at(
        start + header_size, 0x30) if header_size and start + header_size < size_buf else b''

    obj = {
        'tag': tag,
        'start': start,
        'size': size,
        'proc_count': proc_count,
        'header_size': header_size,
        'proc_ref_size': proc_ref_size,
        'unknown_area': unknown_area,
        'procedures': []
    }

    for pe in proc_entries:
        p = parse_procedure(data, pe['offset'], pe['size'])
        obj['procedures'].append(p)
    return obj


def parse_procedure(data: bytes, start: int, size: int) -> Dict[str, Any]:
    size_buf = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size_buf:
            return b''
        return data[off:off + length]

    tag = read_at(start, 0x10).rstrip(
        b'\x00').decode('ascii', errors='replace')
    block_count = read_u32(data, start + 0x10) if start + \
        0x14 <= size_buf else 0
    header_size = read_u32(data, start + 0x14) if start + \
        0x18 <= size_buf else 0x20
    block_ref_size = read_u32(
        data, start + 0x18) if start + 0x1c <= size_buf else 0
    ref_start = start + 0x20
    if not block_ref_size and block_count:
        guessed = block_count * 8
        block_ref_size = min(guessed, max(0, size_buf - ref_start))
    if block_ref_size > 1024 * 1024:
        print(
            f"Warning: block_ref_size too large ({block_ref_size}) at procedure {start}, clamping")
        block_ref_size = 1024 * 1024
    ref_bytes = read_at(ref_start, block_ref_size)
    block_entries = []
    for i in range(0, len(ref_bytes), 8):
        ent = ref_bytes[i:i + 8]
        if len(ent) < 8:
            break
        off = struct.unpack_from('<I', ent, 0)[0]
        sz = struct.unpack_from('<I', ent, 4)[0]
        # stop if all-zero terminator
        if off == 0 and sz == 0:
            break
        abs_off = start + header_size + off
        if abs_off < 0 or abs_off >= size_buf:
            print(
                f"Skipping invalid block entry in procedure at {start}: abs_offset {abs_off} out of range (raw {off})")
            continue
        block_entries.append({'offset': abs_off, 'size': sz})

    proc = {
        'tag': tag,
        'start': start,
        'size': size,
        'block_count': block_count,
        'header_size': header_size,
        'block_ref_size': block_ref_size,
        'blocks': []
    }

    # parse blocks: block 1 = indent region, block 2 = offsets list, block 3 = code
    for be in block_entries:
        b = parse_block(data, be['offset'], be['size'])
        proc['blocks'].append(b)
    # If we have offsets in block 2 and code in block 3, split code into commands
    try:
        if len(proc['blocks']) >= 3:
            offsets_block = proc['blocks'][1]
            code_block = proc['blocks'][2]
            # Only split code into commands when the offsets block actually contains one or more offsets
            if (offsets_block.get('offsets') and len(offsets_block.get('offsets')) >= 1) and code_block.get('raw') is not None:
                cmd_offsets = offsets_block.get('offsets')
                code_raw = code_block.get('raw')
                code_size = code_block.get('size')
                commands = []
                # keep only sane offsets (integers within [0, code_size])
                valid_offsets = [o for o in cmd_offsets if isinstance(
                    o, int) and 0 <= o <= code_size]
                if valid_offsets:
                    valid_offsets = sorted(valid_offsets)
                    if valid_offsets[-1] != code_size:
                        valid_offsets.append(code_size)
                    for i in range(len(valid_offsets) - 1):
                        s = valid_offsets[i]
                        e = valid_offsets[i + 1]
                        if s >= e:
                            continue
                        chunk = code_raw[s:e]
                        commands.append({'index': i, 'rel_start': s, 'rel_end': e,
                                        'size': e - s, 'raw': chunk, 'hex': chunk.hex()})
                code_block['commands'] = commands
    except Exception:
        pass

    return proc


def parse_block(data: bytes, start: int, size: int) -> Dict[str, Any]:
    size_buf = len(data)

    def read_at(off: int, length: int) -> bytes:
        if off < 0 or off >= size_buf:
            return b''
        return data[off:off + length]

    raw = read_at(start, size)
    # Heuristics: if block seems to be list of u32 (length %4==0) and many values, treat as offsets
    is_offsets = (len(raw) % 4 == 0) and (len(raw) >= 8 and len(raw) <= 4096)
    offsets = []
    if is_offsets:
        for i in range(0, len(raw), 4):
            offsets.append(struct.unpack_from('<I', raw, i)[0])

    block = {
        'start': start,
        'size': size,
        'raw': raw,
        'is_offsets': is_offsets,
        'offsets': offsets,
    }
    return block


########################################################################
# Simple GUI


def decode_command_3ds(raw: bytes) -> Dict[str, Any]:
    """Decode a single command using the README's 3DS instruction guidance.

    This function reads the first 4 bytes as an opcode word (little-endian u32)
    and applies a small mapping for observed 3DS patterns. It returns a dict
    containing a friendly name, parsed u32 params and any interpreted fields.
    """
    if not raw:
        return {'error': 'empty'}
    try:
        opcode_word = struct.unpack_from(
            '<I', raw, 0)[0] if len(raw) >= 4 else raw[0]
        out: Dict[str, Any] = {
            'opcode_word': f"0x{opcode_word:08x}", 'raw_hex': raw.hex()}

        # 3DS-only mapping from README.md (observed patterns)
        opcode_map = {
            0x00030009: 'MSG_CONTINUOUS_3DS',  # bytes: 09 00 03 00
        }
        out['name'] = opcode_map.get(opcode_word, f'op_{opcode_word:08x}')

        # read trailing u32 params
        params = []
        off = 4
        while off + 4 <= len(raw):
            params.append(struct.unpack_from('<I', raw, off)[0])
            off += 4

        # opcode-specific friendly decoding
        if opcode_word == 0x00030009:
            # README: 09 00 03 00 | [テキストファイルの番号] * 4bytes [連続する文字数]
            if len(params) >= 1:
                out['text_file_number'] = params[0]
                out['text_file_id'] = params[0]  # legacy name
            if len(params) >= 2:
                out['char_count'] = params[1]
                out['count'] = params[1]  # legacy name
            out['params'] = params
            return out

        if params:
            out['params'] = params
        return out
    except Exception as e:
        return {'error': 'decode_failed', 'exc': str(e), 'raw_hex': raw.hex()}


_FPT_CACHE: Dict[str, Any] = {}

# Optional override directory for locating .fpt files. If set, use this
# directory as the root to search .fpt files instead of walking the repo.
FPT_ROOT_OVERRIDE: Optional[str] = None


def set_fpt_root(path: Optional[str]) -> None:
    """Set or clear the global .fpt search root used by _find_fpt_by_number.

    Pass None or empty string to clear the override and fall back to repo scan.
    """
    global FPT_ROOT_OVERRIDE
    if path:
        FPT_ROOT_OVERRIDE = os.path.abspath(path)
        try:
            print(f"[set_fpt_root] override set to {FPT_ROOT_OVERRIDE}", flush=True)
        except Exception:
            pass
    else:
        FPT_ROOT_OVERRIDE = None
        try:
            print("[set_fpt_root] override cleared", flush=True)
        except Exception:
            pass


def _find_fpt_by_number(num: int) -> Optional[str]:
    """Try to locate a .fpt file that corresponds to the given numeric id.

    Heuristics used:
    - Look for files named with zero-padded 6-digit names like `000000.fpt` or
      `#000000.fpt` anywhere under the repo root.
    - If none found, return None.
    """
    # debug log: show which numeric id we're attempting to resolve
    try:
        print(f"[find_fpt] called with num={num}", flush=True)
    except Exception:
        pass

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    # If an override root is provided via UI, prefer that as the search root.
    search_root = FPT_ROOT_OVERRIDE if FPT_ROOT_OVERRIDE else repo_root
    # gather all .fpt files under search_root
    fpt_files = []
    for root, dirs, files in os.walk(search_root):
        for fn in files:
            if fn.lower().endswith('.fpt'):
                fpt_files.append(os.path.join(root, fn))

    if not fpt_files:
        try:
            print(
                f"[find_fpt] no .fpt files found under {repo_root}", flush=True)
        except Exception:
            pass
        return None

    # Try direct name matches first (exact or containing substring)
    cand_exact = [f"{num:06d}.fpt", f"#{num:06d}.fpt", f"{num}.fpt"]
    for p in fpt_files:
        fn = os.path.basename(p)
        for c in cand_exact:
            if fn == c or c in fn:
                try:
                    print(
                        f"[find_fpt] exact match candidate for num={num} -> {p}", flush=True)
                except Exception:
                    pass
                return p

    # Fallback heuristic: many .fpt use a base index in filename (e.g. '#001000.fpt')
    # where the numeric id = base + index. Find a file whose numeric prefix is <= num
    # and pick the file with the largest base <= num.
    best = None
    best_base = -1
    import re
    for p in fpt_files:
        fn = os.path.basename(p)
        m = re.search(r"(\d{3,6})", fn)
        if not m:
            continue
        try:
            base = int(m.group(1))
        except Exception:
            continue
        # if base is greater than num, skip
        if base > num:
            continue
        if base > best_base:
            best_base = base
            best = p

    if best is not None:
        try:
            print(
                f"[find_fpt] fallback selected base={best_base} for num={num} -> {best}", flush=True)
        except Exception:
            pass
    else:
        try:
            print(
                f"[find_fpt] no matching .fpt found for num={num}", flush=True)
        except Exception:
            pass
    return best


def _load_fpt_messages(fpt_path: str) -> Optional[dict]:
    """Load messages from an .fpt using mess/extract_fpt.py logic.

    Caches results keyed by absolute path. Returns the full parsed dict
    returned by `extract_texts_from_fpt`, which includes 'file_infos' and
    'file_messages'. This lets callers inspect filenames/metadata to find
    the correct message by ID.
    """
    if not fpt_path:
        return None
    ap = os.path.abspath(fpt_path)
    if ap in _FPT_CACHE:
        return _FPT_CACHE[ap]

    # locate the extractor module file in repo: mess/extract_fpt.py
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    extractor_path = os.path.join(repo_root, 'mess', 'extract_fpt.py')
    parsed = None
    if not os.path.isfile(extractor_path):
        # try to import by name as fallback
        try:
            from mess.extract_fpt import extract_texts_from_fpt  # type: ignore
        except Exception:
            return None
        try:
            parsed = extract_texts_from_fpt(ap)
        except Exception:
            return None
    else:
        try:
            spec = importlib.util.spec_from_file_location(
                'extract_fpt_mod', extractor_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)
            parsed = mod.extract_texts_from_fpt(ap)
        except Exception:
            return None

    if not isinstance(parsed, dict):
        return None
    _FPT_CACHE[ap] = parsed
    return parsed


def _resolve_message_from_number(num: int) -> Optional[str]:
    """Given the numeric file id from a command, find the .fpt and return the
    associated message text (best-effort). If not found, return None.
    """
    try:
        fpt_path = _find_fpt_by_number(num)
        if not fpt_path:
            return None
        parsed = _load_fpt_messages(fpt_path)
        if not parsed:
            return None
        msgs = parsed.get('file_messages', [])
        # Each message entry typically contains a 'filename' and 'message'.
        # The .fpt format doesn't guarantee sequential IDs, so we must
        # extract the ID from the filename (or metadata) and compare.
        import re
        for m in msgs:
            # prefer an explicit 'id' field if present
            mid = m.get('id')
            if mid is not None:
                try:
                    if int(mid) == num:
                        try:
                            print(
                                f"[resolve_msg] matched by explicit id={mid} in filename={m.get('filename')}", flush=True)
                        except Exception:
                            pass
                        return m.get('message')
                except Exception:
                    pass
            # otherwise, try to extract any integer token from the filename
            fn = str(m.get('filename', ''))
            for tok in re.findall(r"\d+", fn):
                try:
                    if int(tok) == num:
                        try:
                            print(
                                f"[resolve_msg] matched by filename-number {tok} for num={num} -> filename={fn}", flush=True)
                        except Exception:
                            pass
                        return m.get('message')
                except Exception:
                    continue

        # Fallback: some extractors include file_infos metadata with offsets and
        # other filename forms. Check parsed['file_infos'] for filename fields
        # that may include the numeric ID.
        for fi in parsed.get('file_infos', []):
            fname = str(fi.get('filename', ''))
            for tok in re.findall(r"\d+", fname):
                try:
                    if int(tok) == num:
                        # find corresponding entry in msgs (matching filename)
                        for m in msgs:
                            if m.get('filename') == fi.get('filename'):
                                try:
                                    print(
                                        f"[resolve_msg] matched via file_infos filename={fname} for num={num}", flush=True)
                                except Exception:
                                    pass
                                return m.get('message')
                except Exception:
                    continue

        # nothing matched; return None
        try:
            print(
                f"[resolve_msg] no message matched for num={num} in {fpt_path}", flush=True)
        except Exception:
            pass
        return None
    except Exception:
        return None


class ScriptViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Script Viewer')
        self.geometry('1000x700')

        top = ttk.Frame(self)
        top.pack(fill='x', padx=6, pady=6)
        ttk.Button(top, text='Open script',
                   command=self.open_file).pack(side='left')
        ttk.Button(top, text='Load sample', command=self.load_sample_menu).pack(
            side='left', padx=6)
        # Allow user to set a custom .fpt folder to resolve message ids
        ttk.Button(top, text='Set .fpt dir', command=self._on_set_fpt_dir).pack(
            side='left', padx=6)
        self.fpt_label = ttk.Label(top, text='fpt: (auto)')
        self.fpt_label.pack(side='left', padx=6)
        self.status = ttk.Label(top, text='Ready')
        self.status.pack(side='left', padx=6)

        main = ttk.Panedwindow(self, orient='horizontal')
        main.pack(fill='both', expand=True, padx=6, pady=6)

        left = ttk.Frame(main, width=360)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=3)

        ttk.Label(left, text='Groups').pack(anchor='w')
        # simple list of groups (fast to populate)
        self.group_list = tk.Listbox(left)
        self.group_list.pack(fill='both', expand=True)
        self.group_list.bind('<<ListboxSelect>>', self.on_group_select)

        ttk.Label(left, text='Objects').pack(anchor='w', pady=(6, 0))
        self.object_list = tk.Listbox(left)
        self.object_list.pack(fill='both', expand=True)
        self.object_list.bind('<<ListboxSelect>>', self.on_object_select)

        ttk.Label(left, text='Procedures').pack(anchor='w', pady=(6, 0))
        self.proc_list = tk.Listbox(left)
        self.proc_list.pack(fill='both', expand=True)
        self.proc_list.bind('<<ListboxSelect>>', self.on_proc_select)

        ttk.Label(left, text='Commands').pack(anchor='w', pady=(6, 0))
        self.cmd_list = tk.Listbox(left)
        self.cmd_list.pack(fill='both', expand=True)
        self.cmd_list.bind('<<ListboxSelect>>', self.on_cmd_select)

        # right: details
        ttk.Label(right, text='Details').pack(anchor='w')
        self.detail_text = tk.Text(right)
        self.detail_text.pack(fill='both', expand=True)

        self.current_parsed = None

    def open_file(self):
        p = filedialog.askopenfilename(filetypes=[('Script files', '*.*')])
        if p:
            self.load_script(p)

    def load_sample_menu(self):
        sample_dir = os.path.join(os.path.dirname(__file__), 'sample_data')
        if not os.path.isdir(sample_dir):
            messagebox.showinfo(
                'No samples', f'No sample_data folder found at {sample_dir}')
            return
        files = [f for f in os.listdir(sample_dir) if os.path.isfile(
            os.path.join(sample_dir, f))]
        if not files:
            messagebox.showinfo('No samples', 'No sample files found')
            return
        # present a simple selection dialog
        sel = SimpleSelectDialog(self, files, title='Select sample file')
        self.wait_window(sel)
        if sel.result is not None:
            chosen = os.path.join(sample_dir, sel.result)
            self.load_script(chosen)

    def _on_set_fpt_dir(self):
        # Ask user for a directory containing .fpt files. Setting an empty
        # selection clears the override and falls back to auto-search.
        p = filedialog.askdirectory(title='Select .fpt folder (or Cancel to clear)')
        if p:
            set_fpt_root(p)
            self.fpt_label.config(text=f'fpt: {p}')
        else:
            set_fpt_root(None)
            self.fpt_label.config(text='fpt: (auto)')

    def load_script(self, path: str):
        # Parse in background thread to avoid blocking the UI
        self.status.config(text=f'Parsing {os.path.basename(path)}')
        # disable buttons while parsing
        for child in self.winfo_children():
            try:
                for btn in child.winfo_children():
                    if isinstance(btn, ttk.Button):
                        btn.config(state='disabled')
            except Exception:
                pass

        def worker():
            try:
                parsed = parse_script(path)
            except Exception as e:
                self.after(0, lambda: self._on_parse_error(e))
                return
            # schedule UI update on main thread
            self.after(0, lambda: self._on_parsed(parsed, path))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_parse_error(self, exc: Exception):
        messagebox.showerror('Parse error', str(exc))
        self.status.config(text='Error')
        # re-enable buttons
        for child in self.winfo_children():
            try:
                for btn in child.winfo_children():
                    if isinstance(btn, ttk.Button):
                        btn.config(state='normal')
            except Exception:
                pass

    def _on_parsed(self, parsed: Dict[str, Any], path: str):
        self.current_parsed = parsed
        # logging: print header group_count and per-group object counts
        hdr = parsed.get('header', {})
        gc = hdr.get('group_count')
        print(
            f"Parsed {os.path.basename(path)}: header.group_count={gc}, parsed.groups={len(parsed.get('groups', []))}")
        if gc is not None and gc != len(parsed.get('groups', [])):
            print(
                f"Warning: header.group_count ({gc}) does not match parsed group entries ({len(parsed.get('groups', []))})")
        for i, g in enumerate(parsed.get('groups', [])):
            print(
                f" group {i}: tag={g.get('tag')} obj_count={g.get('obj_count')}")
        # populate UI
        self.populate_tree(parsed)
        self.status.config(text=f'Loaded {os.path.basename(path)}')
        # re-enable buttons
        for child in self.winfo_children():
            try:
                for btn in child.winfo_children():
                    if isinstance(btn, ttk.Button):
                        btn.config(state='normal')
            except Exception:
                pass

    def populate_tree(self, parsed: Dict[str, Any]):
        # populate a simple listbox with group headers
        self.group_list.delete(0, 'end')
        # clear objects view when new file loaded
        try:
            self.object_list.delete(0, 'end')
        except Exception:
            pass
        hdr = parsed.get('header', {})
        self.group_list.insert(
            'end', f"file: {os.path.basename(parsed['path'])} | tag: {hdr.get('tag')} | groups: {hdr.get('group_count')}")
        for gi, g in enumerate(parsed.get('groups', [])):
            self.group_list.insert(
                'end', f"group {gi}: tag={g.get('tag')} offset={g.get('offset')} size={g.get('size')} obj_count={g.get('obj_count')}")

    # group list selection handler
    def on_group_select(self, evt):
        sel = self.group_list.curselection()
        if not sel or not self.current_parsed:
            return
        idx = sel[0]
        # index 0 is file summary
        if idx == 0:
            info = self.current_parsed.get('header', {})
            # clear object list when showing file header
            try:
                self.object_list.delete(0, 'end')
            except Exception:
                pass
            self.detail_text.delete('1.0', 'end')
            import pprint
            self.detail_text.insert('end', pprint.pformat(info, width=120))
            return

        gi = idx - 1
        groups = self.current_parsed.get('groups', [])
        if gi < 0 or gi >= len(groups):
            return
        info = groups[gi]
        self.detail_text.delete('1.0', 'end')
        import pprint
        self.detail_text.insert('end', pprint.pformat(info, width=120))

        # parse group's object headers in background and populate object list
        self.status.config(text=f'Loading objects for group {gi}')
        # clear previous objects
        try:
            self.object_list.delete(0, 'end')
        except Exception:
            pass

        def worker_objs():
            objs = []
            try:
                raw = self.current_parsed.get('raw')
                if raw is not None:
                    objs = parse_group_objects_header(raw, info.get(
                        'offset', 0) or 0, info.get('size', 0) or 0)
            except Exception as e:
                print('Failed to parse objects for group', gi, e)
                objs = []
            self.after(0, lambda: self.populate_objects(objs, gi))

        t = threading.Thread(target=worker_objs, daemon=True)
        t.start()

    def populate_objects(self, objs: List[Dict[str, Any]], group_index: int):
        # populate the object_list with lightweight object headers
        try:
            self.object_list.delete(0, 'end')
        except Exception:
            pass
        # clear procedures view when objects change
        try:
            self.proc_list.delete(0, 'end')
        except Exception:
            pass
        self.object_list.insert(
            'end', f"group {group_index} objects: {len(objs)}")
        for oi, o in enumerate(objs):
            self.object_list.insert(
                'end', f"obj {oi}: tag={o.get('tag')} offset={o.get('offset')} size={o.get('size')} proc_count={o.get('proc_count')}")
        # store current objects for detail view
        self.current_objects = objs
        self.status.config(text=f'Loaded objects for group {group_index}')

    def on_object_select(self, evt):
        sel = self.object_list.curselection()
        if not sel or not hasattr(self, 'current_objects'):
            return
        idx = sel[0]
        # index 0 is group summary
        if idx == 0:
            return
        oi = idx - 1
        if oi < 0 or oi >= len(self.current_objects):
            return
        info = self.current_objects[oi]
        self.detail_text.delete('1.0', 'end')
        import pprint
        self.detail_text.insert('end', pprint.pformat(info, width=120))

        # parse object's procedures in background and populate procedures list
        self.status.config(text=f'Loading procedures for object {oi}')
        # clear previous procedures
        try:
            self.proc_list.delete(0, 'end')
        except Exception:
            pass

        def worker_procs():
            procs = []
            try:
                raw = self.current_parsed.get('raw')
                if raw is not None:
                    o = parse_object(raw, info.get('offset', 0)
                                     or 0, info.get('size', 0) or 0)
                    procs = o.get('procedures', [])
            except Exception as e:
                print('Failed to parse procedures for object', oi, e)
                procs = []
            self.after(0, lambda: self.populate_procs(procs, oi))

        t = threading.Thread(target=worker_procs, daemon=True)
        t.start()

    def populate_procs(self, procs: List[Dict[str, Any]], object_index: int):
        try:
            self.proc_list.delete(0, 'end')
        except Exception:
            pass
        # clear commands when procedures change
        try:
            self.cmd_list.delete(0, 'end')
        except Exception:
            pass
        self.proc_list.insert(
            'end', f'object {object_index} procedures: {len(procs)}')
        for pi, p in enumerate(procs):
            self.proc_list.insert(
                'end', f"proc {pi}: tag={p.get('tag')} start={p.get('start')} size={p.get('size')} block_count={p.get('block_count')}")
        self.current_procs = procs
        self.status.config(text=f'Loaded procedures for object {object_index}')

    def on_proc_select(self, evt):
        sel = self.proc_list.curselection()
        if not sel or not hasattr(self, 'current_procs'):
            return
        idx = sel[0]
        if idx == 0:
            return
        pi = idx - 1
        if pi < 0 or pi >= len(self.current_procs):
            return
        info = self.current_procs[pi]
        self.detail_text.delete('1.0', 'end')
        import pprint
        self.detail_text.insert('end', pprint.pformat(info, width=120))
        # populate commands list if available (third block)
        try:
            self.cmd_list.delete(0, 'end')
        except Exception:
            pass
        cmds = []
        try:
            blocks = info.get('blocks', [])
            if len(blocks) >= 3:
                code_block = blocks[2]
                cmds = code_block.get('commands', []) or []
        except Exception:
            cmds = []
        self.cmd_list.insert('end', f'procedure {pi} commands: {len(cmds)}')
        for ci, c in enumerate(cmds):
            self.cmd_list.insert(
                'end', f"cmd {ci}: rel_start={c.get('rel_start')} size={c.get('size')}")
        self.current_cmds = cmds
        self.status.config(text=f'Loaded commands for procedure {pi}')

    def on_cmd_select(self, evt):
        sel = self.cmd_list.curselection()
        if not sel or not hasattr(self, 'current_cmds'):
            return
        idx = sel[0]
        if idx == 0:
            return
        ci = idx - 1
        if ci < 0 or ci >= len(self.current_cmds):
            return
        info = self.current_cmds[ci]
        # show decoded command (3DS-focused)
        raw = info.get('raw', b'')
        decoded = decode_command_3ds(raw)
        lines = []
        lines.append(f"cmd index: {info.get('index')}")
        lines.append(
            f"rel_start: {info.get('rel_start')}  rel_end: {info.get('rel_end')}  size: {info.get('size')}")
        # friendly decoded view
        if 'error' in decoded:
            lines.append(f"decode error: {decoded.get('error')}")
            if decoded.get('exc'):
                lines.append(f"exc: {decoded.get('exc')}")
            lines.append(f"raw: {decoded.get('raw_hex')}")
        else:
            lines.append(
                f"opcode: {decoded.get('opcode_word')}  name: {decoded.get('name')}")
            if decoded.get('params') is not None:
                lines.append(f"params: {decoded.get('params')}")
            # opcode-specific fields
            # prefer new friendly names, fall back to legacy keys
            tfnum = decoded.get('text_file_number',
                                decoded.get('text_file_id'))
            if tfnum is not None:
                lines.append(f"text_file_number: {tfnum}")
                # attempt to resolve actual message text from .fpt files
                try:
                    msg = _resolve_message_from_number(int(tfnum))
                except Exception:
                    msg = None
                if msg:
                    # show a short preview (first 400 chars)
                    preview = msg[:400]
                    lines.append('message_preview:')
                    for l in preview.splitlines()[:20]:
                        lines.append('  ' + l)
                    if len(msg) > 400:
                        lines.append('  ... (truncated)')
            cc = decoded.get('char_count', decoded.get('count'))
            if cc is not None:
                lines.append(f"char_count: {cc}")
            lines.append(f"raw: {decoded.get('raw_hex')}")

        self.detail_text.delete('1.0', 'end')
        self.detail_text.insert('end', '\n'.join(lines))


class SimpleSelectDialog(tk.Toplevel):
    def __init__(self, parent, items: List[str], title: str = 'Select'):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self.geometry('400x300')
        self.listbox = tk.Listbox(self)
        self.listbox.pack(fill='both', expand=True)
        for it in items:
            self.listbox.insert('end', it)
        btn = ttk.Button(self, text='OK', command=self.ok)
        btn.pack()

    def ok(self):
        sel = self.listbox.curselection()
        if not sel:
            self.result = None
        else:
            self.result = self.listbox.get(sel[0])
        self.destroy()


def test_parse_samples():
    sample_dir = os.path.join(os.path.dirname(__file__), 'sample_data')
    if not os.path.isdir(sample_dir):
        print('No sample_data folder found')
        return
    files = [os.path.join(sample_dir, f) for f in os.listdir(
        sample_dir) if os.path.isfile(os.path.join(sample_dir, f))]
    for f in files:
        print('Parsing', f)
        try:
            p = parse_script(f)
            print('tag=', p['header'].get('tag'), 'groups=', len(p['groups']))
            for gi, g in enumerate(p['groups'][:5]):
                print(
                    f' group {gi}: tag={g.get("tag")} obj_count={g.get("obj_count")}')
                # print lightweight object headers for the first few objects
                try:
                    objs = parse_group_objects_header(p.get('raw', b''), g.get(
                        'offset', 0) or 0, g.get('size', 0) or 0)
                    for oi, o in enumerate(objs[:3]):
                        print(
                            f"  obj {oi}: tag={o.get('tag')} offset={o.get('offset')} size={o.get('size')} proc_count={o.get('proc_count')}")
                except Exception as _e:
                    print('  failed to parse objects:', _e)
            # known-sample assertions
            base = os.path.basename(f)
            if base == 'm01nk1f1.bin':
                try:
                    # expect group0 has 1 object
                    assert p['groups'][0].get(
                        'obj_count') == 1, f"m01nk1f1.bin: expected group0.obj_count==1 got {p['groups'][0].get('obj_count')}"
                    objs = parse_group_objects_header(p.get('raw', b''), p['groups'][0].get(
                        'offset', 0), p['groups'][0].get('size', 0))
                    assert len(
                        objs) >= 1, 'm01nk1f1.bin: expected at least 1 object in group0'
                    # object-level expectations: proc_count=4, header_size=64, proc_ref_size=32
                    o0 = parse_object(p.get('raw', b''), objs[0].get(
                        'offset'), objs[0].get('size'))
                    assert o0.get(
                        'proc_count') == 4, f"m01nk1f1.bin: expected obj.proc_count==4 got {o0.get('proc_count')}"
                    assert o0.get('header_size') in (
                        0x40, 64), f"m01nk1f1.bin: unexpected object header_size {o0.get('header_size')}"
                    assert o0.get('proc_ref_size') in (
                        0x20, 32), f"m01nk1f1.bin: unexpected proc_ref_size {o0.get('proc_ref_size')}"
                    print('m01nk1f1.bin checks: OK')
                except AssertionError as ae:
                    print('Assertion failed:', ae)
        except Exception as e:
            print('Failed:', e)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--test':
        test_parse_samples()
        return
    app = ScriptViewer()
    app.mainloop()


if __name__ == '__main__':
    main()
