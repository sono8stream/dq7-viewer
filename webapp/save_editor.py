"""
Minimal DQ7 (3DS) save-file editor backend.

Offsets are sourced from the turtle-insect/DQ7 save editor
(github.com/turtle-insect/DQ7 - DataContext.cs / Charactor.cs /
SaveData.cs / PartyMember.cs / Util.cs, fetched 2026-08-23), which this
project's own investigation already leaned on to identify the Party
array (0x0510) and Charactors array (0x0C80) constants referenced by
the game's ARM code - see
docs/party_add_remove_command_investigation.md ("セーブデータ構造の調査"
section). This module re-implements just enough of that C# tool
(read/write only, no UI) to inspect and edit a save file directly, so
party add/remove hypotheses can be tested by poking the save instead of
only via script-opcode injection.

Save file layout (all offsets are raw byte offsets into the save file,
no header to skip - `CalcAddress()` in the reference source is the
identity function):

  0x0000-0x0003  u32 checksum = sum of signed-byte values of every byte
                 from 0x0010 to EOF, truncated to 32 bits
  0x0020+id/8    Place.Visit bit array, 1 bit per place id (bit id%8) -
                 reference source's formula, confirmed only for the
                 formula itself; the id->place-name table
                 (`info/place.txt` in the reference tool) is NOT in its
                 git repo or release zip, so names are unknown here.
                 This bit array runs from 0x0020 up to some unknown
                 point before 0x0510 (Party) - the reference source
                 never states its length (it's read from that missing
                 place.txt at runtime). The ~0x4F0-byte gap between
                 0x0020 and 0x0510 almost certainly holds OTHER event/
                 quest flags too (e.g. the flag[N] values referenced by
                 IF_FLAG script opcodes throughout
                 docs/party_add_remove_command_investigation.md) - this
                 module exposes it as raw bytes/bits for exploratory
                 poking rather than guessing a structure.
  0x0510+i*4     Party formation slot i (i=0..5), u32 character_id
                 (0 = empty slot). This is the array ADD_PARTY_MEMBER /
                 PARTY_SLOT_* write into (see docs/).
  0x0528..0x0540 Gold / Bank / Casino / MedalBank / SmallMedal /
                 MaxDamage / AllGold, u32 each
  0x0C80+i*STR   Charactor stat block for fixed character slot i
                 (i=0..5, STRIDE=0x1EC on 3DS / 0x1F0 on Android).
                 NOTE: this is NOT the same indexing as the Party array
                 above - Charactors is one fixed block per character
                 identity, Party is the current formation order.

Device type only changes the Charactor block stride and the Name
field's offset within it. Every other Charactor field below is
unaffected by device type (the reference source's Android +4 shift
only applies to the Items/Magics/Skills/Jobs sub-tables inside
Charactor, which this module does not implement - out of scope for
party add/remove testing).
"""

import datetime
import os
import struct

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_PARTY_MENU_PATH = os.path.join(_ROOT, 'rom', 'extracted', 'MENULIST', 'party_menu.txt')

CHECKSUM_START = 0x10

# raw flags/bits region exposed for exploratory editing - see module
# docstring. Runs up to (not including) PARTY_BASE.
FLAGS_REGION_BASE = 0x0020

PARTY_BASE = 0x0510
PARTY_SLOT_COUNT = 6

CHAR_BASE = 0x0C80
CHAR_COUNT = 6
CHAR_STRIDE = {0: 0x1EC, 1: 0x1F0}
CHAR_NAME_OFFSET = {0: 0x01B0, 1: 0x01B4}
CHAR_NAME_SIZE = 12
# the reference tool writes the name to two locations 0x1A (26) bytes
# apart - a second copy the game apparently also reads from.
CHAR_NAME_MIRROR_DELTA = 0x1A

# (field name, relative offset, byte size, min, max, mirror offset or None)
CHAR_FIELDS = [
    ('exp', 0x0014, 4, 0, 0xFFFFFF, None),
    ('power', 0x0018, 2, 1, 999, None),
    ('defense', 0x001A, 2, 1, 999, None),
    ('hp', 0x001C, 2, 0, 999, None),
    ('max_hp', 0x001E, 2, 1, 999, 0x0020),
    ('mp', 0x0022, 2, 0, 999, None),
    ('max_mp', 0x0024, 2, 1, 999, 0x0026),
    ('speed', 0x0028, 2, 1, 999, None),
    ('intelligence', 0x002A, 2, 1, 999, None),
    ('cool', 0x002C, 2, 1, 999, None),
    ('lv', 0x002E, 1, 1, 99, None),
    ('job', 0x0038, 1, 0, 255, None),
]
CHAR_FIELD_NAMES = {f[0] for f in CHAR_FIELDS}

# Per-job "star" mastery level array (1 byte per job, job_id 0..54 = the
# same 55-record range as LEVELDATA/dq7_player_job.dat - see
# docs/character_status_investigation.md). CONFIRMED 2026-09-22 by
# direct byte comparison against a real save (save/00000001/save001.bin):
# for every party member, the byte at CHAR_JOB_LEVELS_OFFSET + job_id
# equals that member's on-screen job mastery star count for whichever
# job matches their current 'job' field (e.g. job=17 -> byte[17]==7 for
# a character whose job-change menu shows 7 stars). This array is
# distinct from the ARM runtime HaveJob object's own layout
# (this+4=currentJob, this+5..+59=this same level array, one byte per
# job - see HaveJob::getJobLevel/setJobLevel/change, file offsets
# 0x194990/0x1949ac/0x123880 in rom/exefs/code.decompressed.bin) - the
# save block's array starts right after the 'job' byte at relative
# +0x0039 instead of the runtime object's +5, but the per-job indexing
# (job_id = byte offset from array start) and semantics are the same.
# See docs/keifa_job_animation_investigation.md "セーブデータのjob別
# star配列" section for the investigation and the real-save comparison
# table (Keifa's array is entirely zero - he has never held any other
# job in this save - while all 5 other members have scattered non-zero
# entries from their job-change history).
CHAR_JOB_LEVELS_OFFSET = 0x0039
CHAR_JOB_LEVELS_COUNT = 55

# Play time ("冒険した時間"), u32 frame counter at 30fps, offset CONFIRMED
# 2026-09-27 via ARM disassembly of GameStatus::addPlayTime (file offset
# 0x22262c) and cross-checked against 4 real saves - see
# docs/save_play_time_investigation.md for the full investigation
# (why 0x3250, the 0x66febf8/999h59m cap, and the save002.bin fix).
PLAY_TIME_OFFSET = 0x3250
PLAY_TIME_MAX_FRAMES = 0x66FEBF8  # ~999h59m59s at 30fps
FRAMES_PER_SECOND = 30

# (field name, absolute offset, byte size, min, max)
SCALAR_FIELDS = [
    ('gold', 0x0528, 4, 0, 9999999),
    ('bank', 0x052C, 4, 0, 9999999),
    ('casino', 0x0530, 4, 0, 9999999),
    ('medal_bank', 0x0534, 4, 0, 9999999),
    ('small_medal', 0x0538, 4, 0, 9999999),
    ('max_damage', 0x053C, 4, 0, 9999999),
    ('all_gold', 0x0540, 4, 0, 99999999),
    ('play_time_frames', PLAY_TIME_OFFSET, 4, 0, PLAY_TIME_MAX_FRAMES),
]
SCALAR_FIELD_NAMES = {f[0] for f in SCALAR_FIELDS}


def load_character_names() -> dict:
    """id(int) -> name, from MENULIST/party_menu.txt ('#<id>,<flag>,<name>')."""
    names = {0: ''}
    if not os.path.isfile(_PARTY_MENU_PATH):
        return names
    with open(_PARTY_MENU_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('#'):
                continue
            parts = line[1:].split(',', 2)
            if len(parts) < 3:
                continue
            try:
                cid = int(parts[0])
            except ValueError:
                continue
            names[cid] = parts[2]
    return names


def _read_u(buf: bytes, addr: int, size: int) -> int:
    return int.from_bytes(buf[addr:addr + size], 'little', signed=False)


def _write_u(buf: bytearray, addr: int, size: int, value: int) -> None:
    value = max(0, min(value, (1 << (size * 8)) - 1))
    buf[addr:addr + size] = value.to_bytes(size, 'little', signed=False)


def read_bit(buf: bytes, addr: int, bit: int) -> bool:
    return bool(buf[addr] & (1 << bit))


def _write_bit(buf: bytearray, addr: int, bit: int, value: bool) -> None:
    if value:
        buf[addr] |= (1 << bit)
    else:
        buf[addr] &= ~(1 << bit) & 0xFF


def place_visit(buf: bytes, place_id: int) -> bool:
    """Mirrors the reference source's Place.Visit getter exactly:
    ReadBit(0x0020 + id/8, id%8). Name unknown (see module docstring) -
    only the id number and on/off state are meaningful here."""
    return read_bit(buf, FLAGS_REGION_BASE + place_id // 8, place_id % 8)


def compute_checksum(buf: bytes) -> int:
    total = 0
    for b in buf[CHECKSUM_START:]:
        total += b - 256 if b >= 128 else b
    return total & 0xFFFFFFFF


def parse_buffer(buf: bytes, device_type: int = 0) -> dict:
    """Pure parse of raw save bytes -> field dict. No file I/O - shared by
    the path-based load (read_save) and the browser-upload flow (which
    never touches a path on the server, only bytes posted from the
    client's native file picker)."""
    stride = CHAR_STRIDE[device_type]
    name_off = CHAR_NAME_OFFSET[device_type]
    names_by_id = load_character_names()

    stored_checksum = _read_u(buf, 0, 4)
    computed_checksum = compute_checksum(buf)

    party = []
    for i in range(PARTY_SLOT_COUNT):
        cid = _read_u(buf, PARTY_BASE + i * 4, 4)
        party.append({'slot': i, 'character_id': cid, 'character_name': names_by_id.get(cid, f'?{cid}')})

    scalars = {name: _read_u(buf, addr, size) for name, addr, size, _mn, _mx in SCALAR_FIELDS}
    play_time_frames = scalars['play_time_frames']
    scalars['play_time_hours'] = play_time_frames // FRAMES_PER_SECOND // 3600
    scalars['play_time_minutes'] = play_time_frames // FRAMES_PER_SECOND // 60 % 60

    charactors = []
    for i in range(CHAR_COUNT):
        base = CHAR_BASE + i * stride
        entry = {'index': i, 'base_offset': base}
        for name, rel, size, _mn, _mx, _mirror in CHAR_FIELDS:
            entry[name] = _read_u(buf, base + rel, size)
        job_levels = list(buf[base + CHAR_JOB_LEVELS_OFFSET:base + CHAR_JOB_LEVELS_OFFSET + CHAR_JOB_LEVELS_COUNT])
        entry['job_levels'] = job_levels
        entry['job_levels_nonzero'] = {j: v for j, v in enumerate(job_levels) if v}
        raw_name = buf[base + name_off:base + name_off + CHAR_NAME_SIZE]
        entry['name'] = raw_name.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
        # slot index i is a fixed character identity in this array (not the
        # current party formation order) - id = i+1 matches party_menu.txt
        # for the 6 main-story party characters (1=Arus..6=Aira).
        # CONFIRMED against real saves (2026-09-10, see
        # docs/playable_character_expansion_investigation.md 実験A): a save
        # with Kiefa (id 3) rejoined has charactors[2] = the Lv13/MP0
        # physical-type "キーファ" block. Guests (e.g. Filia id 31 sitting in
        # a Party slot) have NO block in this array - it is exactly 6 fixed
        # slots, ending at 0x1808 right before the OPTN/FLAG save sections.
        entry['presumed_character_id'] = i + 1
        entry['presumed_character_name'] = names_by_id.get(i + 1, '')
        charactors.append(entry)

    flags_end = min(PARTY_BASE, len(buf))
    flags_region = {
        'offset': FLAGS_REGION_BASE,
        'size': flags_end - FLAGS_REGION_BASE,
        'hex': buf[FLAGS_REGION_BASE:flags_end].hex(),
    }

    return {
        'file_size': len(buf),
        'device_type': device_type,
        'checksum_stored': stored_checksum,
        'checksum_computed': computed_checksum,
        'checksum_ok': stored_checksum == computed_checksum,
        'party': party,
        'scalars': scalars,
        'charactors': charactors,
        'character_catalog': [{'id': cid, 'name': n} for cid, n in sorted(names_by_id.items()) if cid],
        'flags_region': flags_region,
    }


def read_save(path: str, device_type: int = 0) -> dict:
    with open(path, 'rb') as f:
        buf = f.read()
    result = parse_buffer(buf, device_type)
    result['path'] = path
    return result


def _backup(path: str, buf: bytes) -> str:
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(path)), 'dq7_save_backup')
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = os.path.join(backup_dir, f'{os.path.basename(path)}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(buf)
    return backup_path


def apply_patch(buf: bytes, device_type: int, patch: dict) -> bytes:
    """patch = {'party': [{'slot': i, 'character_id': v}, ...],
                'scalars': {name: value, ...},
                'charactors': [{'index': i, <field>: value, ..., 'name': str?}, ...],
                'raw_bits': [{'offset': int, 'bit': 0-7, 'value': bool}, ...],
                'raw_bytes': [{'offset': int, 'hex': str}, ...]}
    Pure function: applies only the fields present in patch to a copy of
    buf, recomputes the checksum, and returns the new bytes. No file I/O -
    shared by write_save (path on the server) and the browser-upload flow
    (edits bytes in memory, hands them back to the client as a download;
    the server itself never has a path to write to in that case).

    raw_bits/raw_bytes are unrestricted-offset escape hatches for
    exploratory flag hunting (see module docstring on FLAGS_REGION_BASE) -
    unlike every other field above they are not validated against a
    known field table, so a bad offset can corrupt the save. Used from
    the "生バイト/フラグ" panel in the save editor UI.
    """
    buf = bytearray(buf)
    stride = CHAR_STRIDE[device_type]
    name_off = CHAR_NAME_OFFSET[device_type]

    for entry in patch.get('raw_bits', []):
        offset = int(entry['offset'])
        bit = int(entry['bit'])
        if not (0 <= offset < len(buf)) or not (0 <= bit <= 7):
            raise ValueError(f'invalid raw_bits entry {entry}')
        _write_bit(buf, offset, bit, bool(entry['value']))

    for entry in patch.get('raw_bytes', []):
        offset = int(entry['offset'])
        data = bytes.fromhex(entry['hex'])
        if not (0 <= offset and offset + len(data) <= len(buf)):
            raise ValueError(f'invalid raw_bytes entry {entry}')
        buf[offset:offset + len(data)] = data

    for entry in patch.get('party', []):
        i = entry['slot']
        if not (0 <= i < PARTY_SLOT_COUNT):
            raise ValueError(f'invalid party slot {i}')
        _write_u(buf, PARTY_BASE + i * 4, 4, int(entry['character_id']))

    scalars = patch.get('scalars', {})
    for name, addr, size, mn, mx in SCALAR_FIELDS:
        if name in scalars:
            v = max(mn, min(int(scalars[name]), mx))
            _write_u(buf, addr, size, v)

    for entry in patch.get('charactors', []):
        i = entry['index']
        if not (0 <= i < CHAR_COUNT):
            raise ValueError(f'invalid charactor index {i}')
        base = CHAR_BASE + i * stride
        for name, rel, size, mn, mx, mirror in CHAR_FIELDS:
            if name in entry:
                v = max(mn, min(int(entry[name]), mx))
                _write_u(buf, base + rel, size, v)
                if mirror is not None:
                    _write_u(buf, base + mirror, size, v)
        # job_levels: {job_id(str or int): level(0-8)} - sparse edits to
        # the per-job star array (see CHAR_JOB_LEVELS_OFFSET above). Used
        # to test the "is Keifa's empty job-level array the cause of his
        # run/walk animation bug" hypothesis without a CIA rebuild - see
        # docs/keifa_job_animation_investigation.md.
        for job_id, level in entry.get('job_levels', {}).items():
            job_id = int(job_id)
            if not (0 <= job_id < CHAR_JOB_LEVELS_COUNT):
                raise ValueError(f'invalid job_id {job_id}')
            v = max(0, min(int(level), 255))
            buf[base + CHAR_JOB_LEVELS_OFFSET + job_id] = v
        if entry.get('name'):
            raw = entry['name'].encode('utf-8')[:CHAR_NAME_SIZE]
            raw = raw + b'\x00' * (CHAR_NAME_SIZE - len(raw))
            buf[base + name_off:base + name_off + CHAR_NAME_SIZE] = raw
            mirror_off = base + name_off + CHAR_NAME_MIRROR_DELTA
            buf[mirror_off:mirror_off + CHAR_NAME_SIZE] = raw

    checksum = compute_checksum(bytes(buf))
    _write_u(buf, 0, 4, checksum)
    return bytes(buf)


def write_save(path: str, device_type: int, patch: dict) -> dict:
    """Re-reads the file fresh from disk, backs it up, applies patch (see
    apply_patch), and writes the result back to the same path."""
    with open(path, 'rb') as f:
        original = f.read()

    backup_path = _backup(path, original)
    new_buf = apply_patch(original, device_type, patch)

    with open(path, 'wb') as f:
        f.write(new_buf)

    return {'ok': True, 'backup_path': backup_path, 'checksum': _read_u(new_buf, 0, 4)}
