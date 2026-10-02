"""
General-purpose "insert N commands into an existing procedure, safely"
tool. Generalizes the hand-derived single-command insertion recipe from
patch_m01nk1f1_aligned_insert.py (see its docstring for the discovery of
the 16-byte allocation rule this relies on) to an arbitrary number of
commands of arbitrary total size, inserted at an arbitrary command index
within an arbitrary group/object/procedure.

Confirmed rules this implements (see docs/party_add_remove_command_investigation.md,
"最終決着" section, for how these were established):

  - block1 (indent array): ref-table SIZE field = real command count
    (no padding). Physical region is round_up_16(real size) bytes,
    always starting right after the procedure's 64-byte header.
  - block2 (offset table): ref-table SIZE field = real byte count
    ((cmd_count+1)*4, no padding). Physical rel_offset (from the
    procedure header) = round_up_16(block1's real size). Physical
    region size = round_up_16(block2's real size).
  - block3 (command bytes): ref-table SIZE field = real byte count (no
    padding). Physical rel_offset = block2's physical rel_offset +
    round_up_16(block2's real size).
  - procedure's own declared size (in its OWNER OBJECT's proc-ref
    table) = round_up_16(64 + block3's physical rel_offset + block3's
    real size).
  - Growing a procedure by `growth` bytes requires the SAME growth to
    propagate as a `rel_offset += growth` to every OTHER procedure/
    object/group physically positioned AFTER it (by absolute file
    offset) at every containing level (object's other procedures,
    object's own declared size, group's other objects, group's own
    declared size, top-level's other groups). Existing entries'
    rel_offset/size must NEVER be recomputed from scratch - only
    shifted by the exact growth amount - or the game hangs/corrupts
    (this was the single biggest source of failed insertion attempts
    this session; see docs/ for the long trail of failures that led
    here).

This module intentionally does NOT try to interpret block1's values as
a "cascading if-elseif" structure or otherwise validate command
semantics - it only preserves byte-level structural invariants. Command
semantics (what indent values actually mean at the insertion point) are
the caller's responsibility.

Usage as a library:
    from splice_procedure import splice_procedure
    new_data = splice_procedure(
        data, group_idx=3, obj_idx=7, proc_tag='execute',
        insert_after_cmd_idx=19,
        new_indent_bytes=bytes([4, 5, 5, ...]),
        new_block3_bytes=b'...',
        new_cmd_offsets=[0, 12, 24, ...],  # len == len(new_indent_bytes), cumulative offsets into new_block3_bytes
    )
"""

import struct


def round_up_16(n: int) -> int:
    return ((n + 15) // 16) * 16


def _read_u32(data: bytes, off: int) -> int:
    return struct.unpack_from('<I', data, off)[0]


def _write_u32(data: bytearray, off: int, value: int) -> None:
    struct.pack_into('<I', data, off, value)


def _parse_ref_table(data: bytes, container_start: int, count_field_off: int, ref_size_field_off: int, header_size: int):
    """Generic parser for the group/object/procedure ref-table pattern:
    count:u32, header_size:u32, ref_size:u32 at fixed offsets, followed
    by a ref table of (rel_offset:u32, size:u32) pairs at container_start+0x20.
    Returns list of dicts: {index, ref_table_pos, rel_offset, size, abs_offset}.
    """
    ref_size = _read_u32(data, container_start + ref_size_field_off)
    ref_start = container_start + 0x20
    entries = []
    i = 0
    while i * 8 < ref_size:
        pos = ref_start + i * 8
        rel_off = _read_u32(data, pos)
        size = _read_u32(data, pos + 4)
        if rel_off == 0 and size == 0:
            i += 1
            continue
        entries.append({
            'index': i,
            'ref_table_pos': pos,
            'rel_offset': rel_off,
            'size': size,
            'abs_offset': container_start + header_size + rel_off,
        })
        i += 1
    return entries


def extract_procedure_raw(data: bytes, group_idx: int, obj_idx: int, proc_tag: str):
    """Read-only counterpart to splice_procedure: locates group/obj/proc by
    the same navigation logic and returns (block1_raw, block2_offsets,
    block3_raw) exactly as stored - no reinterpretation of command
    semantics, so this is safe to use as a byte-exact source for
    transplanting a whole procedure's command list into another file via
    splice_procedure (block1_raw gives per-command indent, block2_offsets
    gives cumulative per-command byte offsets into block3_raw, whose
    total length equals block2_offsets[-1])."""
    top_header_size = _read_u32(data, 0x14)
    groups = _parse_ref_table(data, 0, 0x10, 0x18, top_header_size)
    group_start = groups[group_idx]['abs_offset']

    group_header_size = _read_u32(data, group_start + 0x14)
    objects = _parse_ref_table(data, group_start, 0x10, 0x18, group_header_size)
    obj_start = objects[obj_idx]['abs_offset']

    obj_header_size = _read_u32(data, obj_start + 0x14)
    procs = _parse_ref_table(data, obj_start, 0x10, 0x18, obj_header_size)
    target_proc = None
    for p in procs:
        tag = data[p['abs_offset']:p['abs_offset'] + 0x10].rstrip(b'\x00').decode('ascii', errors='replace')
        if tag == proc_tag:
            target_proc = p
            break
    if target_proc is None:
        raise ValueError(f"procedure tag {proc_tag!r} not found in group {group_idx}/obj {obj_idx}")
    proc_start = target_proc['abs_offset']

    PROC_HEADER = _read_u32(data, proc_start + 0x14)
    blocks = _parse_ref_table(data, proc_start, 0x10, 0x18, PROC_HEADER)
    b1, b2, b3 = blocks[0], blocks[1], blocks[2]

    block1_raw = bytes(data[b1['abs_offset']:b1['abs_offset'] + b1['size']])
    block2_raw = data[b2['abs_offset']:b2['abs_offset'] + b2['size']]
    block2_offsets = [struct.unpack_from('<I', block2_raw, i * 4)[0] for i in range(b2['size'] // 4)]
    block3_raw = bytes(data[b3['abs_offset']:b3['abs_offset'] + b3['size']])
    assert len(block2_offsets) == len(block1_raw) + 1
    assert block2_offsets[-1] == len(block3_raw)

    return block1_raw, block2_offsets, block3_raw


def replace_commands(
    data: bytes,
    group_idx: int,
    obj_idx: int,
    proc_tag: str,
    start_idx: int,
    end_idx: int,
    new_indent_bytes: bytes,
    new_block3_bytes: bytes,
    new_cmd_offsets: list,
) -> bytes:
    """General range-replace: removes old commands [start_idx, end_idx)
    (end_idx exclusive) and splices in the new commands described by
    new_indent_bytes/new_block3_bytes/new_cmd_offsets in their place.
    Covers insertion (start_idx == end_idx, new content non-empty),
    deletion (new content empty), and same-position edits (replace a
    range with different-sized new content) with the same logic - the
    16-byte allocation rule (see module docstring) and growth
    propagation are symmetric whether the procedure grows or shrinks.

    new_cmd_offsets must have exactly len(new_indent_bytes) entries -
    the cumulative start offset of each new command within
    new_block3_bytes, starting at 0 (empty lists for pure deletion).
    """
    data = bytearray(data)
    N = len(new_indent_bytes)
    if N == 0:
        assert len(new_cmd_offsets) == 0 and len(new_block3_bytes) == 0
    else:
        assert len(new_cmd_offsets) == N, "new_cmd_offsets must have one entry per new command"
        assert new_cmd_offsets[0] == 0, "new_cmd_offsets must start at 0"

    # --- top level ---
    top_header_size = _read_u32(data, 0x14)
    groups = _parse_ref_table(data, 0, 0x10, 0x18, top_header_size)
    group = groups[group_idx]
    group_start = group['abs_offset']

    # --- group ---
    group_header_size = _read_u32(data, group_start + 0x14)
    objects = _parse_ref_table(data, group_start, 0x10, 0x18, group_header_size)
    obj = objects[obj_idx]
    obj_start = obj['abs_offset']

    # --- object: find the target procedure by tag ---
    obj_header_size = _read_u32(data, obj_start + 0x14)
    procs = _parse_ref_table(data, obj_start, 0x10, 0x18, obj_header_size)
    target_proc = None
    for p in procs:
        tag = data[p['abs_offset']:p['abs_offset'] + 0x10].rstrip(b'\x00').decode('ascii', errors='replace')
        p['tag'] = tag
        if tag == proc_tag:
            target_proc = p
    if target_proc is None:
        raise ValueError(f"procedure tag {proc_tag!r} not found in group {group_idx}/obj {obj_idx}")
    proc_start = target_proc['abs_offset']
    old_proc_size = target_proc['size']

    # --- procedure: parse block1/block2/block3 ref entries ---
    PROC_HEADER = _read_u32(data, proc_start + 0x14)
    blocks = _parse_ref_table(data, proc_start, 0x10, 0x18, PROC_HEADER)
    if len(blocks) < 3:
        raise ValueError(f"expected >=3 blocks, found {len(blocks)}")
    b1, b2, b3 = blocks[0], blocks[1], blocks[2]

    old_block1_raw = bytes(data[b1['abs_offset']:b1['abs_offset'] + b1['size']])
    old_M = b1['size']
    if not (0 <= start_idx <= end_idx <= old_M):
        raise ValueError(f"range [{start_idx},{end_idx}) invalid for {old_M} existing commands")

    old_block2_raw = data[b2['abs_offset']:b2['abs_offset'] + b2['size']]
    old_block2_offsets = [struct.unpack_from('<I', old_block2_raw, i * 4)[0] for i in range(b2['size'] // 4)]
    assert len(old_block2_offsets) == old_M + 1, (len(old_block2_offsets), old_M)

    old_block3_raw = bytes(data[b3['abs_offset']:b3['abs_offset'] + b3['size']])
    assert old_block2_offsets[-1] == len(old_block3_raw)

    # === logical splice (see module docstring) ===
    remove_start_offset = old_block2_offsets[start_idx]
    remove_end_offset = old_block2_offsets[end_idx]
    TOTAL_NEW_BYTES = len(new_block3_bytes)
    removed_bytes = remove_end_offset - remove_start_offset
    delta = TOTAL_NEW_BYTES - removed_bytes
    if new_cmd_offsets:
        assert new_cmd_offsets[-1] <= TOTAL_NEW_BYTES

    new_block1_real = old_block1_raw[:start_idx] + new_indent_bytes + old_block1_raw[end_idx:]
    new_entries = [remove_start_offset + o for o in new_cmd_offsets]
    shifted_tail = [o + delta for o in old_block2_offsets[end_idx:]]
    new_block2_offsets = old_block2_offsets[:start_idx] + new_entries + shifted_tail
    new_block3_real = (
        old_block3_raw[:remove_start_offset] + bytes(new_block3_bytes) + old_block3_raw[remove_end_offset:]
    )
    assert new_block2_offsets[-1] == len(new_block3_real)
    removed_count = end_idx - start_idx
    assert len(new_block1_real) == old_M - removed_count + N
    assert len(new_block2_offsets) == old_M - removed_count + N + 1

    # === physical layout ===
    b1_cap = round_up_16(len(new_block1_real))
    b1_padded = new_block1_real + bytes(b1_cap - len(new_block1_real))

    b2_real_size = len(new_block2_offsets) * 4
    b2_cap = round_up_16(b2_real_size)
    b2_raw = b''.join(struct.pack('<I', o) for o in new_block2_offsets)
    b2_padded = b2_raw + bytes(b2_cap - b2_real_size)

    b3_real_size = len(new_block3_real)
    b3_rel_offset = b1_cap + b2_cap

    new_proc_content = b1_padded + b2_padded + new_block3_real
    new_proc_size = round_up_16(PROC_HEADER + b3_rel_offset + b3_real_size)
    new_proc_content = new_proc_content + bytes(new_proc_size - PROC_HEADER - len(new_proc_content))
    assert len(new_proc_content) == new_proc_size - PROC_HEADER

    growth = new_proc_size - old_proc_size

    # === splice new procedure bytes into the file ===
    # the procedure's OWN header (its block1/block2/block3 ref table) is
    # copied from the old data but must be rewritten with the new
    # rel_offset/size values computed above before splicing - this was
    # the bug caught by the validation harness (see script/tests below):
    # the block ref-table entries live inside the procedure's own header
    # region, not in any ancestor's table, so they're easy to forget.
    new_header = bytearray(data[proc_start:proc_start + PROC_HEADER])
    _write_u32(new_header, b1['ref_table_pos'] - proc_start, 0)
    _write_u32(new_header, b1['ref_table_pos'] - proc_start + 4, len(new_block1_real))
    _write_u32(new_header, b2['ref_table_pos'] - proc_start, b1_cap)
    _write_u32(new_header, b2['ref_table_pos'] - proc_start + 4, b2_real_size)
    _write_u32(new_header, b3['ref_table_pos'] - proc_start, b3_rel_offset)
    _write_u32(new_header, b3['ref_table_pos'] - proc_start + 4, b3_real_size)

    new_proc_full = bytes(new_header) + new_proc_content
    assert len(new_proc_full) == new_proc_size
    new_data = bytearray(data[:proc_start]) + bytearray(new_proc_full) + bytearray(data[proc_start + old_proc_size:])

    # === propagate growth to every ref-table entry physically after this procedure ===
    def bump(entries, this_abs_offset, size_field_target, growth):
        for e in entries:
            if e['abs_offset'] == this_abs_offset:
                _write_u32(new_data, e['ref_table_pos'] + 4, size_field_target)
            elif e['abs_offset'] > this_abs_offset:
                _write_u32(new_data, e['ref_table_pos'], e['rel_offset'] + growth)

    bump(procs, proc_start, new_proc_size, growth)
    bump(objects, obj_start, obj['size'] + growth, growth)
    bump(groups, group_start, group['size'] + growth, growth)

    return bytes(new_data)


def insert_container_child(data: bytes, container_start: int, old_container_size: int, new_child_bytes: bytes,
                            at_index: int = None):
    """Insert one new child entry into a ref-table container that follows
    the generic group/object schema _parse_ref_table already reads:
    count:u32 @+0x10, header_size:u32 @+0x14, ref_size:u32 @+0x18,
    ref table @+0x20. Both the top-level script (children = groups) and
    every group (children = objects) use this exact schema,
    confirmed by scanning every SCRIPT/*.bin file in the ROM: at both
    levels, header_size == 0x20 + ref_size with zero exceptions (see
    docs/script_object_insertion.md) - i.e. there is never a gap between
    the end of the ref table and the first child's data.

    This generalizes the "append a new sibling at the end; never touch
    any EXISTING entry's rel_offset/size; only grow header_size/ref_size/
    count by one 8-byte slot" pattern that
    docs/party_add_remove_command_investigation.md's "新しいgroupを追加"
    experiment validated structurally at the top level, to any container
    of that shape - so the same code adds a new group to the top-level
    script OR a new object to a group.

    `old_container_size` is this container's OWN declared size, as
    recorded in ITS PARENT's ref table (a container does not know its
    own size - only its parent does) - needed to know where its content
    currently ends so the new child can be appended right after it.

    `at_index` (added 2026-08-30 to test whether the game's NPC-spawning
    logic is sensitive to WHERE in the ref table a new entry lands, not
    just whether it's structurally valid - see
    docs/script_object_insertion.md) selects which REF-TABLE SLOT the
    new entry occupies, i.e. its index among the container's children
    (0..count, where count = append at the end - the previous, only,
    behavior). This does NOT move any EXISTING child's physical bytes -
    only the 8-byte (rel_offset, size) tuples in the ref table are
    reordered, so every pre-existing child's abs_offset is unaffected;
    only its ref-table slot (and therefore its index) shifts down by one
    if it was at or after at_index. The new child's own bytes are always
    physically appended at the end of the container's content
    (immediately after old_container_size, exactly like before) -
    physical byte order does not have to match index order in this
    format (nothing here requires it to).

    Returns (new_data, growth): growth is how many bytes this container
    grew by in total (just len(new_child_bytes) if an existing spare slot
    was reused - see below - or 8 more than that if the ref table itself
    had to grow by one 8-byte slot). The CALLER is responsible for adding
    `growth` to this container's own size entry in the parent's ref
    table, and for shifting by `growth` the rel_offset of every sibling
    container physically positioned after it - exactly the `bump()`
    pattern replace_commands() above already uses for procedure growth,
    just one level up. See splice_object() for a worked example.

    IMPORTANT (found 2026-08-30, see docs/script_object_insertion.md):
    ref_size is frequently LARGER than count*8 - scanning every group in
    every SCRIPT/*.bin file found this in 11,499 of 13,180 groups (87%).
    This is the "power-of-2 slot allocator" padding
    docs/party_add_remove_command_investigation.md already noted (e.g.
    obj_count=1 but obj_ref_size=16 = 2 slots) - the trailing slots are
    already-reserved, all-zero, UNUSED ref-table entries.
    script_viewer.py's parsers (and presumably the game engine's own
    parsing, since these are the very same objects it successfully
    spawns) stop reading the ref table at the FIRST all-zero
    (rel_offset=0, size=0) pair, relying on that as a terminator rather
    than trusting `count` or `ref_size` alone. That means naively
    appending a brand new entry at `ref_start + ref_size` (i.e. past any
    such padding) would place it AFTER an all-zero pair the parser
    already treats as "end of list" - the new entry would never be seen
    by anything using that stop-at-first-zero convention, even though
    header fields and byte offsets would all still look internally
    consistent (this file's own _parse_ref_table skips zero pairs
    instead of stopping at them, which is why this bug did not surface
    in this module's own round-trip checks).

    So: if a spare (already-reserved, still-zero) slot exists right after
    the `count`'th real entry, this fills THAT slot in place instead -
    zero header growth, just one ref-table write + count+1. Only falls
    back to growing the ref table by a new 8-byte slot (the original
    implementation, still exactly correct on its own) when there is
    truly no spare slot left.

    IMPORTANT #2 (found 2026-08-30, real-hardware test by the user):
    scanning every group in every SCRIPT/*.bin file (13,180 groups)
    found that ref-table INDEX order and ascending REL_OFFSET (i.e.
    physical byte position) order are IDENTICAL in literally every
    single one, with zero exceptions, in the untouched ROM - this
    appears to be a real, previously-undocumented invariant of the
    format (not merely incidental), since it held with no exceptions at
    this scale. An earlier version of this function, when given
    `at_index` less than `count`, only reordered the ref-table's 8-byte
    (rel_offset, size) TUPLES - it left the new child's bytes physically
    appended at the very end regardless of `at_index`. That produces the
    ONLY group in the entire ROM where index order and rel_offset order
    disagree, and a user's real-hardware test of exactly that structure
    (inserting a copy at group3/index 9 in m01nk1f1.bin) was not picked
    up by the game - consistent with, though not proof of, the game
    relying on that ordering somewhere. This function now instead
    PHYSICALLY moves the new child's bytes to the position matching
    at_index (shifting every existing child at or after at_index forward
    by len(new_child_bytes), i.e. exactly the child-level equivalent of
    what replace_commands() does for commands), which preserves the
    invariant unconditionally, at every value of at_index.
    """
    data = bytearray(data)
    count = _read_u32(data, container_start + 0x10)
    header_size = _read_u32(data, container_start + 0x14)
    ref_size = _read_u32(data, container_start + 0x18)
    if header_size != 0x20 + ref_size:
        raise ValueError(
            f'container at {container_start}: header_size ({header_size}) != '
            f'0x20+ref_size ({0x20 + ref_size}) - insert_container_child assumes '
            'no gap between the ref table and the first child'
        )

    if at_index is None:
        at_index = count
    if not (0 <= at_index <= count):
        raise ValueError(f'at_index {at_index} out of range [0, {count}] for container at {container_start}')

    ref_start = container_start + 0x20
    old_entries = [
        (_read_u32(data, ref_start + i * 8), _read_u32(data, ref_start + i * 8 + 4))
        for i in range(count)
    ]

    # physical insertion point: right where the object currently at
    # at_index starts (or right after the last object's content, if
    # appending at the end) - this is what keeps index order and
    # physical order in agreement.
    insert_rel = old_entries[at_index][0] if at_index < count else (old_container_size - header_size)
    insert_abs = container_start + header_size + insert_rel
    new_len = len(new_child_bytes)

    # insert the new child's bytes physically at insert_abs FIRST (a
    # larger-or-equal absolute position than anywhere the ref table
    # itself will be touched below, since insert_rel >= 0) - doing the
    # larger-offset insert first means it's unaffected by the
    # ref-table-growth insert that may come after it.
    data[insert_abs:insert_abs] = bytes(new_child_bytes)

    new_entries = []
    for i, (rel, sz) in enumerate(old_entries):
        new_entries.append((rel, sz) if i < at_index else (rel + new_len, sz))
    new_entries.insert(at_index, (insert_rel, new_len))

    spare_slots = (ref_size // 8) - count
    if spare_slots > 0:
        for i, (rel, sz) in enumerate(new_entries):
            _write_u32(data, ref_start + i * 8, rel)
            _write_u32(data, ref_start + i * 8 + 4, sz)
        _write_u32(data, container_start + 0x10, count + 1)
        growth = new_len
        return bytes(data), growth

    # no spare slot: the ref table itself must grow by one 8-byte slot,
    # inserted right where the first child's data used to start (a
    # SMALLER-or-equal absolute position than insert_abs above, so doing
    # it second is safe - it shifts the content already inserted above
    # by +8, which is exactly compensated by header_size growing by +8
    # in the abs_offset formula, same as the original single-slot-grow
    # case).
    grow_pos = ref_start + ref_size  # == container_start + header_size
    data[grow_pos:grow_pos] = bytes(8)
    for i, (rel, sz) in enumerate(new_entries):
        _write_u32(data, ref_start + i * 8, rel)
        _write_u32(data, ref_start + i * 8 + 4, sz)

    _write_u32(data, container_start + 0x10, count + 1)
    _write_u32(data, container_start + 0x14, header_size + 8)
    _write_u32(data, container_start + 0x18, ref_size + 8)

    growth = 8 + new_len
    return bytes(data), growth


def remove_container_child(data: bytes, container_start: int, old_container_size: int, at_index: int):
    """Inverse of insert_container_child(): physically deletes the child
    currently at ref-table slot `at_index` from a container of the
    group/object schema (count:u32 @+0x10, header_size:u32 @+0x14,
    ref_size:u32 @+0x18, ref table @+0x20), used to implement the
    viewer's "このオブジェクトを削除" feature (added 2026-08-31 per user
    request; see docs/script_object_insertion.md).

    Deliberately keeps header_size/ref_size UNCHANGED - only `count` is
    decremented by one and the vacated ref-table slot (formerly holding
    the last real entry) is zeroed out. This mirrors the "spare slot"
    padding pattern insert_container_child() already knows how to reuse
    (see its docstring's "IMPORTANT" note - 87% of groups in the
    untouched ROM already have such zeroed trailing slots, and
    script_viewer.py's parser already stops at the first all-zero
    entry rather than trusting ref_size), so a group that had a deletion
    ends up looking exactly like a group that always had one fewer real
    object and some spare capacity - not like a structurally unusual
    shape. It also means a later insert into the same container can
    reuse that freed slot without growing the ref table again.

    Every other real entry keeps its own ref-table slot INDEX (no
    reordering) except that any entry physically positioned after the
    deleted child has its rel_offset shifted down by the deleted child's
    size - the same "index order == physical order" invariant
    insert_container_child()'s at_index path maintains is preserved here
    too, since removing bytes never changes relative ordering.

    Returns (new_data, growth) where growth is <= 0 (negative of the
    deleted child's size) - the CALLER must add `growth` to this
    container's own size entry in the parent's ref table, and shift by
    `growth` the rel_offset of every sibling container physically
    positioned after it, exactly like insert_container_child()'s caller
    does for a positive growth. See delete_object() for a worked
    example.
    """
    data = bytearray(data)
    count = _read_u32(data, container_start + 0x10)
    header_size = _read_u32(data, container_start + 0x14)
    ref_size = _read_u32(data, container_start + 0x18)
    if header_size != 0x20 + ref_size:
        raise ValueError(
            f'container at {container_start}: header_size ({header_size}) != '
            f'0x20+ref_size ({0x20 + ref_size}) - remove_container_child assumes '
            'no gap between the ref table and the first child'
        )
    if not (0 <= at_index < count):
        raise ValueError(f'at_index {at_index} out of range [0, {count}) for container at {container_start}')

    ref_start = container_start + 0x20
    old_entries = [
        (_read_u32(data, ref_start + i * 8), _read_u32(data, ref_start + i * 8 + 4))
        for i in range(count)
    ]

    removed_rel, removed_size = old_entries[at_index]
    remove_abs = container_start + header_size + removed_rel

    new_entries = [e for i, e in enumerate(old_entries) if i != at_index]
    new_entries = [
        (rel - removed_size, sz) if rel > removed_rel else (rel, sz)
        for rel, sz in new_entries
    ]

    del data[remove_abs:remove_abs + removed_size]

    for i, (rel, sz) in enumerate(new_entries):
        _write_u32(data, ref_start + i * 8, rel)
        _write_u32(data, ref_start + i * 8 + 4, sz)
    # zero out the now-vacated last real-entry slot so it reads as a
    # spare/padding slot, not a stale duplicate entry.
    _write_u32(data, ref_start + (count - 1) * 8, 0)
    _write_u32(data, ref_start + (count - 1) * 8 + 4, 0)

    _write_u32(data, container_start + 0x10, count - 1)

    growth = -removed_size
    return bytes(data), growth


def delete_object(dst_data: bytes, target_group_idx: int, target_obj_idx: int) -> bytes:
    """Delete an existing scriptobject (target_group_idx/target_obj_idx)
    entirely from dst_data via remove_container_child() - the "object丸ご
    と削除" operation added 2026-08-31 per user request. Every OTHER
    object in the same group keeps its own index; only objects physically
    positioned after the deleted one (and the group's own declared size,
    and any group physically positioned after this group) shift down by
    the deleted object's size - exactly the mirror image of
    splice_object()'s growth propagation.

    NOTE: this only removes the object's bytes from the SCRIPT file; it
    does not know whether some other object's OBJECT_TOGGLE command
    (opcode 0x10005, see docs/script_object_insertion.md) or any other
    command elsewhere references this object's (now-shifted-or-gone)
    index. Deleting an object that something else still points at by
    index is the caller's responsibility to check first (e.g. via the
    viewer's command search) - this function only guarantees the result
    is structurally valid, not that nothing else in the file logically
    depended on the deleted object's identity or position.
    """
    top_header_size = _read_u32(dst_data, 0x14)
    groups = _parse_ref_table(dst_data, 0, 0x10, 0x18, top_header_size)
    target_group = groups[target_group_idx]

    new_data, growth = remove_container_child(
        dst_data, target_group['abs_offset'], target_group['size'], at_index=target_obj_idx
    )
    new_data = bytearray(new_data)

    for e in groups:
        if e['abs_offset'] == target_group['abs_offset']:
            _write_u32(new_data, e['ref_table_pos'] + 4, target_group['size'] + growth)
        elif e['abs_offset'] > target_group['abs_offset']:
            _write_u32(new_data, e['ref_table_pos'], e['rel_offset'] + growth)

    return bytes(new_data)


def splice_object(
    dst_data: bytes,
    target_group_idx: int,
    src_data: bytes,
    src_group_idx: int,
    src_obj_idx: int,
    new_tag: str = None,
    field_overrides: dict = None,
    at_index: int = None,
) -> bytes:
    """Copy an entire existing scriptobject (its header, its own
    proc-ref table, its 48-byte NPC-placement metadata block, and every
    procedure it owns - the full byte range recorded for it in its
    group's object ref table) and insert it as a brand-new object into
    target_group_idx's object list in dst_data, via
    insert_container_child(). By default (at_index=None) it's appended
    at the end (the object list's new highest index); pass at_index to
    insert it at a specific position instead (0..current object count),
    shifting every existing object at or after that index up by one -
    added 2026-08-30 to test whether the game's NPC-spawning logic cares
    about WHERE in the list a new object lands, not just whether the
    structure is valid (a plain append at the end was tested first and
    not picked up by the game - see docs/script_object_insertion.md).

    src_data/src_group_idx/src_obj_idx locate the template object to
    copy; dst_data/target_group_idx locate where the copy is inserted.
    They may refer to the same file (duplicate an object within one
    file, into the same or a different group) or different files
    (transplant an object from one SCRIPT file into another) - both are
    just byte buffers read independently, so there is no special-casing
    needed for either case.

    new_tag optionally overwrites the copy's 16-byte tag (ASCII,
    truncated to 16 bytes, zero-padded).

    field_overrides optionally overwrites fields in the copy's 48-byte
    NPC-placement block (see webapp/server.py's _NPC_PLACEMENT_FIELD_DEFS
    for known offsets/types), as {field_offset: (value_type, value)}
    where value_type is 'u32', 'i32', or 'f32'.

    This deliberately never invents new object content from scratch - it
    only ever clones bytes that already parse as a valid object
    somewhere in the ROM, sidestepping the need to hand-derive the full
    internal object layout (proc-ref table / metadata block relationship)
    from first principles. See docs/script_object_insertion.md for what
    is and isn't validated about objects added this way: structural
    validity is (verify_script_structure.py passes), but whether the
    game engine actually invokes a newly appended object at runtime is a
    separate, still-open question (see
    docs/party_add_remove_command_investigation.md's "残る課題" note).
    """
    top_header_size_src = _read_u32(src_data, 0x14)
    src_groups = _parse_ref_table(src_data, 0, 0x10, 0x18, top_header_size_src)
    src_group = src_groups[src_group_idx]
    src_group_header_size = _read_u32(src_data, src_group['abs_offset'] + 0x14)
    src_objects = _parse_ref_table(src_data, src_group['abs_offset'], 0x10, 0x18, src_group_header_size)
    src_obj = src_objects[src_obj_idx]
    obj_bytes = bytearray(src_data[src_obj['abs_offset']:src_obj['abs_offset'] + src_obj['size']])

    obj_header_size = _read_u32(obj_bytes, 0x14)

    if new_tag is not None:
        tag_bytes = new_tag.encode('ascii')[:0x10]
        obj_bytes[0:0x10] = bytes(0x10)
        obj_bytes[0:len(tag_bytes)] = tag_bytes

    if field_overrides:
        for field_offset, (value_type, value) in field_overrides.items():
            abs_off = obj_header_size + int(field_offset)
            if value_type == 'f32':
                struct.pack_into('<f', obj_bytes, abs_off, float(value))
            elif value_type == 'u32':
                struct.pack_into('<I', obj_bytes, abs_off, int(value))
            elif value_type == 'i32':
                struct.pack_into('<i', obj_bytes, abs_off, int(value))
            else:
                raise ValueError(f'unsupported value_type {value_type!r}')

    top_header_size_dst = _read_u32(dst_data, 0x14)
    groups = _parse_ref_table(dst_data, 0, 0x10, 0x18, top_header_size_dst)
    target_group = groups[target_group_idx]

    new_data, growth = insert_container_child(
        dst_data, target_group['abs_offset'], target_group['size'], bytes(obj_bytes), at_index=at_index
    )
    new_data = bytearray(new_data)

    for e in groups:
        if e['abs_offset'] == target_group['abs_offset']:
            _write_u32(new_data, e['ref_table_pos'] + 4, target_group['size'] + growth)
        elif e['abs_offset'] > target_group['abs_offset']:
            _write_u32(new_data, e['ref_table_pos'], e['rel_offset'] + growth)

    return bytes(new_data)


def replace_object(
    dst_data: bytes,
    target_group_idx: int,
    target_obj_idx: int,
    src_data: bytes,
    src_group_idx: int,
    src_obj_idx: int,
    new_tag: str = None,
    field_overrides: dict = None,
) -> bytes:
    """Overwrite an EXISTING object's full byte content
    (target_group_idx/target_obj_idx in dst_data) with a clone of another
    object (src_group_idx/src_obj_idx from src_data, possibly a
    different file) - the "既存objectの乗っ取り" operation from
    docs/script_object_insertion.md.

    Added 2026-08-30 after real-hardware testing showed that
    splice_object() (which APPENDS a brand-new object at the end of a
    group, leaving every existing index untouched) does not get spawned
    by the game at all - whatever decides which objects in a group
    become visible NPCs apparently doesn't just iterate obj_count. The
    next experiment is to instead overwrite an object index the game
    DOES already instantiate, to see whether the new content then runs.

    Unlike splice_object(), the target object's ref-table INDEX/POSITION
    is preserved (it doesn't become a new entry) - only its
    rel_offset/size are updated, exactly like any size-changing replace:
    growth (positive or negative) is propagated to every sibling
    object/group physically positioned after it, mirroring
    replace_commands()'s bump() one level up.
    """
    top_header_size_src = _read_u32(src_data, 0x14)
    src_groups = _parse_ref_table(src_data, 0, 0x10, 0x18, top_header_size_src)
    src_group = src_groups[src_group_idx]
    src_group_header_size = _read_u32(src_data, src_group['abs_offset'] + 0x14)
    src_objects = _parse_ref_table(src_data, src_group['abs_offset'], 0x10, 0x18, src_group_header_size)
    src_obj = src_objects[src_obj_idx]
    obj_bytes = bytearray(src_data[src_obj['abs_offset']:src_obj['abs_offset'] + src_obj['size']])

    obj_header_size = _read_u32(obj_bytes, 0x14)
    if new_tag is not None:
        tag_bytes = new_tag.encode('ascii')[:0x10]
        obj_bytes[0:0x10] = bytes(0x10)
        obj_bytes[0:len(tag_bytes)] = tag_bytes
    if field_overrides:
        for field_offset, (value_type, value) in field_overrides.items():
            abs_off = obj_header_size + int(field_offset)
            if value_type == 'f32':
                struct.pack_into('<f', obj_bytes, abs_off, float(value))
            elif value_type == 'u32':
                struct.pack_into('<I', obj_bytes, abs_off, int(value))
            elif value_type == 'i32':
                struct.pack_into('<i', obj_bytes, abs_off, int(value))
            else:
                raise ValueError(f'unsupported value_type {value_type!r}')

    top_header_size_dst = _read_u32(dst_data, 0x14)
    groups = _parse_ref_table(dst_data, 0, 0x10, 0x18, top_header_size_dst)
    target_group = groups[target_group_idx]

    target_group_header_size = _read_u32(dst_data, target_group['abs_offset'] + 0x14)
    objects = _parse_ref_table(dst_data, target_group['abs_offset'], 0x10, 0x18, target_group_header_size)
    target_obj = objects[target_obj_idx]

    old_size = target_obj['size']
    new_size = len(obj_bytes)
    growth = new_size - old_size

    data = bytearray(dst_data)
    obj_start = target_obj['abs_offset']
    data[obj_start:obj_start + old_size] = obj_bytes

    # this object's own ref-table entry keeps its rel_offset (its
    # physical start didn't move - only what comes after it did); only
    # its declared size changes.
    _write_u32(data, target_obj['ref_table_pos'] + 4, new_size)

    # shift every OTHER object in the same group physically after this one
    for e in objects:
        if e['index'] == target_obj['index']:
            continue
        if e['abs_offset'] > obj_start:
            _write_u32(data, e['ref_table_pos'], e['rel_offset'] + growth)

    # propagate to this group's own declared size + every sibling group
    # physically positioned after it
    for e in groups:
        if e['abs_offset'] == target_group['abs_offset']:
            _write_u32(data, e['ref_table_pos'] + 4, target_group['size'] + growth)
        elif e['abs_offset'] > target_group['abs_offset']:
            _write_u32(data, e['ref_table_pos'], e['rel_offset'] + growth)

    return bytes(data)


def splice_procedure(
    data: bytes,
    group_idx: int,
    obj_idx: int,
    proc_tag: str,
    insert_after_cmd_idx: int,
    new_indent_bytes: bytes,
    new_block3_bytes: bytes,
    new_cmd_offsets: list,
) -> bytes:
    """Backward-compatible pure-insertion wrapper around replace_commands()
    - inserts new commands right after insert_after_cmd_idx, removing
    nothing. Kept because most of this session's patch scripts call it
    by this name; new code (e.g. the viewer's edit/delete API) should
    call replace_commands() directly for the general case."""
    boundary = insert_after_cmd_idx + 1
    return replace_commands(
        data, group_idx, obj_idx, proc_tag,
        start_idx=boundary, end_idx=boundary,
        new_indent_bytes=new_indent_bytes,
        new_block3_bytes=new_block3_bytes,
        new_cmd_offsets=new_cmd_offsets,
    )
