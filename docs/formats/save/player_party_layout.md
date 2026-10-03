# Party-Related Memory/Save Structure

## Fixed arrays in the save

Within the save data, the following two arrays are both **fixed at 6
elements**, with a different section immediately adjacent right after them
(no room for expansion).

- **Party (formation) array**: offset `0x0510`, elements are `u32`
  (character ID) × 6. Right after `0x0510 + 6*4 = 0x0528` comes the Gold
  field, contiguously.
- **Charactors (status body) array**: offset `0x0C80`, element stride
  `0x1EC` (3DS version) × 6. Right after `0x0C80 + 6*0x1EC = 0x1808` comes
  the header of the `OPTN` (options) section, contiguously.
- Slot `i` of the Charactors array has been confirmed, from the byte
  contents of actual save files, to correspond to character ID `i+1` in the
  PLAYER_NAME system (0 = ID1 … 5 = ID6).

## Character ID space

- The ID→name mapping via `MENULIST/party_menu.txt` / `TEXT/PLAYER_NAME.txt`
  is used consistently throughout the game. IDs 1–6 are the fixed main-story
  playable slots.
- IDs 7 and 8 are temporary-join characters that do not have a dedicated
  slot in the save's Charactors array.

## Corresponding functions on the ExeFS side (ARM, 32-bit fixed-length
instructions, file offsets are base-game-relative)

- `PlayerParty::addMember` (file offset `0x188c08`): simply writes the
  character ID into an empty slot of the formation array (fixed 6 elements,
  loop terminated by `cmp r0,6`). Does not generate or reference status
  values.
- `fcn.0018aaf4` (the body of `PlayerManager::addPlayer`, called at the tail
  end via a debug flag): shifts existing members' coordinates, initializes
  appearance, rebuilds the formation, and calls
  `PlayerManager::setPartyControl`, but does not write the status values
  themselves.
- `PlayerDataContainer::initialize` (file offset `0x12ce18`): loops from
  `r4=1` to below `r4=46` (id = 1–45), calling
  `PlayerData::setup(this=slot, arg2=id, jobId=id)` for each ID. The slot
  address is `this + (id*133)*8 + 8` (i.e. an array spaced 1064 bytes per
  character). This loop **always runs for all characters regardless of
  whether a save exists**.
- `PlayerDataContainer::deserialize` (file offset `0x23e43c`): uses the same
  slot-address formula, but the loop range is **id = 1–6 only**
  (`cmp r4,7`; `cmp r4,6` in the unmodified version). It overwrites only
  this range with values from the Charactors block in the save (stride
  `0x1ec`).
- Combining the above two functions: all of id = 1–45 are first built from
  values derived from `character_init_data.dat`, after which only id = 1–6
  are overwritten with save values. From id = 7 onward, the values derived
  from `character_init_data.dat` continue to be used as-is.

## `PlayerData::setup` (file offset `0x223ab4`)

- Arguments `(this, arg2, jobId)`. `jobId` is stored as 1 byte into
  `this+0x14` immediately after the call.
- At the start, there is a branch on whether the given ID value is 1–6; only
  for 1–6 does it go through additional initialization processing (4
  unanalyzed function calls such as `fcn.19b2fc`). id = 7 and above skip
  this additional initialization and receive only the common processing.
- In the common processing, multiple fields are copied into `this` from the
  corresponding record of `dq7_character_init_data.dat` (table descriptor
  `0x3eed28`/`0x672f98`, via the generic table-lookup helper
  `fcn.001949d8`).
- At the end of the function, using a third table (descriptor
  `0x3ef540`/`0x679994`, indexed by job ID), record fields `+0x3d` (HP
  multiplier) and `+0x3e` (MP multiplier, processed the same way), it
  performs the fixed-point computation
  `final value = floor(base value × multiplier ÷ 10)` against the base
  values `this` already holds (`+0x24` = HP base, `+0x2a` = MP base), and
  passes the result to `HaveStatus::setHpMax` (file offset `0x123bf0`) /
  `setMpMax` (`0x123b98`).
- It has been confirmed via actual-data comparison that `+0x24`/`+0x2a` (HP/MP
  base) themselves are filled directly from fields inside the
  `dq7_character_init_data.dat` record (described below; see
  "character_init_data.dat").

## Display-side constraint (`CommonStatusWindowGroup::resetChildren`, file
offset `0x144a58`)

- The status menu's display loop is fixed at 4 iterations, `r4=0–3`
  (`cmp r4,4`). This is a fixed count against formation slot numbers; there
  is no branch inside this function that judges by character ID or
  character type. Whether a slot is shown is determined purely by comparing
  "number of living formation members" against the slot number.

## A separate `id<7` hardcoding (`fcn.0021a220`, file offset `0x21a220`)

- There is processing that reads values from 4 fixed global addresses
  (`0x542938`–`0x542944`), adopts only the ones that are nonzero and less
  than 7, and passes them to `PlayerParty::reorder` (`0x188c4c`). This is a
  separate system from the usual formation processing, and is likely
  handling a special forced party composition (estimated to be related to
  `dq7_special_party.dat`), unrelated to the normal status-menu display path
  described above.

## Unconfirmed / unresolved points

- The exact meaning of `arg2` in `PlayerData::setup`.
- Exactly where within `setup()` the writes to `+0x24`/`+0x2a` occur (narrowed
  down to very likely being an unanalyzed internal region rather than
  outside the function).
- The complete path by which a field equivalent to `category_code` feeds
  into the "controllable / AI character" determination (a partial
  relationship has been confirmed, but the main branch itself has turned
  out to be controlled by a different factor — bit relationships on the
  formation slot number — rather than a simple 1:1 branch).
