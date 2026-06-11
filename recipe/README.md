# MergeProjectsPlus as a native ifcpatch recipe

This folder turns MergeProjectsPlus into a plain [ifcpatch](https://docs.ifcopenshell.org/ifcpatch.html)
recipe. Once installed, it appears in Bonsai's native IFC Patch UI
(**Scene Properties → Quality and Control → IFC Patch**) and its options are
drawn automatically from the recipe signature — no custom panel needed.

The recipe subclasses Bonsai's bundled `MergeProjects` recipe, so it inherits
its automatic length-unit conversion, and adds optional deduplication of the
spatial hierarchy on top. MergeProjects' geolocation/false-origin alignment is
**disabled by default** (see `align_geolocation` below): it mixes up project
and map units when the models' georeferencing differs, which shifts or scales
the merged geometry by 1000× for millimetre models.

## Files

| File | Purpose |
|---|---|
| `MergeProjectsPlus.py` | The self-contained ifcpatch recipe |
| `addon/` | Tiny installer addon: copies the recipe into Bonsai's `ifcpatch/recipes/` |
| `test_recipe.py` | Tests (merge logic + the `extract_docs` call Bonsai uses to draw the UI) |

## Install

**Option A — installer addon (recommended):** copy `MergeProjectsPlus.py` into
`addon/`, zip the `addon/` folder, and install it as a Blender extension
("Install from Disk"). Enabling it copies the recipe into Bonsai's
`ifcpatch/recipes/` folder. After a Bonsai update, re-enable the addon or press
**Install / Reinstall Recipe** in its addon preferences. (In the development
layout the installer also finds the recipe one level above `addon/`, so no
copy is needed when running from this repo.)

**Option B — manual copy:** drop `MergeProjectsPlus.py` into Bonsai's bundled
recipes folder, e.g.

```
%APPDATA%\Blender Foundation\Blender\<version>\extensions\.local\lib\python3.13\site-packages\ifcpatch\recipes\
```

## Usage

1. Open or link your base IFC project in Bonsai (or pick an input file).
2. Scene Properties → Quality and Control → IFC Patch.
3. Select recipe **MergeProjectsPlus** ("Load from Memory" merges into the
   currently open project).
4. Pick the other IFC file and tick the options:
   - **merge_sites** — combine same-named IfcSite elements
   - **merge_buildings** — combine same-named IfcBuilding elements (within the same site)
   - **merge_storeys** — combine same-named IfcBuildingStorey elements (within the same building)
   - **storeys_same_elevation** — only combine same-named storeys whose
     Elevation also matches (*only has an effect when merge_storeys is on* —
     the auto-generated UI cannot nest it under the storey checkbox)
5. Run. Repeat with another file to merge more than two projects.

Also works headless:

```python
import ifcpatch, ifcopenshell
model = ifcopenshell.open("a.ifc")
out = ifcpatch.execute({"input": "a.ifc", "file": model, "recipe": "MergeProjectsPlus",
                        "arguments": ["b.ifc", True, True, True, True]})
ifcpatch.write(out, "merged.ifc")
```

## Tests

```
uv run --with ifcpatch --with ifcopenshell python recipe/test_recipe.py
```

## Notes / limitations vs. the panel addon

The original rich-panel addon in the repo root is untouched and still works;
this recipe is an alternative front-end with native UI. Trade-offs of the
recipe form: one extra file per run (no multi-file list in Bonsai's auto-UI),
no linked-files picker, no incremental temp-folder merge, and the
`storeys_same_elevation` checkbox is always visible instead of nested.
