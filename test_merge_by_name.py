"""Quick functional test for merge-by-name options. Run: uv run --with ifcopenshell python test_merge_by_name.py"""
import os, tempfile
import ifcopenshell, ifcopenshell.api.root, ifcopenshell.api.aggregate
import ifcopenshell.api.unit, ifcopenshell.api.context
import ifcopenshell.api.georeference
import mergeProjectsPlus as engine


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


def run_case(storeys_same_elevation, expect_storeys):
    tmp = tempfile.mkdtemp()
    a = os.path.join(tmp, "a.ifc")
    b = os.path.join(tmp, "b.ifc")
    out = os.path.join(tmp, "out.ifc")
    # Same site/building names; "L1" storeys at same elevation, "L2" at different ones
    make_file("Site A", "Bldg 1", [("L1", 0.0), ("L2", 3.0)]).write(a)
    make_file("Site A", "Bldg 1", [("L1", 0.0), ("L2", 99.0)]).write(b)
    engine.merge_files(a, [b], out, merge_sites=True, merge_buildings=True,
                       merge_storeys=True, storeys_same_elevation=storeys_same_elevation)
    m = ifcopenshell.open(out)
    sites = m.by_type("IfcSite")
    blds = m.by_type("IfcBuilding")
    storeys = m.by_type("IfcBuildingStorey")
    assert len(sites) == 1, f"expected 1 site, got {len(sites)}"
    assert len(blds) == 1, f"expected 1 building, got {len(blds)}"
    assert len(storeys) == expect_storeys, f"expected {expect_storeys} storeys, got {len(storeys)}"
    # All storeys must hang off the single remaining building
    for st in storeys:
        parent = engine._get_aggregate_parent(m, st)
        assert parent == blds[0], f"storey {st.Name} parented to {parent}"
    print(f"OK same_elevation={storeys_same_elevation}: 1 site, 1 building, {len(storeys)} storeys "
          f"({sorted((s.Name, s.Elevation) for s in storeys)})")


def run_case_no_merge():
    tmp = tempfile.mkdtemp()
    a = os.path.join(tmp, "a.ifc")
    b = os.path.join(tmp, "b.ifc")
    out = os.path.join(tmp, "out.ifc")
    make_file("Site A", "Bldg 1", [("L1", 0.0)]).write(a)
    make_file("Site A", "Bldg 1", [("L1", 0.0)]).write(b)
    engine.merge_files(a, [b], out)  # all options off
    m = ifcopenshell.open(out)
    assert len(m.by_type("IfcSite")) == 2
    assert len(m.by_type("IfcBuilding")) == 2
    assert len(m.by_type("IfcBuildingStorey")) == 2
    print("OK options off: duplicates preserved (2 sites, 2 buildings, 2 storeys)")


def make_unit_file(site_name, x, raw_units="MILLIMETERS", georef=False):
    """File in the given length units, site placed at x (in those units)."""
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": raw_units})
    ifcopenshell.api.context.add_context(f, context_type="Model")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name=site_name)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    pt = f.createIfcCartesianPoint((float(x), 0.0, 0.0))
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


def site_positions(f):
    return {s.Name: s.ObjectPlacement.RelativePlacement.Location.Coordinates[0]
            for s in f.by_type("IfcSite")}


def run_case_mm_safe():
    """Regression: all-mm files (even with differing georeferencing) must
    merge without moving or rescaling geometry."""
    tmp = tempfile.mkdtemp()
    a, b, out = (os.path.join(tmp, n) for n in ("a.ifc", "b.ifc", "out.ifc"))
    make_unit_file("Site A", 5000.0, "MILLIMETERS", georef=True).write(a)
    make_unit_file("Site B", 7000.0, "MILLIMETERS", georef=False).write(b)
    engine.merge_files(a, [b], out)
    m = ifcopenshell.open(out)
    xs = site_positions(m)
    assert abs(xs["Site A"] - 5000.0) < 1e-6, xs
    assert abs(xs["Site B"] - 7000.0) < 1e-6, xs
    assert engine.get_length_unit_name(m) == "MILLIMETRE"
    print(f"OK all-mm merge: placements intact, units MILLIMETRE ({xs})")


def run_case_mixed_units():
    """Other file in metres gets converted into the base's millimetres."""
    tmp = tempfile.mkdtemp()
    a, b, out = (os.path.join(tmp, n) for n in ("a.ifc", "b.ifc", "out.ifc"))
    make_unit_file("Site A", 5000.0, "MILLIMETERS").write(a)
    make_unit_file("Site B", 7.0, "METERS").write(b)
    engine.merge_files(a, [b], out)
    m = ifcopenshell.open(out)
    xs = site_positions(m)
    assert abs(xs["Site A"] - 5000.0) < 1e-6, xs
    assert abs(xs["Site B"] - 7000.0) < 1e-6, xs
    print(f"OK mixed-unit merge: metres converted to mm ({xs})")


if __name__ == "__main__":
    # With elevation check: L1+L1 merge (same elev), L2s stay apart -> 3 storeys
    run_case(storeys_same_elevation=True, expect_storeys=3)
    # Without elevation check: L1s and L2s both merge by name -> 2 storeys
    run_case(storeys_same_elevation=False, expect_storeys=2)
    run_case_no_merge()
    run_case_mm_safe()
    run_case_mixed_units()
    print("All tests passed.")
