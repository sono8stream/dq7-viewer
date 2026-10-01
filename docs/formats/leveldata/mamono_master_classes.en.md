# Battle Task Structure for the "Monster Tames You" Sequence

The group of classes implementing the presentation of adding a defeated
monster, after battle, to the owned-monster list of the "Monster Park."
This corresponds to addition to the Monster Park's owned-monster list,
not direct recruitment into the walking party.

## Class composition: `BattleTaskMamonoMaster` + `BattleExecMamonoMaster00/01/02`

DQ7's battle tasks follow the design "one `BattleTaskXxx` executes several
`BattleExecXxx` (sub-states) in sequence" (a pattern shared with other
battle tasks). This sequence consists of 3 states.

| Class | Role |
|---|---|
| `BattleExecMamonoMaster00` | Displays a single system message. The displayed wording involves a grammar-variant selection (singular/plural, etc.) that switches based on the target monster's attribute byte (upper 3 bits of `+0x84`) |
| `BattleExecMamonoMaster01` | Displays a Yes/No confirmation system message. After display, calls a helper function that writes to a global flag array |
| `BattleExecMamonoMaster02` | Branches on the player's answer (a global 1-byte flag). On the Yes side, calls `BattleResult::setMonsterAttach` to finalize the taming and displays the corresponding message. On the No side, it only displays a different message |

Based on the function name `BattleResult::setMonsterAttach`, it is
presumed that upon a successful tame, the monster is linked to
`BattleResult` (the battle-result structure) as an "accompanying monster,"
and registered into the Monster Park after the battle ends (related
symbols `BattleResult::setMonsterAttachCount` and
`MonsterParkUtility::getMonsterParkHouseCount` also exist).

`BattleTaskMamonoMaster` itself (`initializeUser`) merely registers the 3
sub-states; the decision of whether to launch this task at all lies
further outside (the battle-end processing). Candidate functions
`MonsterPartyUtility::isEnableCallMonster` and
`status::isEnableCallMonster` exist, and a loop structure scanning
surviving monsters one by one has been confirmed to exist, but the actual
judgment condition itself (tameability, probability roll, etc.) has not
been decoded.

## Unresolved points

- The conditional expression for the `isEnableCallMonster` family (the
  probability/conditions for "taming").
- The actual Monster Park registration processing that occurs after the
  `BattleResult::setMonsterAttach` call.
- Which field of the monster parameter table corresponds to the monster's
  attribute byte `+0x84` (upper 3 bits, used for the grammar-variant
  branch).

## Investigation method notes

Fixed messages built into the battle system (cases where the ExeFS side
holds the message ID directly, without going through a SCRIPT file) can be
found by byte-searching the entire ExeFS for the 32-bit integer literal of
the message ID. The fact that a message is "not found by searching
SCRIPT" does not mean that message does not exist.
