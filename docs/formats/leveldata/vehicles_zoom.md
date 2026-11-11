# `LEVELDATA/dq7_vehicles.dat` and the Zoom menu

`dq7_vehicles.dat` is an ExcelBinaryData table (20-byte header: magic, record count, record size, count, 0;
records from `+0x14`). 29 records of 0x3c bytes. Record `d` is Zoom destination `d`; it also says where the ship
and the magic carpet are moved when the party zooms there.

| Offset | Type | Meaning |
|---|---|---|
| +0x00 | s32 | ship place number (30000 + the map's sea exit) |
| +0x04 | s32 | same as +0x00 in every record |
| +0x08 | s32 | magic carpet place number (50000 + n) |
| +0x0c | s32 | ship floor id |
| +0x10 | s32 | carpet floor id |
| +0x14 | f32 ×3 | ship position |
| +0x20 | f32 ×3 | carpet position |
| +0x2c | u16 | destination floor id |
| +0x2e | u16 | destination exit number (map link): the party arrives as if it came through that exit |
| +0x30 | u16 | (not read by the Zoom code) |
| +0x32 | u16 | alternative floor id |
| +0x34 | u16 | alternative exit number |
| +0x36 / +0x38 | u16 | flags (type 0) choosing the alternative, with the polarity bits of +0x3b |
| +0x3a | u8 | ? |
| +0x3b | u8 | bit 0 / bit 1: polarity for the flags at +0x36 / +0x38 |

## How the game reads it

- `TownRuraMenu::onOpen` (base 0x1c4438) lists destination `d` = 1..25 when the type-0 story flag `d` is set
  (`GameFlag::check(flags, 0, d)`), in that order.
- `TownRuraMenu::onDraw` draws the name as menu text `0xe4070 + d`, which is entry `#d` of
  `MENULIST/place_menu.txt`.
- `TownRuraMenu::onResult` (0x246e2c) stores the chosen `d` (24 becomes 27, 25 becomes 28).
- `FlowRuraAction::onEnd` / `FlowShipRura::onEnd` request a map link to
  `LevelDataUtility::getVehiclesFloorId(d)` / `getVehiclesSurfaceId(d)`: +0x2c / +0x2e, or +0x32 / +0x34 when
  +0x38 is non-zero, its flag matches bit 1 of +0x3b, and (+0x36 is zero or its flag does not match bit 0).
  Then they copy the ship and carpet fields into the vehicle manager (same code as `DQVehicleManager::setRura`).
- When no destination flag is set the list is empty. `onOpen` zero-fills the slot array, so confirming would
  take slot 0 = destination 0, and record 0 is all zeros (floor 0). Casting Zoom with no destination froze the
  game; this path is read from the code, not traced at run time.
