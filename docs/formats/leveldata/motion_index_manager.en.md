# Motion Resolution Pipeline (`MotionIndexManager` / `MotionIndexJobManager`)

The mechanism that resolves "which clip inside a `.pack.lz`" a character
should play, during field exploration or battle. Structure confirmed via
static analysis of the ARM32 code (`code.decompressed.bin`) and
real-hardware verification of modification patches.

## Overall dispatch: `CharacterObject::getMotionIndex` (file offset `0x1853dc`)

Branches on the "category tag" at `+0x94` of `CharacterObject`:

```c
int CharacterObject::getMotionIndex(this, motionType) {
    switch (this->+0x94) {
    case 0x1000000: // person (playable)
    case 0x3000000: // person variant (e.g. currently-controlled slot)
        slot = this->+0x8c;
        if (slot < 7)
            return MotionIndexJobManager::getInstance()
                     ->getJobCharacterMotionIndex(*(this+0x90), motionType, *(this+0x98));
        else
            return MotionIndexManager::getInstance()
                     ->getCharacterMotionIndex(*(this+0x90), motionType);

    case 0x2000000: // NPC/monster (treated more on the battle side)
        idx = this->+0x8c;
        if (idx < 7 || idx == 0x34)
            return MotionIndexJobManager::getInstance()->getJobBattleMotionIndex(
                     motionType, 0xc, *(this+0x9c) ?: 0);
        else if (idx > 1000)
            return MotionIndexManager::getInstance()->getMonsterJobIndex(
                     motionType, (this->+0x98==0x34 ? 0x36 : this->+0x98), *(this+0x9c) ?: 0);
        else if (38 <= idx <= 45)
            return MotionIndexManager::getInstance()->getMonsterMotionIndex(
                     motionType, character_init_data[idx].field_0x68);
        else
            return MotionIndexManager::getInstance()->getBattleMotionIndex(motionType, idx);

    case 0x4000000: // monster
        return MotionIndexManager::getInstance()->getMonsterMotionIndex(
                 motionType, LevelDataUtility::getBaseMonsterNo(this->+0x8c));

    default:
        return -1;
    }
}
```

Related symbols (file offset, base-ROM basis):

| file offset | symbol |
|---|---|
| `0x184ac8` | `MotionIndexJobManager::getInstance` |
| `0x185000` | `MotionIndexManager::getInstance` |
| `0x184c04` | `LevelDataUtility::getBaseMonsterNo` |
| `0x26214` | `MotionIndexJobManager::getJobBattleMotionIndex` |
| `0x23ad8` | `MotionIndexManager::getMonsterJobIndex` |
| `0x184b30` | `MotionIndexManager::getMonsterMotionIndex` |
| `0x23c88` | `MotionIndexManager::getBattleMotionIndex` |
| `0x23e38` | `MotionIndexManager::getCharacterMotionIndex` |
| `0x263b0` | `MotionIndexJobManager::getJobCharacterMotionIndex` |
| `0x18390c` | `MotionIndexManager::readFile` |
| `0x1949d8` | `ExcelBinaryData::getRecordDynamic` (generic record lookup) |
| `0x194990` / `0x1949ac` | `HaveJob::getJobLevel` / `HaveJob::setJobLevel` |
| `0x123880` | `HaveJob::change` |

`MotionIndexJobManager` (dedicated to job-related lookups) and
`MotionIndexManager` (general-purpose, including monsters) are separate
classes, but both use `ExcelBinaryData::getRecordDynamic` in common for
their internal table lookups.

## File-loading pattern

`MotionIndexManager::readFile` assembles its path using the format
`"%s.idx"`. Candidate strings:

```
CHARACTER/person   → CHARACTER/person.idx
MONSTER/enemy      → MONSTER/enemy.idx
BATTLE/battle      → BATTLE/battle.idx
WEAPON/weapon      → WEAPON/weapon.idx
GOODS/goods        → GOODS/goods.idx
```

Under `CHARACTER/`, in addition to `person.idx` there are also sibling
files `person.jidx` (for job variants), `person.matidx`, and
`person.jmatidx`. Under `BATTLE/`, `battle.jidx` similarly exists.

## Confirmed structure of `person.jidx` / `battle.jidx`

Both files share the same layout (`battle.jidx` is the battle-use
counterpart, read by
`MotionIndexJobManager::getJobBattleMotionIndex` (`0x26214`)):

```
header: u16 count
record (6 bytes, count entries):
  +0x00 u16 characterId   (1=Hero, 2=Maribel, 3=Kiefer, 4=Gabo, 5=Melvin, 6=Aira)
  +0x02 u16 jobId         (0=jobless ... 20)
  +0x04 u16 subOffset     (absolute offset from the start of the file = right after the header)

sub-block (pointed to by each record's subOffset):
  an array of {u16 motionKey, u16 result}
  motionKey is a motion-type ID from dq7_motion_list.dat; result is the
  final motion index used to resolve an animation clip inside .pack.lz
```

- A record is looked up by the combination of `characterId` × `jobId`; if
  not found, `-1` is returned (meaning that character has no motion
  linked for that job at all).
- In the base ROM, 5 of the 6 main-story playable characters (Hero,
  Maribel, Gabo, Melvin, Aira) have all 21 records for `jobId=0-20`, but
  **Kiefer (characterId=3) has only a single record for `jobId=0`
  (jobless)**, with no records from `jobId=1` onward (a direct, data-level
  reflection of the fact he was developed as a character not meant to
  change jobs).
- `getJobCharacterMotionIndex` (`0x263b0`) performs a 2-axis matching
  lookup, comparing `record[+0]` (characterId) against a value derived via
  `*(CharacterObject+0x90)`, and `record[+2]` (jobId) against the raw
  value at `[CharacterObject+0x98]`.

## Motion-type aliasing in `CharacterObject::setMotion`

A hardcoded substitution on the code side, inside
`setMotion(this, motionType, ...)`:

```c
if (motionType == 100 /*idle*/) motionType = 0;
if (motionType == 119 /*turn_l*/ || motionType == 120 /*turn_r*/) motionType = 101 /*run*/;
else if (motionType == 130 /*dash2*/) motionType = 102 /*dash*/;
idx = getMotionIndex(this, motionType);
```

## `LEVELDATA/dq7_motion_list.dat` (motion-type "ID → name" correspondence table)

```
header: u32 magic, u32 nrec(228), u32 rsize(28), u32 nrec_dup(228), u32 reserved  ; 20 bytes total
record (28 bytes):
  +0x00 u32 self_index
  +0x07 char[20] name (NUL-terminated)
  +0x1B u8  flag (0/1, meaning unconfirmed)
```

Known correspondences (the main ones): `100=idle`, `101=run`, `102=dash`,
`103=pop`, `104=out`, `130=dash2`.

## `CHARACTER/MotionListTable.dat` (character-independent common table)

```
header: u16 count(224)
record (4 bytes): u16 a (ID from dq7_motion_list.dat), u16 b (reference target for the actual clip)
```

Almost all records have `b==a` (self-reference). The 3 exceptions
(`idle(100)→0`, `pop(103)→2`, `out(104)→3`) are aliases where the field
version reuses the same-named motion intended for battle.

## `HaveJob` (runtime object, per-character job state)

```
HaveJob
+0x04  u8     currentJob (current job ID)
+0x05  u8[55] jobLevel[job_id] (proficiency per job, star rank 0-8, job_id=0-54)
```

`HaveJob::change(this, jobId)` only rewrites `currentJob`; it does not
check whether the job change is allowed (at most, if `jobLevel[jobId]` is
0 it bumps it up to 1).

`dq7_player_job.dat`: 55 records × 188 bytes.
`ExcelBinaryData::getRecordDynamic` (`0x1949d8`) performs direct index
access: `record = job_id × recordSize + (header_ptr + 0x14)` (`recordSize`
is `+8` of the static descriptor).

## Per-job star-level array inside save data

Within a character record, right after `job` (current job, relative
`+0x0038`) there is a 55-byte array starting at `+0x0039`, holding
per-"job-specific star level," indexed directly by `job_id`
(`webapp/save_editor.py`'s `CHAR_JOB_LEVELS_OFFSET=0x0039` /
`CHAR_JOB_LEVELS_COUNT=55`).

## Field and battle use different reference paths

Even for the same character identifier/model swap, field display and
battle display go through different reference paths (`getMotionIndex`'s
categories `0x1000000`/`0x3000000` lean toward field, `0x2000000` leans
toward battle). When verifying a swap of RomFS model/animation files, both
field and battle must be checked individually.

## Clip selection inside `.pack.lz` is by position index, not by name

The `SkeletalAnims` dictionary has string keys, but the clip actually
selected for playback at runtime is based on **order (index number)**
within the dictionary. The `result` field (motion index) of
`person.jidx`/`battle.jidx` is used as an index specifying a position
within this clip list. Because of this, swapping between data whose clip
composition/order differs, even if the names match, can result in a
completely different motion being played.
