# BIM: Merge Project Plus

A Blender add-on for Bonsai (BlenderBIM) that merges multiple IFC files into
one. A superset of the standard ifcpatch `MergeProjects` recipe: it merges
linked files, manually-added file paths, and the active project — together,
in one pass — with an optional step-by-step incremental merge.

## File tree

```
merge_project_plus_addon.zip
├── blender_manifest.toml     Extension metadata (Blender 4.2+ format)
├── __init__.py               Add-on: UI panel, operators, properties
├── mergeProjectPlus.py       Engine: merge logic (UI-free, reusable)
└── README.md                 This file
```

## How it works

- `mergeProjectPlus.py` is the **engine** — pure merge logic with no UI.
  It exposes `merge_files()` (called by the add-on) and an ifcpatch-compatible
  `Patcher` class (for future use as a native recipe).
- `__init__.py` is the **add-on** — it loads the engine from the same folder
  and calls it directly. No ifcpatch recipe registration, no Blender restart.

## Requirements

| | Version |
|---|---|
| Blender | 4.2 or later (tested on 5.1) |
| Bonsai (BlenderBIM) | 0.8.5 or later |

## Installation

1. Edit → Preferences → Add-ons → ⌄ dropdown → **Install from Disk…**
   (or drag the zip onto the Blender window).
2. Select `merge_project_plus_addon.zip`.
3. Enable **BIM: Merge Project Plus**.

## Usage

Open **Scene Properties → Merge Project Plus** panel.

1. **Refresh** to load linked IFC files (from Bonsai's IFC Links).
2. Tick which linked files to include.
3. Optionally tick **Include loaded project** to add the active model.
4. Optionally tick **Add file paths manually** to pick extra IFC files
   via the file browser. Linked + manual files merge together.
5. Set the **Output File** path.
6. Click **Merge N Files**.

## Incremental merge

Tick **Use temporary incremental merge** to merge one file at a time. Each
step is written to `merge_project_plus_tmp/` next to the output file:

```
merge_project_plus_tmp/
  tmp_step_000.ifc   base model
  tmp_step_001.ifc   base + file 1
  tmp_step_002.ifc   step_001 + file 2
  ...
```

A live progress bar prints to the system console (Window → Toggle System
Console) as each file merges:

```
[MergeProjectPlus] |████████████------------------| 2/5 ( 40.0%) mep_hvac.ifc
```

Untick **Keep temp folder** to auto-delete the temp files when done.

## Notes

- At least 2 files must be selected to merge.
- Duplicate spatial elements (sites, buildings, storeys) are not auto-merged —
  this matches standard MergeProjects behaviour.
- The engine converts length units and de-duplicates geometric contexts
  automatically.

## Roadmap

The engine's `Patcher` class is already ifcpatch-compatible, so
`mergeProjectPlus.py` can later be dropped into the ifcpatch `recipes/` folder
to become a native recipe — with a view to contributing upstream to
IfcOpenShell / Bonsai.