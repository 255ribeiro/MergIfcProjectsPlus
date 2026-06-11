"""Repro: merging two millimetre files reportedly degenerates geometry / scales 1000x.
Run: uv run --with ifcpatch --with ifcopenshell python recipe/repro_mm_bug.py"""
import importlib.util
import logging
import os
import tempfile

import ifcopenshell
import ifcopenshell.api.root, ifcopenshell.api.aggregate
import ifcopenshell.api.unit, ifcopenshell.api.context
import ifcopenshell.util.unit
try:
    import ifcopenshell.api.georeference
except ImportError:
    pass
import ifcpatch
import ifcpatch.recipes.MergeProjects as MP

logging.basicConfig(level=logging.INFO)
HERE = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location("MergeProjectsPlus", os.path.join(HERE, "MergeProjectsPlus.py"))
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)

# ── instrument the steps that could rescale ─────────────────────────
orig_convert = ifcopenshell.util.unit.convert_file_length_units
def spy_convert(f, target):
    print(f"  !! convert_file_length_units CALLED, target={target}")
    return orig_convert(f, target)

orig_sfo_patch = MP.SetFalseOrigin.patch
def spy_sfo(self):
    print(f"  !! SetFalseOrigin CALLED x={self.x} y={self.y} z={self.z} e={self.e} n={self.n} h={self.h}")
    return orig_sfo_patch(self)

def make_mm_file(site_name, x_mm, georef=False):
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "MILLIMETERS"})
    ifcopenshell.api.context.add_context(f, context_type="Model")
    project = f.by_type("IfcProject")[0]
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name=site_name)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    # site placed at x_mm millimetres
    pt = f.createIfcCartesianPoint((float(x_mm), 0.0, 0.0))
    ax = f.createIfcAxis2Placement3D(pt, None, None)
    site.ObjectPlacement = f.createIfcLocalPlacement(None, ax)
    if georef:
        try:
            ifcopenshell.api.georeference.add_georeferencing(f)
            ifcopenshell.api.georeference.edit_georeferencing(
                f,
                projected_crs={"Name": "EPSG:31983"},
                coordinate_operation={"Eastings": 333000.0, "Northings": 7395000.0,
                                      "OrthogonalHeight": 0.0, "Scale": 0.001},
            )
        except Exception as e:
            print(f"  (georef setup failed: {e})")
    return f

def site_x(f, name):
    for s in f.by_type("IfcSite"):
        if s.Name == name:
            return s.ObjectPlacement.RelativePlacement.Location.Coordinates[0]
    return None

def unit_name(f):
    u = ifcopenshell.util.unit.get_project_unit(f, "LENGTHUNIT")
    return ifcopenshell.util.unit.get_full_unit_name(u)

def run(label, georef_a, georef_b):
    print(f"\n=== {label} ===")
    ifcopenshell.util.unit.convert_file_length_units = spy_convert
    MP.SetFalseOrigin.patch = spy_sfo
    try:
        tmp = tempfile.mkdtemp()
        a = make_mm_file("Site A", 5000.0, georef=georef_a)
        b = make_mm_file("Site B", 7000.0, georef=georef_b)
        bp = os.path.join(tmp, "b.ifc")
        b.write(bp)
        print(f"  units: a={unit_name(a)} b={unit_name(b)}")
        print(f"  before: Site A x={site_x(a, 'Site A')}  Site B x={site_x(b, 'Site B')}")
        recipe.Patcher(a, logging.getLogger("repro"), filepath=bp).patch()
        xa, xb = site_x(a, "Site A"), site_x(a, "Site B")
        print(f"  after : Site A x={xa}  Site B x={xb}  (expected 5000 / 7000)")
        if xb is not None and abs(xb - 7000.0) > 1.0:
            print(f"  >>> BUG REPRODUCED: Site B moved/scaled by factor {xb/7000.0}")
    finally:
        ifcopenshell.util.unit.convert_file_length_units = orig_convert
        MP.SetFalseOrigin.patch = orig_sfo_patch

if __name__ == "__main__":
    print(f"ifcopenshell {ifcopenshell.version}")
    run("both mm, no georeferencing", False, False)
    run("both mm, both georeferenced (same origin)", True, True)
    run("both mm, only base georeferenced", True, False)
