# Mapping Between `CHARACTER/pXXXX` Model Numbers and Character IDs

## A dead end: `dq7_chara_list.dat`

`LEVELDATA/dq7_chara_list.dat` (927 records × 84 bytes) is a catalog of
model assets, and its record order is unrelated to the character ID
system. Each record does contain the model name string (`pXXXX`) itself,
but a character ID cannot be reverse-looked-up from a record's position.

## The working path: `dq7_character_init_data.dat`

This file (20-byte header + 46 records × 172 bytes) has record index =
character ID itself (index 0 is a dummy). Near offset `+0x78` of each
record, there is an ASCII string holding the last 3 digits of the model
number (the `XXXX` part of `pXXXX`, with the leading `p0` stripped).

```python
HDR = len(data) - 46 * 172   # = 20
for char_id in range(46):
    rec = data[HDR + char_id*172 : HDR + (char_id+1)*172]
    model_suffix = rec[0x78:0x78+16].split(b'\x00')[0].decode('ascii', 'replace')
    # 'CHARACTER/p0' + model_suffix(3 digits) is the actual model path
```

To get the display name from a character ID, look it up in
`TEXT/PLAYER_NAME.txt`.

## Cross-checking via the script's speaker tag

Text under `MESS/` carries a speaker tag `#<model number>`, and this
**matches the model number (the numeric part of `pXXXX`), not the
character ID (the record index of `dq7_character_init_data.dat`)**. This
can be confirmed by checking a character for which the two values differ,
proving the tag is the model number rather than the character ID.

## Correspondence between model number (`pXXXX`) range and character category

The approximate correspondence found by comparing multiple models
(boundary values are "less than"):

| Model number range | Category |
| --- | --- |
| below p50 | party characters (main members who join combat as companions) |
| p50 to below p100 | NPCs that join the party (characters who join temporarily/for an event) |
| p100 to below p150 | NPCs with a proper individual name (individually named characters with a story role) |
| p150 to below p400 | NPCs (other named mobs/residents, etc.) |
| p400 and above | other (monsters, objects, effects, etc., including non-humanoid entities) |

This classification is a separate axis from the character-ID system
(id0-45) of `dq7_character_init_data.dat`, and also covers the large
number of other NPC models that have not been assigned a character ID
(since those character IDs are not in that table, use this range to
roughly infer their category).

## Generalized procedure

1. Reverse-look-up model number → character ID (the record index itself)
   using the `+0x78` string in `dq7_character_init_data.dat`. Since this
   table only has 46 records (id0-45), model numbers not listed in it
   cannot be identified via this path.
2. Look up the display name from the character ID in
   `TEXT/PLAYER_NAME.txt`.
3. If possible, search script text under `MESS/` for the speaker tag
   `#<model number>` and cross-check from context (note that the tag
   matches the model number, not the character ID).
