"""Tests for the MergeProjectsPlus ifcpatch recipe.
Run: uv run --with ifcpatch --with ifcopenshell python recipe/test_recipe.py"""
import importlib.util
import logging
import os
import shutil
import tempfile

import ifcopenshell
import ifcopenshell.api.root, ifcopenshell.api.aggregate
import ifcopenshell.api.unit, ifcopenshell.api.context
import ifcpatch

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPE = os.path.join(HERE, "MergeProjectsPlus.py")
ARGS = ("filepath", "merge_sites", "merge_buildings", "merge_storeys",
        "storeys_same_elevation", "align_geolocation")


def load_recipe_module():
    spec = importlib.util.spec_from_file_location("MergeProjectsPlus", RECIPE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


recipe = load_recipe_module()


def make_file(site_name, building_name, storey_specs):
    """storey_specs: list of (name, elevation)"""
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(f)
    ifcopenshell.api.context.add_context(f, context_type="Model")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name=site_name)
    bld = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name=building_name)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[bld], relating_object=site)
    for name, elev in storey_specs:
        st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=name)
        st.Elevation = elev
        ifcopenshell.api.aggregate.assign_object(f, products=[st], relating_object=bld)
    return f


def run_patch(**options):
    tmp = tempfile.mkdtemp()
    other = os.path.join(tmp, "other.ifc")
    # Same site/building names; "L1" storeys at same elevation, "L2" at different ones
    model = make_file("Site A", "Bldg 1", [("L1", 0.0), ("L2", 3.0)])
    make_file("Site A", "Bldg 1", [("L1", 0.0), ("L2", 99.0)]).write(other)
    recipe.Patcher(model, logging.getLogger("test"), filepath=other, **options).patch()
    return model


def run_case(storeys_same_elevation, expect_storeys):
    m = run_patch(merge_sites=True, merge_buildings=True, merge_storeys=True,
                  storeys_same_elevation=storeys_same_elevation)
    sites = m.by_type("IfcSite")
    blds = m.by_type("IfcBuilding")
    storeys = m.by_type("IfcBuildingStorey")
    assert len(sites) == 1, f"expected 1 site, got {len(sites)}"
    assert len(blds) == 1, f"expected 1 building, got {len(blds)}"
    assert len(storeys) == expect_storeys, f"expected {expect_storeys} storeys, got {len(storeys)}"
    for st in storeys:
        parent = recipe.get_aggregate_parent(m, st)
        assert parent == blds[0], f"storey {st.Name} parented to {parent}"
    print(f"OK same_elevation={storeys_same_elevation}: 1 site, 1 building, {len(storeys)} storeys "
          f"({sorted((s.Name, s.Elevation) for s in storeys)})")


def run_case_no_merge():
    m = run_patch(merge_sites=False, merge_buildings=False, merge_storeys=False)
    assert len(m.by_type("IfcSite")) == 2
    assert len(m.by_type("IfcBuilding")) == 2
    assert len(m.by_type("IfcBuildingStorey")) == 4
    print("OK options off: duplicates preserved (2 sites, 2 buildings, 4 storeys)")


def make_mm_file(site_name, x_mm, georef=False):
    """Millimetre-unit file with the site placed at x_mm; optionally georeferenced."""
    import ifcopenshell.api.georeference
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "MILLIMETERS"})
    ifcopenshell.api.context.add_context(f, context_type="Model")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name=site_name)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    pt = f.createIfcCartesianPoint((float(x_mm), 0.0, 0.0))
    ax = f.createIfcAxis2Placement3D(pt, None, None)
    site.ObjectPlacement = f.createIfcLocalPlacement(None, ax)
    if georef:
        ifcopenshell.api.georeference.add_georeferencing(f)
        ifcopenshell.api.georeference.edit_georeferencing(
            f,
            projected_crs={"Name": "EPSG:31983"},
            coordinate_operation={"Eastings": 333000.0, "Northings": 7395000.0,
                                  "OrthogonalHeight": 0.0, "Scale": 0.001},
        )
    return f


def run_case_mm_georef():
    """Regression: merging mm files with differing georeferencing must not
    move/scale geometry (inherited SetFalseOrigin alignment is off by default)."""
    tmp = tempfile.mkdtemp()
    other = os.path.join(tmp, "other.ifc")
    model = make_mm_file("Site A", 5000.0, georef=True)
    make_mm_file("Site B", 7000.0, georef=False).write(other)
    recipe.Patcher(model, logging.getLogger("test"), filepath=other).patch()
    xs = {s.Name: s.ObjectPlacement.RelativePlacement.Location.Coordinates[0]
          for s in model.by_type("IfcSite")}
    assert abs(xs["Site A"] - 5000.0) < 1e-6, xs
    assert abs(xs["Site B"] - 7000.0) < 1e-6, xs
    print(f"OK mm + differing georeferencing: placements intact ({xs})")


def arg_names(inputs):
    if isinstance(inputs, dict):
        return list(inputs)
    out = []
    for i in inputs:
        if isinstance(i, dict):
            out.append(i.get("name"))
        else:
            out.append(getattr(i, "name", None))
    return out


def run_docs_check():
    """Exactly what Bonsai does to draw the recipe UI: copy the recipe into
    ifcpatch/recipes and run extract_docs on it."""
    recipes_dir = os.path.join(os.path.dirname(os.path.abspath(ifcpatch.__file__)), "recipes")
    dst = os.path.join(recipes_dir, os.path.basename(RECIPE))
    shutil.copyfile(RECIPE, dst)
    try:
        docs = ifcpatch.extract_docs("MergeProjectsPlus", "Patcher", "__init__",
                                     ("src", "file", "logger", "args"))
        assert docs, "extract_docs returned nothing"
        inputs = docs["inputs"] if isinstance(docs, dict) else getattr(docs, "inputs")
        names = arg_names(inputs)
        assert names == list(ARGS), f"expected args {ARGS}, got {names}"
        print(f"OK extract_docs: {names}")
        print(f"   raw inputs: {inputs}")
    finally:
        try:
            os.remove(dst)
        except OSError:
            pass


if __name__ == "__main__":
    # With elevation check: L1+L1 merge (same elev), L2s stay apart -> 3 storeys
    run_case(storeys_same_elevation=True, expect_storeys=3)
    # Without elevation check: L1s and L2s both merge by name -> 2 storeys
    run_case(storeys_same_elevation=False, expect_storeys=2)
    run_case_no_merge()
    run_case_mm_georef()
    run_docs_check()
    print("All tests passed.")
