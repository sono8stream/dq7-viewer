# SCRIPT File (Event Script) Format

The structure of `RomFS/SCRIPT/*.bin` (bytecode describing NPC dialogue and
event processing), and the list of opcodes identified so far.

## Container Hierarchy and Header Schema

A file has a structure of 4 nested container levels:

```
script file
└─ group[]
    └─ object[]
        └─ procedure[initialize / execute / terminate / (metadata block)]
```

The top level, group, and object levels share a common header schema.

```
+0x00: tag (16 bytes, ASCII, remainder zero-filled)
+0x10: count (u32)         # number of child elements
+0x14: header_size (u32)   # this value + rel_offset = the child element's absolute offset
+0x18: ref_size (u32)      # actual byte size of the reference table
+0x20: ref table[count]    # array of (rel_offset: u32, size: u32), 8 bytes per entry
```

Confirmed invariants (hold without exception across the entire ROM, except
for a few procedure-header entries with a corrupted tag, "BAD PROC TAG"):

- `header_size == 0x20 + ref_size` (no gap between the end of the reference
  table and the first child element's data).
- The ref-table often reserves more slots (`ref_size`) than `count` (likely
  a trace of a power-of-2-unit allocator); unused surplus slots are always
  `(rel_offset=0, size=0)`. A parser reads the reference table from the
  start and treats hitting `(0,0)` as the end of the list.
- The ref-table's index order always matches the physical byte layout order
  of the child elements (ascending).

The procedure's own ref table (4 slots within one object: anonymous
metadata/initialize/execute/terminate) has `block_count=3`, but always
reserves `block_ref_size=32` (worth of 4 slots), with the 4th, unused slot
always `(0,0)`.

## Internal Procedure Structure (block1/block2/block3) and Alignment Rules

Each procedure (initialize/execute/terminate) internally has 3 blocks.

```
procedure header
  +0x00~: block1 (indent array, 1 byte per command = if/elseif nesting depth)
  block2 (cumulative offset array, 4 bytes × (command count + 1))
  block3 (raw command byte stream)
```

- The size of `block1` = the actual command count (1 byte/command).
- The **physical region** of `block1` reserves `round_up_16(block1 actual
  size)` (rounded up to a 16-byte unit).
- `block2`'s `rel_offset` always starts at the position
  `round_up_16(block1 actual size)`.
- `block3`'s `rel_offset` always starts at the position
  `block2's rel_offset + round_up_16(block2 actual size)`.
- The procedure's own declared size is
  `round_up_16(block1's physical end + block2's physical end + block3 actual size)`.

**Safety rules for editing (verified on real hardware)**:

1. Increasing a container's (group/object/procedure, any of them) own
   declared size by adding padding that doesn't belong to an existing child
   element is always safe, regardless of hierarchy level.
2. The dangerous case is only when a procedure's block1/block2/block3 change
   size due to actual data growing/shrinking. If this is computed with a
   naive linear shift instead of following the round_up_16 rules above, it
   freezes on real hardware. If the rules are followed, inserting/deleting
   any command can be done safely.
3. Insertion into the block1 array must place the value at the logical
   position corresponding to the insertion point (not appended at the end).
4. For any of the group/object/procedure ref-tables, a new entry must always
   be added immediately after existing entries (at the end of the list, or
   into an empty `(0,0)` slot), and the `rel_offset`/`size` values of
   existing entries must not be changed. It is only operations that change
   the value of an existing entry (a size change from actual data
   growing/shrinking) that cause the freeze.
5. The ref-table's index order and physical layout order must always be
   kept consistent (swapping index order while placing the physical layout
   only at the end is an implementation that has not been verified on real
   hardware and should be avoided, as it produces a structural difference).

## Object Metadata Block (head of the proc-ref table, 48 bytes)

The "anonymous" entry (always 48 bytes) at the head of a scriptobject's
proc-ref table is not a procedure, but a metadata block tied to the object
itself. Interpreted as `int32[]`:

| Offset | Type | Contents |
| --- | --- | --- |
| 0 | u32 | a value matching the speaker control code (speaker ID in `#NNNN` form) |
| 4 | u32 | small sequential value, purpose unknown |
| 8,12,16 | f32×3 | purpose unknown (possibly coordinates, but unverified; a separate region from the NPC placement block below) |

## NPC Placement Info Block (right after the object header, 48 bytes)

Right after each scriptobject's header there is a fixed-size, fixed-offset
48-byte region that is outside the scope of the ref-table's
insertion/deletion logic (can be overwritten directly in 4-byte units).

| Offset | Type | Contents | Verification status |
| --- | --- | --- | --- |
| 0 | u32 | purpose unknown (sequential value) | unconfirmed |
| 4 | u32 | the NPC's display model/actor ID | **confirmed** (rewriting it changes the displayed model on real hardware) |
| 8 | u32 | purpose unknown (type flag or facing) | unconfirmed |
| 12 | f32 | map coordinate X | **confirmed** (rewriting it on real hardware changes the display position) |
| 16 | f32 | map coordinate Y (height) | **confirmed** |
| 20 | f32 | map coordinate Z | **confirmed** |
| 24-44 | — | always 0 (unused/reserved region) | — |

Entries where the coordinates are all `(0,0,0)` (possibly special objects
with no physical placement, such as ones dedicated to triggering dialogue)
are treated as low confidence.

## Opcode Encoding and the Generic "Once / Repeats" Mechanism

Every opcode is a 32-bit value split into two independent 16-bit fields:
`(high16 << 16) | low16`. Across the entire ROM, `low16` is the command
subtype (one of 236 values, see below) and `high16` only ever takes the
values `0x0000` (condition/branch primitives such as `IF_FLAG`/`IF_TALKED_TO`),
`0x0001`, or `0x0003`.

This has been confirmed from the executable code (`rom/exefs/code.decompressed.bin`):

- The generic per-command dispatcher `script::CommandFunction` reads only
  the **low 16 bits** (a single `ldrh` halfword load) and uses it directly
  as a 236-entry jump-table index to reach the handler for that command
  subtype. `high16` is never read at dispatch time.
- Each handler then calls the shared `ScriptCommand::exec` state machine,
  passing the absolute address of the opcode word itself (inside the
  script file's `block3` bytes) as the "instance" pointer. `ScriptCommand::exec`
  treats **byte offset +2 of that same opcode word** (i.e. the low byte of
  `high16`, since the format is little-endian) as a mutable run-time status
  byte, OR-ing in bits `0x10` (in progress) and `0x40` (finished) as
  execution proceeds. Because `0x01` and `0x03` both have bit `0x01` set,
  and `0x10`/`0x40` never collide with `0x01`/`0x02`, the original authored
  `high16` value survives alongside the run-time bits.
- `siren::GetScriptCommandClearFlag` reads exactly bit `0x02` of that byte —
  i.e. whether `high16` was originally `0x0003` rather than `0x0001`.
  `ScriptTree::recursiveTree` calls this once a node's execution finishes;
  if it's true, it calls `siren::ClearScriptCommandStatus` (`status &= ~0x50`),
  which clears the "in progress"/"finished" bits while leaving the original
  `0x01`/`0x03` byte intact, allowing that exact command to run again from
  scratch the next time its branch is re-entered (e.g. the next time the
  NPC is talked to). If it's false (`high16 == 0x0001`), the finished bit is
  never cleared, so the command silently no-ops on every subsequent visit.

**[Corrected 2026-10-03]** The paragraph above describes the original
(incorrect) understanding, which assumed "once vs. repeats" was a per-command
property. On-device testing (several purpose-built test NPCs with different
command orderings) showed the real mechanism is different:

> **Only the `high16` of the *last* command physically placed inside an
> if/elseif block matters. It decides whether the completion status of
> *every* sibling command in that block gets reset as a group when the block
> finishes.**
> - If the last command is `0x0003`: the whole block's state is reset, so
>   **every command in it — including any `0x0001` ones earlier in the
>   block — runs again in full the next time the branch is re-entered.**
> - If the last command is `0x0001`: the block's state is never reset, so
>   **even an `0x0003` command earlier in the block never runs again either.**

In other words, `high16` is not a per-command "once vs. repeats" flag at
all — it only has an effect when it's on the *last* command of a block,
where it decides whether that whole block resets on the next visit. A
`high16` value on a command earlier in the block has no effect on that
command's own re-execution; the block's fate is always decided by its last
command. This implies a concrete authoring constraint: to make a
conversation replay in full every time the player talks, the *last* command
in the branch must be `0x0003`, regardless of what the earlier commands are
tagged with.

## Multi-Frame Blocking Commands: Re-Entry Timing

`ScriptTree::recursiveTree` (the interpreter that walks a procedure's
command tree) only re-walks a branch's body from its start when the
branch's own guard condition (e.g. `IF_TALKED_TO`) evaluates true again —
which, for a player-interaction trigger, means the next time the player
interacts (talks) again, not continuously every frame. This has a
user-visible consequence for any command that spans multiple frames while
waiting on player input *other than* simply dismissing a message box — most
notably a choice menu such as `CHOICE_MENU`: a UI system outside the script
engine drives the menu's cursor and detects the player's final selection
every frame, but the *script* side only re-checks that command's completion
(`isEnd()`) when the tree is re-walked. Concretely, for `IF_TALKED_TO →
CHOICE_MENU → next_command`:

- Selecting an option in the menu does **not** make `next_command` run in
  that same conversation — the script never re-visits `CHOICE_MENU` to
  notice the selection finished, because `IF_TALKED_TO` doesn't fire again
  until the player initiates a new interaction.
- Talking again re-triggers `IF_TALKED_TO`, the tree is walked from the top,
  `CHOICE_MENU` is found already finished (its `isEnd()` was true all
  along), and the walk falls straight through to `next_command` in that same
  pass.

Verified on real hardware (2026-10-03) with a purpose-built test object
mirroring a real `CHOICE_MENU` → warp sequence (see `group3`/`obj9` in
`SCRIPT/m01nk1f1.bin` for an authored example of this exact pattern, where
the command after `CHOICE_MENU` only ever fires on the visit *after* the one
where the choice was made). This is a property of the generic interpreter,
not specific to `CHOICE_MENU` — it should apply to any command that can take
more than one frame to finish without itself being the thing the player
repeatedly presses a button to re-check.

## Confirmed Opcode List

| opcode | name | parameters | meaning | status |
| --- | --- | --- | --- | --- |
| `0x00000003` | `IF_FLAG` | `[type, flag_id, expected_value]` | flag branch. `type` observed to be 0/1/2. When type is 2 it is non-persistent (cleared on every boot); 0/1 appear to be persisted to the save | confirmed |
| `0x0000000f` | `IF_TALKED_TO` | `[variant]` | branch condition that becomes true when talked to. A standard pattern placed at the start (#0) of almost every NPC's `execute` procedure. variant=0 in the vast majority of cases (meaning of 1,2 unconfirmed) | confirmed |
| `0x00000070` | `IF_KO_STATUS` | `[character_id, mode]` | checks whether the given character is alive/dead. mode=0 branches on "when alive", mode=1 on "when incapacitated" | confirmed |
| `0x00010004` | `SET_FLAG` (generic write mid-branch) | `[type, flag_id, value]` | writes a flag. Same (type, id) space as `IF_FLAG` | confirmed |
| `0x00030004` | `SET_FLAG` (branch-end marker) | `[type, flag_id, value]` | almost always called at the very end of an if/elseif block, with the value almost always 1. Used as a "this event branch has been executed" completion marker. Being physically last in its block, its `high16=0x0003` is exactly what causes the *whole preceding block* to have its completion state reset on every re-entry (see "Opcode Encoding..." above) — this is a deliberate, idiomatic use of the block-reset mechanism, not an independent property of this one command | confirmed (statistically supported; `high16` mechanism confirmed from code and on-device testing) |
| `0x00010005` | `OBJECT_TOGGLE` | `[target_index]` | toggles the display on/off of "the (target_index+1)-th object" within the same group. An object merely being counted in `obj_count` does not make it display automatically; explicit activation via this command is required | confirmed (verified on real hardware) |
| `0x00010009`/`0x00030009` etc., the MSG family (low16 is `0x0007`/`0x0009`/`0x000a`/`0x000b`/`0x000d`/`0x000e`) | message display | `[msgID, count, ...]` | `low16` is the command subtype (a difference in display form; e.g. `0x0007`/`0x0009` share the same display form but differ in "whether the speaker faces the player (`0x0009`) or not (`0x0007`)"). `high16` (`0x0001`/`0x0003`) only matters when the message is the *last* command in its if/elseif block, per the block-reset mechanism described above; when a dialogue's final message is `0x0003`, the whole preceding block (including any `0x0001`-tagged messages earlier in it) replays in full on every subsequent talk, whereas `0x0001` on the final message leaves the whole block permanently "done" after the first run. Across a full-ROM check, 99.5% of `repeats`(`0x0003`) instances are inside an `IF_TALKED_TO` branch, and nearly 100% of `once`(`0x0001`) instances are outside it — a confirmed design tendency | confirmed (verified on real hardware; `high16` mechanism confirmed from code and on-device testing) |
| `0x00010014` | `SET_POSITION` | roughly `[0, x(f32), z(f32)]` (details unconfirmed) | presumed to be a command that dynamically places a target at given coordinates. There are real examples where it outputs coordinates matching the confirmed x/y/z values of the NPC placement block | semi-confirmed (hypothesis from matching bit patterns, not verified on real hardware) |
| `0x00010022`/`0x00010023` | `ADD_PARTY_MEMBER`/`REMOVE_PARTY_MEMBER` | `[character_id, mode]` | mode=0 adds the given character to the party (formation array, fixed at 6 slots), mode≠0 removes them. Removal calls the native implementation `PlayerParty::delMember` (linearly scans the 6 slots, zeroes the target, and compacts by shifting subsequent nonzero elements forward). The engine has absolutely no safeguard such as a zero-member check or exclusion of specific characters | confirmed (both addition and removal backed by both real-hardware and real-data evidence) |
| `0x00010025` | `CONFIRM_YESNO` | `[var_type, var_id, cancel_value]` | shows a yes/no confirmation prompt and writes the result into flag(var_type, var_id) | confirmed (extensive usage across the full ROM) |
| `0x0001001f` | `MAP_WARP` | `[floor_id, x(f32), y(f32), z(f32), facing, flag5]` | warps to the coordinates of the given floor ID. `floor_id` can be resolved via the correspondence table in `LEVELDATA/dq7_floor_list.dat` (see "Related Data Files" below). The meaning of facing (presumed to be one of 4 directions) and flag5 (0/1) is unconfirmed | semi-confirmed (the meaning of the arguments is supported by a full-ROM scan; actually executing the warp on real hardware is unverified) |
| `0x00010064` | `PARTY_SLOT_ACTIVATE` (tentative name) | `[slot, value]` | presumed to be an operation related to a formation slot. Confirmed that it alone does not cause any significant visible change in formation behavior on real hardware | tentative name (effect unconfirmed) |
| `0x00010093` | `PARTY_SLOT_QUERY` (tentative name) | `[type, slot]` | presumed to be a formation-slot state query (for reading/branching). Often referenced multiple times within a single process, suggesting it's a read operation rather than a one-time write | tentative name (effect unconfirmed) |
| `0x00010096` | `JOIN_BANNER` (also called `FANFARE_MSG`) | `[msgID, count, style]` | displays a jingle-accompanied message banner such as "X has joined the party" | confirmed |
| `0x000100c5` | `CHOICE_MENU` (`CmdOpenPartyChangeMenu`) | `[msgID, p1, flag_slot2..flag_slot6]` | a multi-choice menu for changing the party formation. Building the candidate list (onOpen) dynamically scans the current party, but resolving the selection result (onResult) is an implementation hardcoded to 4 specific character IDs and does not support arbitrary characters. See a separate document for details. **The command physically following this one in the same block does not run until the *next* time the branch is re-entered** (see "Multi-Frame Blocking Commands" above) — e.g. a warp placed right after it only happens on the visit after the one where the choice was made | confirmed |

## Related Data Files

- `LEVELDATA/dq7_floor_list.dat`: a floor-ID ⇔ map-code correspondence
  table. 16-byte header (count, rec_size, etc.), fixed 16-byte records, the
  table starts at offset `0x20`.
  - `+0x00` u32: unused (always 0 in the observed range)
  - `+0x04` u16: floor ID (corresponds to `MAP_WARP`'s param[0])
  - `+0x06` u16: group number (a sequential number per map series)
  - `+0x08` char[8]: map code name (NUL-terminated)
  - Records with floor IDs in the 5000s are all for divided world-map
    tiles.
  - The floor ID does not match the line number in `MAP/_list.txt`. It must
    always be resolved via this table's `+0x04`.

## Generic N-Choice Menu Commands (the `CmdSelectMenu`/`CmdSelectMenu1` family)

On the executable-code side, there exist generic choice-menu implementation
classes that carry no notion of character at all.

- `CmdSelectMenu` (4 choices) / `CmdSelectMenu1` (5 choices): looks only at
  the chosen cursor position (0-indexed) and sets the corresponding
  script-side flag ID directly. The parameters take the form
  `[..., flag0, flag1, ...]`, with as many flag IDs trailing as there are
  choices.
- `CmdSelectMenu2` (6 choices): a more complex implementation that branches
  not on cursor position but by comparing each candidate's own "value"
  field against a threshold.
- In the only usage example that could be confirmed (opcode `0x000100e4`,
  2 occurrences across the full ROM), the display text for each choice was
  not individually embedded in the message text; all branches after the
  choice converged on the same following text, and the only difference was
  internal numeric parameters (camera coordinates, destination floor ID,
  etc.). In other words, this mechanism is not designed so that "writing
  free text in the message body makes it the choice label as-is."
- The actual opcode number(s) corresponding to `CmdSelectMenu`/`CmdSelectMenu1`
  are unconfirmed.

## Dead Code (empty implementations)

- `CmdSetPartyQuitToAzuke`: even combining all 4 methods — initialize/
  execute/isEnd/destructor — totals 20 bytes (just an immediate `bx lr`
  return; isEnd unconditionally returns 1 = complete). The class
  composition carried over from the previous installment (the DQ4-6 series)
  remains, but in DQ7 the processing body has been replaced with an empty
  one.
- `CmdSpecialMenu`: both initialize and isEnd are empty implementations.
