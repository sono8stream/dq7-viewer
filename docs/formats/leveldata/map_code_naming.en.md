# Mapping Between Map File IDs and In-Game Location Names

File names in `MAP/_list.txt` / `SCRIPT/*.bin` (e.g. `h01nout1`,
`d06pf1a`) are internal codes and do not directly spell out a location
name.

## Map code naming convention (based on observation)

```
[letters identifying the area series][2-digit number][p or n][per-map suffix]
```

- Letters: the area/dungeon series (`MAP/_list.txt` has about 255 series)
- 2-digit number: a serial number within the same series (the number can
  change for the same location as the chapter progresses)
- `p` / `n`: past / present(now)
- Suffix: identifies the individual map, e.g. `out` (outdoors), `f1`...
  (floors inside a building), `b1`... (basement/back map), `m1f1`...
  (individual buildings such as houses)

The line number (1-based) in `MAP/_list.txt` matches the record index in
`LEVELDATA/dq7_floor_list.dat` / `dq7_floor_param.dat`. However, this line
number does not necessarily match the index of the location-name
reference tables described below.

## Location name reference tables

### `MENULIST/place_menu.txt` (major location names, 311 entries)

Format `#number,,location name`. A list of names for major towns and
dungeons (presumed to be used for things like the "current location"
display in menus).

### `MENULIST/floor_menu.txt` (detailed floor names, 13890 entries)

Format `#number,group number,floor name`. Detailed names including each
floor inside a building. The group number column appears to correspond to
the numbers in `place_menu.txt` (unconfirmed).

**Note**: the `#number` column of `floor_menu.txt` does NOT match the
`floor_id` of `dq7_floor_list.dat`. It is an independent serial number for
menu display purposes, and the same numeric value may refer to a different
entity. There is no reliable way to mechanically reverse-derive a floor_id
from a location name; the message text inside the script must be checked
directly.

## Floor ID ⇔ map code correspondence table (`dq7_floor_list.dat`)

Contains a direct "floor ID → map code name" correspondence table.
16-byte records (the table starts at 0x20):

```
+0x04 (u16): floor ID
+0x06 (u16): series group number
+0x08 (char[8]): map code name (e.g. c01nout, m01nm2f2, wld_n25a)
```

This floor ID matches argument 0 of the SCRIPT map-move opcode
`0x0001001f`.

## Reproducible procedure to identify a location name

To identify the location name for an uninvestigated map code:

1. Read the target `SCRIPT/<mapcode>.bin` and search for a message-display
   opcode (e.g. `09 00 03 00`, `0B 00 01 00`, `0D 00 01 00`).
2. The 4 bytes immediately after the found opcode are the message ID
   (u32 LE).
3. Open `MESS/#XXX000.fpt` (`XXX000` = the message ID truncated down to
   the nearest 1000) and look up the entry for file name
   `#<message ID>.txt` in its FPT0 format. Note that the entry's
   `msg_offset` is not an absolute offset from the start of the file, but
   a relative offset from `data_start`.
4. Read the corresponding message text and identify the location from the
   place name, people's names, and situation it describes.
5. Cross-check against `MENULIST/place_menu.txt` / `floor_menu.txt` for a
   plausible location name.

## Known unresolved points

- The correspondence between the 2nd column of `place_menu.txt`
  (apparently a group number) and the group codes of `MAP/_list.txt` has
  not been decoded.
- An exhaustive table mapping all 255 series of map codes to location
  names has not been created.
