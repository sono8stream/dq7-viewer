[日本語](README.ja.md)

# DQ7 Viewer

A web-based viewer & editor for Dragon Quest VII (Nintendo 3DS) ROM data,
built from original binary format analysis.

🚧 Work in progress / early stage — actively being developed, expect rough
edges and missing features.

## What this is

- `webapp/`: a local web app for browsing/editing extracted RomFS/ExeFS data
  (built on Python's standard `http.server`, minimal dependencies)
- `docs/formats/`: format specifications discovered through analysis
  (offsets, field definitions, algorithms). Each document has an English
  (`.md`) and Japanese (`.ja.md`) version side by side.

## What this is not

- **No ROM, CIA, or save data is included.** This repository publishes only
  the analysis tooling and the factual results of the analysis (data
  structure specs).
- The documents under `docs/formats/` are written as pure structural
  reference: no investigation narrative, and no quoted in-game dialogue or
  message text.

## Usage

To run the viewer you need RomFS data extracted from **a ROM you legally
own**. This repository does not include ROM-dumping or RomFS-extraction
tools or steps.

### Placing your ROM data

At the repository root (the same level as `webapp/`), create a folder
`rom/extracted/` and put the contents of your extracted RomFS inside it
as-is, keeping RomFS's original folder names (`SCRIPT/`, `MESS/`,
`LEVELDATA/`, `CHARACTER/`, `MONSTER/`, `TEXT/`, `MENULIST/`, `TEXTURE/`,
`MAP/`, etc.).

```
dq7-viewer/
├── webapp/
└── rom/
    └── extracted/
        ├── SCRIPT/
        ├── MESS/
        ├── LEVELDATA/
        ├── CHARACTER/
        ├── MONSTER/
        ├── TEXT/
        ├── MENULIST/
        ├── TEXTURE/
        ├── MAP/
        └── ...(and any other RomFS folders, as-is)
```

`rom/` is already excluded via `.gitignore`, so placing your data there
won't accidentally get committed. Use existing 3DS ROM tools (e.g. GodMode9,
CTR-format tools) to dump your cartridge/CIA and extract its RomFS — that
process itself is not part of this repository.

If you'd rather keep your extracted RomFS somewhere else (e.g. shared with
another checkout), set the `DQ7_ROM_DIR` environment variable to that `rom/`
folder's path instead of placing it under the repository:

```
DQ7_ROM_DIR=/path/to/your/rom python3 server.py
```

### Running it

```
cd webapp
python3 server.py
```

See `webapp/server.py` for startup options and the API.

## Format documentation index

`docs/formats/` is split into subfolders that mirror the game's main data
areas.

### `exefs/` — ExeFS (`.code` executable) internals

| File | Covers |
|---|---|
| `exefs_master_structures.md` | Field/encounter-related structures inside ExeFS |
| `exefs_symbol_recovery.md` | ExeFS function symbol recovery |
| `save_player_data_container.md` | `PlayerDataContainer` and the NCCH/ExeFS container format |
| `party_change_menu.md` | Internals of the party-change menus |
| `scriptgroup_chapter_flags.md` | How chapter number and event flags are updated together |
| `symbol_notes.md` | Notes on field-symbol related data |
| `gameflag_bitfield.md` | `GameFlag` bitfield structure |

### `save/` — save file structure

| File | Covers |
|---|---|
| `save_data_structures.md` | Overall save data layout |
| `play_time_field.md` | Play-time field |
| `player_party_layout.md` | Party-related memory/save layout |

### `script/` — SCRIPT bytecode

| File | Covers |
|---|---|
| `script_opcodes.md` | `SCRIPT/*.bin` (event script) format |

### `leveldata/` — `LEVELDATA/*.dat` tables

| File | Covers |
|---|---|
| `camera_and_encounter_data.md` | Field camera and encounter data |
| `character_status_data.md` | Character status data files |
| `character_identity.md` | Model number ⇔ character ID mapping |
| `partytalk_format.md` | partytalk-series LEVELDATA file format |
| `map_code_naming.md` | Map file ID ⇔ in-game location mapping |
| `mamono_master_classes.md` | Battle task structure for the "monster tames you" sequence |
| `debug_data_tables.md` | Developer debug-related data |
| `motion_index_manager.md` | Motion resolution pipeline |

### `models/` — 3D models, animation, images

| File | Covers |
|---|---|
| `bcmdl_format.md` | CGFX (BCRES) / `.bcmdl` 3D model format |
| `canm_format.md` | Skeletal animation (CANM) format |
| `character_job_assets.md` | Character visual asset layout rules |
| `face_expression_textures.md` | Facial expression (blink/lip-sync) texture storage |
| `image_containers.md` | Image container formats (bctex/bcmdl/dmp/fpt) |

## Notes

This repository publishes only the factual data-structure findings from
analysis, and the source code of the viewer used to browse them. It
contains no copyrighted game assets (ROM itself, text, images, audio, or
copies thereof). Only extract data from software you legally own.
