"""
mergeProjectsPlus.py — MergeProjectsPlus recipe engine (UI-free).
Superset of ifcpatch MergeProjects: merges N files, converts units,
dedups geometric contexts, optional incremental merge via temp folder.
Drop into ifcpatch/recipes/ later to become a native recipe.
"""
from __future__ import annotations
import json, logging, os
from typing import Sequence, Union
import ifcopenshell, ifcopenshell.util.element

log = logging.getLogger(__name__)

def to_bool(v): 
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true","1","yes","on")

def get_length_unit_name(f):
    try:
        for u in f.by_type("IfcSIUnit"):
            if u.UnitType == "LENGTHUNIT":
                return f"{(u.Prefix or '').upper()}{(u.Name or '').upper()}".strip() or "METRE"
    except Exception: pass
    return "METRE"

def get_equivalent_context(base, other_ctx):
    try:
        t, i, v = other_ctx.ContextType, other_ctx.ContextIdentifier, other_ctx.TargetView
    except Exception: return None
    for e in base.by_type("IfcGeometricRepresentationContext"):
        if (getattr(e,"ContextType",None)==t and getattr(e,"ContextIdentifier",None)==i
                and getattr(e,"TargetView",None)==v):
            return e
    return None

def merge_into(base, other, logger=log):
    bu, ou = get_length_unit_name(base), get_length_unit_name(other)
    if bu != ou:
        try:
            import ifcpatch
            other = ifcpatch.execute({"input":"in.ifc","file":other,
                "recipe":"ConvertLengthUnit","arguments":[bu]})
        except Exception as e:
            logger.warning("unit convert failed: %s", e)
    bp = base.by_type("IfcProject")[0]
    ops = other.by_type("IfcProject")
    op = ops[0] if ops else None
    added = {}
    for ent in other:
        if op is not None and ent == op: continue
        try: added[ent.id()] = base.add(ent)
        except Exception: pass
    if op is not None:
        for rel in other.by_type("IfcRelAggregates"):
            if rel.RelatingObject == op and rel.id() in added:
                try: added[rel.id()].RelatingObject = bp
                except Exception: pass
    for ent in other.by_type("IfcGeometricRepresentationContext"):
        if ent.id() not in added: continue
        ac = added[ent.id()]
        ex = get_equivalent_context(base, ent)
        if ex and ex != ac:
            for inv in base.get_inverse(ac):
                try: ifcopenshell.util.element.replace_attribute(inv, ac, ex)
                except Exception: pass
            try: base.remove(ac)
            except Exception: pass

def merge_files(base_path, other_paths, output_path,
                use_incremental=False, keep_temp=True, logger=log):
    base = ifcopenshell.open(base_path)
    if not other_paths:
        base.write(output_path); return base
    if use_incremental:
        return _merge_incremental(base, other_paths, output_path, keep_temp, logger)
    for p in other_paths:
        try: merge_into(base, ifcopenshell.open(p), logger)
        except Exception as e: logger.error("merge failed %s: %s", p, e)
    base.write(output_path)
    return base

def _merge_incremental(base, other_paths, output_path, keep_temp, logger):
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
    final.write(output_path)
    if not keep_temp:
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass
    return final

class Patcher:
    """ifcpatch-compatible: args = filepaths, use_incremental, output_path, keep_temp"""
    def __init__(self, file, logger=None, filepaths=(), use_incremental=False,
                 output_path="", keep_temp=True):
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

    def patch(self):
        if not self.filepaths:
            self.logger.warning("MergeProjectsPlus: nothing to merge"); return
        if self.use_incremental and self.output_path:
            out_dir = os.path.dirname(os.path.abspath(self.output_path)) or os.getcwd()
            tmp = os.path.join(out_dir, "merge_project_plus_tmp")
            os.makedirs(tmp, exist_ok=True)
            bt = os.path.join(tmp, "tmp_base.ifc"); self.file.write(bt)
            merged = _merge_incremental(ifcopenshell.open(bt), self.filepaths,
                self.output_path, self.keep_temp, self.logger)
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