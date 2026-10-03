# Field / encounter-related structures inside ExeFS `.code`

Target: `.code.decompressed.bin` (3DS ExeFS executable code, ARM 32-bit
fixed-length instructions). Addresses are base-game virtual addresses (as
listed in `FuncSearch.txt`). File offset = VA − 0x100000.

## RomFS file manifest table

A table enumerating pointers to `.dat` file paths under `LEVELDATA/` is
embedded in `.code`.

- Starting VA: `0x3ee930`
- Entry size: 40 bytes, 51 entries in alphabetical order
- Each entry's `+12` holds a pointer to the path string
- Actual runtime resource loading does not reference this table directly
  (it is likely a log/registration string table); files are loaded through
  a different path

## `dq7_field_symbol.dat` (159 records × 20 bytes)

An anchor coordinate table used only for roaming symbols on the world map
(`wld_*` maps). Dungeon-interior symbols are not included here.

```
+0x00 u8   id (= record number - 1)
+0x01-03   FF FF FF (fixed marker)
+0x04 f32  X coordinate (world-map tile coordinates, range 0-176)
+0x08 f32  Y coordinate
+0x0c u16  mapId (matches +0x04 in dq7_encount_tile.dat / dq7_floor_list.dat)
+0x0e u16  symId (unique symbol instance ID; shared only by instances spanning adjacent sub-regions)
+0x10 u32  reserved (usually 0; one record has the exceptional value 0x5a2)
```

There is no field corresponding to detection/pursuit radius in this table
(only coordinates + ID fields).

## `Encount` class: step-counter-based encounter determination

`Encount::execWalk` (VA `0x228818`) is the determination routine called on
every single-tile move.

Field layout (offsets relative to `this`):
- `+0x00` u16: `stepThreshold` (step-counter wraparound value)
- `+0x05` u8: terrain/zone type parameter (field = 0, dungeon = 8)
- `+0x14` u8: determination state (progresses 0→1→2; finalized at 2)
- `+0x18` u16: `stepCounter16` (incremented by 1 per tile moved, reset on reaching `stepThreshold`)
- `+0x1a` u16: `totalSteps16` (cumulative step count, purpose unconfirmed)
- `+0x1c` u8: encounter-triggered flag (set to 1 when `Encount::brew` returns true at state 2)
- `+0x5c`: an `EncountCountDown` instance (see below)

`stepThreshold` is initialized to the fixed immediate value `8` in both
`Encount::setupField` (VA `0x1877fc`) and `Encount::setupDungeon`
(VA `0xa6f24`) (not derived from RomFS data — a constant embedded directly
in the code). In `Encount::setupDungeon`, the same immediate load is also
used for the terrain type field `+0x05` (both fields are initialized by the
same instruction at once).

### `EncountCountDown`

- `EncountCountDown::setupRandom` (VA `0x198390`) / `EncountCountDown::exec`
  (VA `0x1984f4`) handle the countdown decrement
- `EncountCountDown::setupSymbol` (aka `fcn.001503cc`, VA `0x2503cc`)
  determines "the actual interval per wraparound." It uses a weighted
  lottery curve table embedded in rodata (an integer array around VA
  `0x402470`-`0x402528`) together with `rand(0..31)` to draw a value from
  the cumulative distribution. The referenced table is switched depending
  on whether terrain type `+0x05` is `8` (dungeon)
- Neither the curve table above nor `stepThreshold` references RomFS data
  at all (all primary frequency parameters are fixed values inside ExeFS)

## `SymbolEncountStatus`: grid-based spawn position determination

A class of the same name exists in two different VA ranges (around
`0x21bxxx` and `0x33exxx`) (the difference in role is unconfirmed).

### Grid cell flags (u16/cell)

- `0x8000`: cell is occupied by another symbol
- `0x2000`: visited during the current search
- `0x4000`: when set, the cell is eligible for the "connected component of
  5+ tiles of open terrain" determination (see `isCellRootPos` below)
- Low bits (`& 0x3f`): tile type (values `1`/`2` are forbidden tiles
  excluded from candidacy)
- Upper nibble (`>> 28`): priority (used in `calcEncountPos` candidate
  selection)

Grid structure (equivalent to, via a singleton: `[0x5c7234]→+8→+0x10000→+0x34`):
- `info->+0x10`: actual distance scale per ring (`ringDistScale`)
- `info->+0x18`/`+0x1c`: float divisors used for cell subdivision (cell
  size; likely differs per map, source unconfirmed)
- `info->+0x1c`: grid width (cell count)
- `info->+0x20`: grid height (cell count)

### `SymbolEncountStatus::registEncountData` (VA `0x229844`)

Searches a fixed array of 16 slots × 84 bytes (0x54) for an empty slot
(`+0x04` is `-1`) and initializes it. Record fields (partial, some details
unanalyzed):
- `+0x00`: argument passed by the caller (symbol/encounter ID)
- `+0x04`: a byte at `+0x1a` of a different table (presumed monster-data
  related)
- `+0x08`: a global counter value
- `+0x1c`/`+0xc`: status value arrays for the 4 party members (details
  unconfirmed)

### Priority order for spawn position determination (confirmed control flow)

```
1. isCellRootPos(pos, maxRadius)
     A flood fill starting from a cell with the 0x4000 flag set, checking
     whether the connected 0x4000 cells number 5 or more tiles. On success,
     the position is finalized immediately.
     (The hypothesis that this flag marks "dedicated town-entrance anchors"
     was disproven by verification; it is considered a general-purpose flag
     for "a reasonably large area of open terrain.")
2. On failure of (1) → calcEncountPos(pos, maxRadius)
     A greedy approach that increases the radius index `ring` by 1 starting
     from an initial value, trying 4 candidate points on that ring. Loop
     condition: `ring * cellSize < maxRadius`. As soon as any candidate
     satisfies "unoccupied, not a forbidden tile, priority at or above the
     threshold," it is finalized on the spot without searching farther
     rings. `maxRadius` is a fixed float constant shared between field and
     dungeon (a literal-pool value; no branching by map type).
3. On failure of both (1) and (2), if a retry is allowed → calcNearPos(pos)
     A 4-direction BFS (up/down/left/right) from the center cell. Round cap
     of 10; each round expands the frontier by 1 tile in every direction.
     Has no exclusion logic other than "occupied/visited" (no exclusion by
     distance). Collects up to 200 candidates.
```

`calcEncountPos`/`isCellRootPos`/`calcNearPos` are each called from a single
shared caller across the entire binary; there is no separate initialization
branch for field vs. dungeon.

`SymbolEncountStatus::isToheros` (VA `0x2299e4`):
```
Returns true if monsterLevelOrRank <= playerLevel - 5
(only evaluated when a global state such as the "Holy Protection" /
Toheros-equivalent effect is active)
```
The threshold `5` is an immediate value embedded directly in the code.

## Monster movement logic (`EnemyObjectFlow`/`TaskEnemyObject`)

For monster-dedicated objects (presumed to inherit from `CharacterObject`,
allocated from a 32-element pool via `PeopleParty::add` → the generic
factory `fcn.0x193148`), field `+0x10` is a movement-speed scalar (f32)
referenced in common by all three confirmed movement logics.

Confirmed movement states (in the `EnemyObjectFlow` region, around VA
`0x1df908`-`0x1e2604`):

1. **Direct pursuit**: recalculates a direct vector toward the player's
   current position every frame and approaches. Waits while timer `+0x5c`
   is below threshold 7; begins approaching at 12 or above.
2. **Wandering**: tries passable candidate points in order from the 8
   directions around the current position, and moves to a found point via
   node interpolation.
3. **Charge (predictive movement)**: estimates the player's future position
   using the player's current velocity × a prediction-time constant, and
   moves in a straight line toward that single point (a "leading shot"
   style of movement).

In all cases, the actual movement is built via the "action node" generation
function `fcn.0x18fae4(nodeType, targetObj)`, riding on a behavior-tree
system keyed by node-type ID (node type 0 = interpolated-movement family).
The overall picture of node-type dispatch and the meaning of each parameter
is undeciphered.

There is no separate code path per monster species; it is a single shared
state-machine implementation for all monsters, designed so that individual
differences show up in the referenced numeric values (speed, timer
thresholds, etc.) instead. Whether the source of the speed field `+0x10`
(RomFS data vs. a fixed value) is unconfirmed.
