# The structure for updating the chapter number and event flags

## What `GameParameter::setFlagShopParty` does

The chapter number in `StoryStatus` and the bulk-set of type-0 event flags
of the `day_index` kind are both performed, in sequence, from the same
record of the same table, inside a single function
`GameParameter::setFlagShopParty(int recordIndex)`.

```c
// The relevant part of GameParameter::setFlagShopParty(int recordIndex) (pseudocode)
Record* rec = ExcelBinaryData::getRecordDynamic(&g_table, recordIndex, ...);
u8 chapterNibble = rec->byte[0xa1] & 0x0f;            // chapter info inside the record
StoryStatus::setChapter(storyStatusInstance, chapterNibble + 1); // update the chapter number
some_other_prep(recordIndex);                          // unanalyzed preprocessing
GameParameter::setEventFlag(recordIndex);              // bulk-sets type-0 flags using
                                                        // the same recordIndex as the dayIndex
```

- `GameParameter::setEventFlag` internally calls `GameFlag::initialize`
  (vtable[5]), which **first zero-clears** the type-0/type-1/type-2 flag
  regions entirely, then re-sets only the one record's worth of data for
  row `recordIndex` via `GameFlag::set(type=0, ...)`. This is "rebuild from
  zero every time," not "apply just one row."
- `GameParameter::setFlagShopParty` is referenced from only a single
  location in the entire ROM. Its callers are `GameParameter::execFlagShop`
  and `CheckPart::initialize`.

## Design consequence

The chapter number and the type-0 `day_index`-style event flags are always
updated as a set, from the same `recordIndex`. Consequently, a state where
"the `day_index` side has advanced but the chapter number is still old"
cannot occur via the regular code path.

## References to `StoryStatus` (the code that reads the chapter number)

References to the `StoryStatus` instance, within what could be confirmed,
are limited to UI/menu-related gating checks such as those below; no
references were found from map/NPC-display classes (`ScriptGroup`,
`ObjectAccess`, `TownSystem`, etc.).

```
BattleExecItem03::setup, BattleExecStealItem01::setup, PartUtility::startTitle,
UserMessageMacroHook::PostProcess, SurechigaiMenuMain::endSurechigaiMessage43,
BankMenuMain::end/start, NameMenuMain::endMessageWindow/end,
TownJobMenu::onUpdate, TownTopMenu::onResult, TownReportMenu::onOpen,
TownTopTacticsMenu::onResult, TownStatusTargetMenu::onResult,
BattleCommandMenu::onResult, ContestMenuMain::endMessageWindow/
endContestMessage7, ContestRankingMenu::onDraw, HaveAction::isType,
GameParameter::setFlagShopParty
```

## `ScriptGroup` header structure (whether per-chapter groups exist)

Multiple `ScriptGroup`s can exist within a SCRIPT file, but the header's
`tag` field is the fixed string `"scriptgroup"` common to all groups, and
contains no identifier indicating chapter or variant. Differences between
groups are observed only as size differences such as `obj_count`/
`header_size`; it is likely (unconfirmed) that the same group of NPCs being
split across multiple groups is a unit of weather/time-of-day variation
rather than a chapter-based switch.

## Points that remain unconfirmed

- The specific trigger condition by which `recordIndex` is determined
  during gameplay.
- The contents of the preprocessing function called between the chapter and
  flag updates.
- The structure/record count of the referenced table, and the meaning of
  each field (offsets +0x6, +0x8, +0xa, +0xc, +0xe appear to be a group of
  message IDs, but this is unconfirmed).
- Whether this table and the day_index table inside the event-flag
  definition data point into the same index space.
