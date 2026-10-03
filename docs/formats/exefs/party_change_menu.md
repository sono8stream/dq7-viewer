# Internal structure of the party-change menus (ExeFS side)

Target classes: `CmdOpenPartyChangeMenu` (a script-VM command implementation
class), `PartyChangeMenu`, `TownFormationMenu` (all identified from
`FuncSearch.txt` symbols). File offsets are relative to the base game
(32-bit ARM fixed-length instructions).

## Note on premises / confidence

The correspondence between `CmdOpenPartyChangeMenu` and being the handler
for a specific script-side opcode is based on circumstantial evidence (the
class name and argument structure match); the actual runtime dispatch path
from the opcode number to this function has not been directly confirmed.
On the other hand, the fact that the three functions discussed below —
`CmdOpenPartyChangeMenu`, `PartyChangeMenu::onOpen`, and
`PartyChangeMenu::onResult` — consistently read and write the same
structure (same `this` pointer, same field offsets) has been directly
confirmed from decompilation results, so the internal consistency of these
being one unified feature is itself confirmed.

## `CmdOpenPartyChangeMenu::initialize` (file offset `0x220274`)

Takes 7 parameters `[p0, p1, p2, p3, p4, p5, p6]` and copies them into a
singleton structure at a fixed address (via `0x45b05c`) as follows:

```
singleton.field_0xa1c = params[2]
singleton.field_0xa20 = params[3]
singleton.field_0xa24 = params[4]
singleton.field_0xa28 = params[5]
singleton.field_0xa2c = params[6]
```

`params[0]` is used as the "starting ID" for the subsequent message
queueing process (file offset `0x14fa30`), and `params[1]` as the "number
of consecutive pages to queue" (returns immediately if 0 or less; otherwise
loops that many times, incrementing the ID while queueing).

## `CmdOpenPartyChangeMenu::isEnd` equivalent (file offset `0x220314`)

Checks the singleton's status byte to determine completion; if complete,
sets a flag at the fixed address `0x541730` (the flag-management structure)
with `type=2, id=singleton.field_0xa30`. `field_0xa30` is a 6th field,
separate from the 5 fields (`0xa1c`-`0xa2c`) written by `initialize`, that
holds the selection result.

## `PartyChangeMenu::onOpen` (candidate-list construction, around file offset `0x1073cc`)

```c
void PartyChangeMenu::onOpen(this) {
    party = PlayerParty::getInstance();
    this->a08 = party->b8;              // number of living party members
    this->a1c = this->a20 = this->a24 = this->a28 = this->a2c = this->a30 = 0;
    this->a0c = this->a10 = this->a14 = this->a18 = 0;  // init the 4-element candidate list

    for (i = 0; i < this->a08; i++) {
        charId = <get character ID from formation slot i>;
        if (charId != 1) {               // exclude only the Hero (character ID 1)
            candidate[compact_idx++] = charId;  // pack into the 4-element buffer (no bounds check)
        }
    }
}
```

Key points:
- The only character excluded is character ID 1 (the Hero). No exclusion
  condition exists for any other character ID.
- The buffer holding the candidate list (`a0c`/`a10`/`a14`/`a18`) physically
  has only 4 elements, and there is no bounds check to reject a 5th or
  later candidate. Attempting to pack a 5th candidate overwrites the field
  adjacent to the buffer (`a1c`, originally meant to hold the selection-
  result flag ID).

## `PartyChangeMenu::onResult` (selection-result handling, file offset `0x107734`)

```c
void PartyChangeMenu::onResult(this, result_code) {
    cursor = this->a9a0;                 // current cursor position
    if (result_code == 0) return;        // not yet decided
    if (result_code == 1) {              // confirmed
        tag = this->a0c[cursor];         // get the selected character ID from the candidate array
        if (tag == 2) this->a30 = this->a1c;
        else if (tag == 4) this->a30 = this->a20;
        else if (tag == 5) this->a30 = this->a24;
        else if (tag == 6) this->a30 = this->a28;
        // if tag matches none of the above 4 values, a30 is not updated in this branch
        if (this->a08 - 1 == cursor) {   // if the cursor matches the last position in the candidate list
            this->a30 = this->a2c;       // unconditionally overwritten
        }
    } else if (result_code == 2) {       // cancel
        this->a30 = this->a2c;
    } else if (result_code == 4) {
        <branches to another shared routine, unanalyzed in detail>;
    }
}
```

Key points:
- Of the character IDs that can appear in the candidate array, only the 4
  fixed values `2/4/5/6` are targets for assignment to their corresponding
  flag ID received by `initialize` (`a1c`/`a20`/`a24`/`a28`). Any other
  character ID value that could appear in the candidate list is not
  handled by this if-chain.
- If the cursor position matches "the last slot in the candidate list,"
  `a2c` (the fallback/cancel flag ID) is adopted unconditionally,
  regardless of the character-ID determination above. This means the same
  flag is set for both a "cancel operation" and "selecting the last entry
  in the candidate list."
- The selection result is observable from the script side only through the
  state of the `type=2` flag that `isEnd` sets (no individual return-value
  register or similar is involved).

## `TownFormationMenu` (a separate class, generic implementation)

Despite a similarly-sounding name to `PartyChangeMenu`, its implementation
is independent and contains no hardcoded character-ID determination at all.

```c
void TownFormationMenu::onOpen(this) {
    count = PlayerParty::getInstance()->b8;
    this->a0c = count;
    this->a08 = (count >= 1);  // slot 0's "include in formation" flag (bool)
    this->a09 = (count >= 2);
    this->a0a = (count >= 3);
    this->a0b = (count >= 4);
}

void TownFormationMenu::onDraw(this) {
    count = PlayerParty::getInstance()->b8;
    for (i = 0; i < count; i++) {
        if (<slot i's "include in formation" flag is 1>) {
            charId = <character ID of formation slot i>;
            <generic status retrieval / row rendering (per slot)>;
        }
    }
}
```

Key points:
- Subscript `i` is a formation-array slot number, not a character ID
  itself.
- Whether each slot is shown is determined not by a branch on character
  ID, but by an independent on/off flag per slot.
- The `onResult`-equivalent processing also manipulates slot positions via
  a generic utility; no character-ID comparison appears.

## Design differences between the two classes (summary)

| | `PartyChangeMenu` | `TownFormationMenu` |
|---|---|---|
| Unit of candidate/target | Character ID (partially hardcoded) | Formation slot number |
| How the selection result is reflected | 4-pattern if-branch on character-ID value + fallback | Generic per-slot on/off |
| Candidate buffer limit | Fixed at 4 elements (no bounds check) | Tracks the party headcount |
| Excluded target | Character ID 1 (the Hero), fixed | None (determined per slot) |

## Related functions (unanalyzed/unconfirmed)

- `TriggerPartyChange::onStart` (file offset `0x18aae4`): a thin
  implementation that only calls `PlayerManager::getInstance()`; the actual
  trigger conditions require separate investigation of map/trigger-related
  data.
- `PlayerParty::reorder` (file offset `0x188c4c`) and, inside its caller
  `fcn.0021a220` (file offset `0x21a220`), a hardcoded `id<7` bounds check
  that reads values from 4 fixed globals and adopts only those that are
  "nonzero and less than 7." This is a separate system from normal party-
  change processing (presumed related to special, forced party
  configurations).

## Unconfirmed / unresolved points

- The actual runtime dispatch path from an opcode number to
  `CmdOpenPartyChangeMenu::initialize`.
- Exactly which scene/call path (via script, or a direct C++-side trigger)
  actually opens `TownFormationMenu`.
- Details of how a `Message::SetMacro`-equivalent call is used to insert
  the speaker's name into the selection result.
