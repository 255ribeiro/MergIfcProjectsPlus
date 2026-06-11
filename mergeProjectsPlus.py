"""
mergeProjectsPlus.py — MergeProjectsPlus recipe engine (UI-free).
Superset of ifcpatch MergeProjects: merges N files, converts units,
dedups geometric contexts, optional incremental merge via temp folder.
Drop into ifcpatch/recipes/ later to become a native recipe.
"""
from __future__ import annotations
import json, logging, os
from typing import Sequence, Union
import ifcopenshell, ifcopenshell.util.element, ifcopenshell.util.unit

log = logging.getLogger(__name__)

def to_bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true","1","yes","on")

def get_length_unit_name(f):
    try:
        unit = ifcopenshell.util.unit.get_project_unit(f, "LENGTHUNIT")
        if unit is not None:
            return ifcopenshell.util.unit.get_full_unit_name(unit)
    except Exception: pass
    try:
        for u in f.by_type("IfcSIUnit"):
            if u.UnitType == "LENGTHUNIT":
                return f"{(u.Prefix or '').upper()}{(u.Name or '').upper()}".strip() or "METRE"
    except Exception: pass
    return "METRE"

def get_equivalent_context(existing_contexts, added_ctx):
    """Same matching rules as ifcpatch MergeProjects: subcontexts also
    compare TargetView, plain contexts only type + identifier."""
    for ctx in existing_contexts:
        if ctx.is_a() != added_ctx.is_a():
            continue
        if ctx.is_a("IfcGeometricRepresentationSubContext"):
            if (ctx.ContextType == added_ctx.ContextType
                    and ctx.ContextIdentifier == added_ctx.ContextIdentifier
                    and ctx.TargetView == added_ctx.TargetView):
                return ctx
        elif (ctx.ContextType == added_ctx.ContextType
                and ctx.ContextIdentifier == added_ctx.ContextIdentifier):
            return ctx
    return None

def merge_into(base, other, logger=log):
    """MergeProjects-style merge without its geolocation alignment, which
    mixes project and map units (a 1000x error on millimetre models) when
    the files' georeferencing differs."""
    bu, ou = get_length_unit_name(base), get_length_unit_name(other)
    if bu != ou:
        try:
            other = ifcopenshell.util.unit.convert_file_length_units(other, bu)
        except Exception as e:
            logger.warning("unit convert failed: %s", e)

    existing_contexts = base.by_type("IfcGeometricRepresentationContext")
    added_contexts = set()

    bp = base.by_type("IfcProject")[0]
    ops = other.by_type("IfcProject")
    merged_project = base.add(ops[0]) if ops else None

    for ent in other.by_type("IfcGeometricRepresentationContext"):
        added_contexts.add(base.add(ent))
    for ent in other:
        try: base.add(ent)
        except Exception: pass

    if merged_project is not None:
        for inv in base.get_inverse(merged_project):
            try: ifcopenshell.util.element.replace_attribute(inv, merged_project, bp)
            except Exception: pass
        try: base.remove(merged_project)
        except Exception: pass

    to_delete = set()
    for ac in added_contexts:
        ex = get_equivalent_context(existing_contexts, ac)
        if not ex or ex == ac:
            continue
        for inv in base.get_inverse(ac):
            if base.schema != "IFC2X3" and inv.is_a("IfcCoordinateOperation"):
                to_delete.add(inv.id())
                continue
            try: ifcopenshell.util.element.replace_attribute(inv, ac, ex)
            except Exception: pass
        to_delete.add(ac.id())
    for eid in to_delete:
        try: ifcopenshell.util.element.remove_deep2(base, base.by_id(eid))
        except Exception: pass

def _get_aggregate_parent(f, elem):
    for rel in f.by_type("IfcRelAggregates"):
        if elem in (rel.RelatedObjects or ()):
            return rel.RelatingObject
    return None

def _merge_duplicate_into(f, keeper, dup, logger=log):
    # Detach dup from its parent aggregation (keeper already hangs there;
    # Decomposes is SET [0:1], so dup may not simply be repointed).
    for rel in f.by_type("IfcRelAggregates"):
        if dup in (rel.RelatedObjects or ()):
            remaining = [o for o in rel.RelatedObjects if o != dup]
            if remaining:
                rel.RelatedObjects = remaining
            else:
                try: f.remove(rel)
                except Exception: pass
    # Everything else referencing dup (children aggregations, contained
    # elements, psets, ...) now points at keeper instead.
    for inv in f.get_inverse(dup):
        try: ifcopenshell.util.element.replace_attribute(inv, dup, keeper)
        except Exception: pass
    # Keep dup's placement if children still chain through it, so geometry
    # stays where it was; drop it only when nothing references it anymore.
    placement = getattr(dup, "ObjectPlacement", None)
    try: f.remove(dup)
    except Exception: pass
    if placement is not None:
        try:
            if not f.get_inverse(placement):
                f.remove(placement)
        except Exception: pass

def merge_spatial_by_name(f, ifc_class, match_elevation=False, logger=log):
    """Merge same-named ifc_class elements that share the same parent.
    With match_elevation, storeys also need (near-)equal Elevation."""
    groups = {}
    for e in f.by_type(ifc_class):
        name = (e.Name or "").strip()
        if not name:
            continue  # never merge unnamed elements
        parent = _get_aggregate_parent(f, e)
        key = [name, parent.id() if parent is not None else -1]
        if match_elevation:
            elev = getattr(e, "Elevation", None)
            key.append(None if elev is None else round(float(elev), 5))
        groups.setdefault(tuple(key), []).append(e)
    merged = 0
    for group in groups.values():
        keeper = group[0]
        for dup in group[1:]:
            try:
                _merge_duplicate_into(f, keeper, dup, logger)
                merged += 1
            except Exception as e:
                logger.error("merge %s '%s' failed: %s", ifc_class, keeper.Name, e)
    if merged:
        logger.info("merged %d duplicate %s by name", merged, ifc_class)
    return merged

def apply_spatial_merges(f, merge_sites=False, merge_buildings=False,
                         merge_storeys=False, storeys_same_elevation=False,
                         logger=log):
    # Top-down so children regroup under already-merged parents.
    if merge_sites:
        merge_spatial_by_name(f, "IfcSite", logger=logger)
    if merge_buildings:
        merge_spatial_by_name(f, "IfcBuilding", logger=logger)
    if merge_storeys:
        merge_spatial_by_name(f, "IfcBuildingStorey",
                              match_elevation=storeys_same_elevation, logger=logger)

def merge_files(base_path, other_paths, output_path,
                use_incremental=False, keep_temp=True, logger=log,
                merge_sites=False, merge_buildings=False,
                merge_storeys=False, storeys_same_elevation=False):
    base = ifcopenshell.open(base_path)
    if not other_paths:
        apply_spatial_merges(base, merge_sites, merge_buildings,
                             merge_storeys, storeys_same_elevation, logger)
        base.write(output_path); return base
    if use_incremental:
        return _merge_incremental(base, other_paths, output_path, keep_temp, logger,
                                  merge_sites, merge_buildings,
                                  merge_storeys, storeys_same_elevation)
    for p in other_paths:
        try: merge_into(base, ifcopenshell.open(p), logger)
        except Exception as e: logger.error("merge failed %s: %s", p, e)
    apply_spatial_merges(base, merge_sites, merge_buildings,
                         merge_storeys, storeys_same_elevation, logger)
    base.write(output_path)
    return base

def _merge_incremental(base, other_paths, output_path, keep_temp, logger,
                       merge_sites=False, merge_buildings=False,
                       merge_storeys=False, storeys_same_elevation=False):
    import shutil
    out_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
    tmp = os.path.join(out_dir, "merge_project_plus_tmp")
    os.makedirs(tmp, exist_ok=True)
    step = os.path.join(tmp, "tmp_step_000.ifc")
    base.write(step)

    total = len(other_paths)

    def _progress(done, total, label=""):
        bar_len = 30
        filled = int(bar_len * done / total) if total else bar_len
        bar = "█" * filled + "-" * (bar_len - filled)
        pct = (done / total * 100) if total else 100
        # \r returns to line start so the bar updates in place
        print(f"\r[MergeProjectsPlus] |{bar}| {done}/{total} ({pct:5.1f}%) {label[:30]:<30}",
              end="", flush=True)

    _progress(0, total, "starting")
    for i, p in enumerate(other_paths, 1):
        nxt = os.path.join(tmp, f"tmp_step_{i:03d}.ifc")
        try:
            bm = ifcopenshell.open(step)
            merge_into(bm, ifcopenshell.open(p), logger)
            bm.write(nxt)
            step = nxt
        except Exception as e:
            logger.error("step %03d failed: %s", i, e)
        _progress(i, total, os.path.basename(p))

    print()  # newline after the bar completes

    final = ifcopenshell.open(step)
    apply_spatial_merges(final, merge_sites, merge_buildings,
                         merge_storeys, storeys_same_elevation, logger)
    final.write(output_path)
    if not keep_temp:
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass
    return final

class Patcher:
    """ifcpatch-compatible: args = filepaths, use_incremental, output_path, keep_temp,
    merge_sites, merge_buildings, merge_storeys, storeys_same_elevation"""
    def __init__(self, file, logger=None, filepaths=(), use_incremental=False,
                 output_path="", keep_temp=True, merge_sites=False,
                 merge_buildings=False, merge_storeys=False,
                 storeys_same_elevation=False):
        self.file = file; self.logger = logger or log
        r = []
        if isinstance(filepaths, str):
            s = filepaths.strip()
            if s.startswith("["): r = [p for p in json.loads(s) if p]
            elif s: r = [p.strip() for p in s.split(",") if p.strip()]
        else:
            r = [fp.strip() for fp in filepaths if isinstance(fp,str) and fp.strip()]
        self.filepaths = r
        self.use_incremental = to_bool(use_incremental)
        self.output_path = output_path or ""
        self.keep_temp = to_bool(keep_temp)
        self.merge_sites = to_bool(merge_sites)
        self.merge_buildings = to_bool(merge_buildings)
        self.merge_storeys = to_bool(merge_storeys)
        self.storeys_same_elevation = to_bool(storeys_same_elevation)

    def patch(self):
        if not self.filepaths:
            self.logger.warning("MergeProjectsPlus: nothing to merge"); return
        if self.use_incremental and self.output_path:
            out_dir = os.path.dirname(os.path.abspath(self.output_path)) or os.getcwd()
            tmp = os.path.join(out_dir, "merge_project_plus_tmp")
            os.makedirs(tmp, exist_ok=True)
            bt = os.path.join(tmp, "tmp_base.ifc"); self.file.write(bt)
            merged = _merge_incremental(ifcopenshell.open(bt), self.filepaths,
                self.output_path, self.keep_temp, self.logger,
                self.merge_sites, self.merge_buildings,
                self.merge_storeys, self.storeys_same_elevation)
            for e in list(self.file):
                try: self.file.remove(e)
                except Exception: pass
            for e in merged:
                try: self.file.add(e)
                except Exception: pass
        else:
            for p in self.filepaths:
                try: merge_into(self.file, ifcopenshell.open(p), self.logger)
                except Exception as e: self.logger.error("failed %s: %s", p, e)
            apply_spatial_merges(self.file, self.merge_sites, self.merge_buildings,
                self.merge_storeys, self.storeys_same_elevation, self.logger)