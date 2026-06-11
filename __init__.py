# __init__.py — BIM: Merge Project Plus
bl_info = {
    "name": "BIM: Merge Project Plus",
    "author": "Custom",
    "version": (2, 2, 0),
    "blender": (4, 2, 0),
    "location": "Scene Properties → Quality and Control → Merge Project Plus",
    "description": "Merge linked + manually-added IFC files into one output.",
    "category": "BIM",
}

import json
import os
import importlib.util

import bpy
from bpy.props import (
    BoolProperty, StringProperty, CollectionProperty, PointerProperty,
    EnumProperty,
)
from bpy.types import PropertyGroup, Operator, Panel


# ─────────────────────────────────────────────────────────────
# Load the engine module that sits next to this file
# ─────────────────────────────────────────────────────────────
def _load_engine():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "mergeProjectsPlus.py")
    spec = importlib.util.spec_from_file_location("mergeProjectsPlus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    engine = _load_engine()
except Exception as e:
    engine = None
    print(f"[MergeProjectsPlus] Could not load engine: {e}")


# ─────────────────────────────────────────────────────────────
# Bonsai helpers
# ─────────────────────────────────────────────────────────────
def _bonsai_available():
    try:
        import bonsai  # noqa
        return True
    except ImportError:
        return False


def _get_linked_paths(context):
    """Confirmed: BIMProjectProperties.links[*].filepath"""
    try:
        links = context.scene.BIMProjectProperties.links
        out = []
        for lnk in links:
            p = getattr(lnk, "filepath", None)
            if p and isinstance(p, str) and p.strip():
                out.append(p.strip())
        return out
    except Exception as e:
        print(f"[MergeProjectsPlus] links read failed: {e}")
        return []


def _get_active_ifc_path(context):
    try:
        return context.scene.BIMProperties.ifc_file or ""
    except Exception:
        return ""


def _gather_merge_paths(context):
    """Ordered, de-duplicated list of all files selected for the merge."""
    props = context.scene.MPPProps
    paths = [i.filepath for i in props.linked_files if i.selected and i.filepath]
    if props.use_manual_paths:
        paths += [m.filepath for m in props.manual_files if m.selected and m.filepath]
    active = _get_active_ifc_path(context)
    if props.include_active and active and active not in paths:
        paths.insert(0, active)
    seen, ordered = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


# ─────────────────────────────────────────────────────────────
# Property groups
# ─────────────────────────────────────────────────────────────
class MPP_LinkedItem(PropertyGroup):
    filepath: StringProperty()
    selected: BoolProperty(default=True)


class MPP_ManualItem(PropertyGroup):
    filepath: StringProperty()
    selected: BoolProperty(default=True)


class MPP_Props(PropertyGroup):
    linked_files: CollectionProperty(type=MPP_LinkedItem)
    manual_files: CollectionProperty(type=MPP_ManualItem)
    use_manual_paths: BoolProperty(
        name="Add file paths manually",
        description="Reveal a list to add IFC files by path (merged together with linked files)",
        default=False,
    )
    include_active: BoolProperty(
        name="Include loaded project",
        description="Also merge the IFC project currently open in Bonsai",
        default=False,
    )
    use_incremental: BoolProperty(
        name="Use temporary incremental merge",
        description="Merge one file at a time, saving each step to a temp folder (safer but slowest)",
        default=False,
    )
    merge_sites_by_name: BoolProperty(
        name="Merge sites by name",
        description="After merging, combine IfcSite elements that share the same name into one",
        default=False,
    )
    merge_buildings_by_name: BoolProperty(
        name="Merge buildings by name",
        description="After merging, combine IfcBuilding elements with the same name (under the same site) into one",
        default=False,
    )
    merge_storeys_by_name: BoolProperty(
        name="Merge storeys by name",
        description="After merging, combine IfcBuildingStorey elements with the same name (in the same building) into one",
        default=False,
    )
    storeys_same_elevation_only: BoolProperty(
        name="Only if same height",
        description="Only merge same-named storeys when their elevation matches",
        default=True,
    )
    keep_temp: BoolProperty(
        name="Keep temp folder (debug)",
        default=True,
    )
    output_path: StringProperty(
        name="Output IFC", subtype="FILE_PATH", default="",
    )
    show_experimental: BoolProperty(
        name="Experimental: pre/post-merge operations",
        description="Show the experimental operations pipeline (recipes and "
                    "quantity take-offs applied before and after the merge)",
        default=False,
    )


# ─────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────
class MPP_OT_refresh_links(Operator):
    bl_idname = "mpp.refresh_links"
    bl_label = "Refresh"
    bl_description = "Reload linked IFC files from the Bonsai scene"

    def execute(self, context):
        props = context.scene.MPPProps
        prev = {i.filepath: i.selected for i in props.linked_files}
        props.linked_files.clear()
        for p in _get_linked_paths(context):
            it = props.linked_files.add()
            it.filepath = p
            it.selected = prev.get(p, True)
        self.report({"INFO"}, f"Found {len(props.linked_files)} linked file(s).")
        return {"FINISHED"}


class MPP_OT_links_all(Operator):
    bl_idname = "mpp.links_all"
    bl_label = "All"
    def execute(self, context):
        for i in context.scene.MPPProps.linked_files:
            i.selected = True
        return {"FINISHED"}


class MPP_OT_links_none(Operator):
    bl_idname = "mpp.links_none"
    bl_label = "None"
    def execute(self, context):
        for i in context.scene.MPPProps.linked_files:
            i.selected = False
        return {"FINISHED"}


class MPP_OT_add_manual(Operator):
    bl_idname = "mpp.add_manual"
    bl_label = "Add IFC File"
    bl_description = "Pick an IFC file to add to the merge list"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.ifc", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        props = context.scene.MPPProps
        p = (self.filepath or "").strip()
        if p and p.lower().endswith(".ifc"):
            if not any(m.filepath == p for m in props.manual_files):
                it = props.manual_files.add()
                it.filepath = p
                it.selected = True
                self.report({"INFO"}, f"Added: {os.path.basename(p)}")
            else:
                self.report({"WARNING"}, "Already in the list.")
        else:
            self.report({"WARNING"}, "Not an .ifc file.")
        return {"FINISHED"}


class MPP_OT_remove_manual(Operator):
    bl_idname = "mpp.remove_manual"
    bl_label = "Remove"
    bl_description = "Remove this file from the manual list"

    index: bpy.props.IntProperty()

    def execute(self, context):
        props = context.scene.MPPProps
        if 0 <= self.index < len(props.manual_files):
            props.manual_files.remove(self.index)
        return {"FINISHED"}


class MPP_OT_run(Operator):
    bl_idname = "mpp.run"
    bl_label = "Merge IFC Files"
    bl_description = "Run MergeProjectsPlus with the current settings"

    def execute(self, context):
        if engine is None:
            self.report({"ERROR"}, "Engine module not loaded.")
            return {"CANCELLED"}

        props = context.scene.MPPProps
        paths = _gather_merge_paths(context)

        if len(paths) < 2:
            self.report({"WARNING"}, "Select at least 2 files to merge.")
            return {"CANCELLED"}

        output = bpy.path.abspath(props.output_path).strip()
        if not output:
            self.report({"ERROR"}, "Set an output IFC path.")
            return {"CANCELLED"}
        out_dir = os.path.dirname(output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        pre_ops, post_ops = _collect_operations(context, paths)

        base_path, others = paths[0], paths[1:]
        self.report({"INFO"}, f"Merging {len(paths)} files…")
        try:
            engine.merge_files(
                base_path=base_path,
                other_paths=others,
                output_path=output,
                use_incremental=props.use_incremental,
                keep_temp=props.keep_temp,
                merge_sites=props.merge_sites_by_name,
                merge_buildings=props.merge_buildings_by_name,
                merge_storeys=props.merge_storeys_by_name,
                storeys_same_elevation=(props.merge_storeys_by_name
                                        and props.storeys_same_elevation_only),
                pre_ops=pre_ops,
                post_ops=post_ops,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Merge failed: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"✓ Saved to {output}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────
# Experimental: pre/post-merge operations pipeline
# Depends on Bonsai's Attribute PropertyGroup, so the classes are
# defined and registered deferred (extension load order is not
# guaranteed) and the whole section hides behind a checkbox.
# ─────────────────────────────────────────────────────────────
_exp_classes = []
_exp_error = ""


def _experimental_ready():
    return bool(_exp_classes)


def _op_to_dict(op):
    """Convert an MPP_Operation into the engine's plain-dict format."""
    if op.op_type == "RECIPE":
        if not op.recipe or op.recipe == "NONE":
            return None
        args = []
        for a in op.args:
            v = a.get_value()
            if a.data_type == "file" and a.metadata == "single_file":
                v = v[0] if v else ""
            args.append(v)
        return {"type": "recipe", "name": op.recipe, "arguments": args}
    return {"type": "takeoff",
            "queries": [s.query for s in op.searches if s.query],
            "rule": op.qto_rule,
            "fallback": op.qto_fallback}


def _collect_operations(context, paths):
    """Build (pre_ops dict per path, post_ops list) for engine.merge_files."""
    pre_ops, post_ops = {}, []
    props = context.scene.MPPProps
    if not props.show_experimental or not _experimental_ready():
        return pre_ops, post_ops
    scene = context.scene
    for op in getattr(scene, "MPPPreOps", []):
        d = _op_to_dict(op)
        if not d:
            continue
        if op.apply_to_all:
            targets = paths
        else:
            targets = [f.filepath for f in op.files
                       if f.selected and f.filepath in paths]
        for t in targets:
            pre_ops.setdefault(t, []).append(d)
    for op in getattr(scene, "MPPPostOps", []):
        d = _op_to_dict(op)
        if d:
            post_ops.append(d)
    return pre_ops, post_ops


_recipe_items_cache = None


def _recipe_enum_items(self, context):
    global _recipe_items_cache
    if _recipe_items_cache is None:
        items = []
        try:
            import ifcpatch
            recipes_dir = os.path.join(
                list(importlib.util.find_spec("ifcpatch").submodule_search_locations)[0],
                "recipes")
            for fn in sorted(os.listdir(recipes_dir)):
                name, ext = os.path.splitext(fn)
                if ext != ".py" or name.startswith("__"):
                    continue
                # Non-IFC / multi-file outputs don't fit an in-pipeline patch.
                if name in ("Ifc2Sql", "SplitByBuildingStorey"):
                    continue
                try:
                    docs = ifcpatch.extract_docs(name, "Patcher", "__init__",
                                                 ("src", "file", "logger", "args"))
                    desc = ((docs or {}).get("description") or "").split("\n")[0]
                except Exception:
                    desc = ""
                items.append((name, name, desc))
        except Exception as e:
            print(f"[MergeProjectsPlus] recipe listing failed: {e}")
        _recipe_items_cache = items or [("NONE", "No recipes found", "")]
    return _recipe_items_cache


_qto_rule_items_cache = {}


def _qto_rule_enum_items(self, context):
    schema = "IFC4"
    try:
        import bonsai.tool as tool
        f = tool.Ifc.get()
        if f is not None and f.schema == "IFC4X3":
            schema = "IFC4X3"
    except Exception:
        pass
    if schema not in _qto_rule_items_cache:
        items = []
        try:
            import ifc5d.qto
            for rid, rule in ifc5d.qto.rules.items():
                if rid.startswith("IFC4X3") == (schema == "IFC4X3"):
                    items.append((rid, rule.get("name", rid),
                                  rule.get("description", "")))
        except Exception as e:
            print(f"[MergeProjectsPlus] qto rules listing failed: {e}")
        _qto_rule_items_cache[schema] = items or [
            ("IFC4QtoBaseQuantities", "IFC4QtoBaseQuantities", "")]
    return _qto_rule_items_cache[schema]


def _update_recipe_args(self, context):
    """Rebuild the Attribute collection for the selected recipe — same
    mapping as Bonsai's bim.update_ifc_patch_arguments operator."""
    self.args.clear()
    if not self.recipe or self.recipe == "NONE":
        return
    try:
        import ifcpatch
        docs = ifcpatch.extract_docs(self.recipe, "Patcher", "__init__",
                                     ("src", "file", "logger", "args"))
    except Exception as e:
        print(f"[MergeProjectsPlus] extract_docs failed for {self.recipe}: {e}")
        return
    inputs = (docs or {}).get("inputs") or {}
    type_map = {"Literal": "enum", "file": "file", "str": "string",
                "float": "float", "int": "integer", "bool": "boolean"}
    for arg_name, arg_info in inputs.items():
        attr = self.args.add()
        data_type = arg_info.get("type", "str")
        is_filepath = ("filepath" in arg_info["name"]
                       or arg_info["name"].endswith("_dir")
                       or "filter_glob" in arg_info)
        if is_filepath:
            data_type = "file"
            attr.metadata = "single_file"
        if isinstance(data_type, list):
            if "file" in data_type or is_filepath:
                data_type = ["file"]
            data_type = next(dt for dt in data_type if dt != "NoneType")
        attr.data_type = type_map.get(data_type, "string")
        attr.name = arg_name.replace("_", " ").title()
        attr.description = arg_info.get("description", "") or ""
        if attr.data_type == "enum":
            attr.enum_items = json.dumps(arg_info.get("enum_items", []))
            try:
                attr.enum_value = arg_info.get("default", attr.get_value_default())
            except Exception:
                pass
            continue
        if attr.data_type == "file":
            attr.filepath_value.single_file = arg_info.get("default") or ""
            attr.filter_glob = arg_info.get("filter_glob", "*.ifc;*.ifczip;*.ifcxml")
            continue
        try:
            attr.set_value(arg_info.get("default", attr.get_value_default()))
        except Exception:
            pass


def _update_op_type(self, context):
    if self.op_type == "RECIPE" and not self.args:
        _update_recipe_args(self, context)


def _sync_op_files(op, context):
    paths = _gather_merge_paths(context)
    prev = {f.filepath: f.selected for f in op.files}
    op.files.clear()
    for p in paths:
        it = op.files.add()
        it.filepath = p
        it.selected = prev.get(p, True)


def _update_apply_to_all(self, context):
    if not self.apply_to_all:
        _sync_op_files(self, context)


_search_items_cache = []


def _saved_search_enum_items(self, context):
    global _search_items_cache
    items = []
    try:
        import bonsai.tool as tool
        f = tool.Ifc.get()
        if f is not None:
            for g in f.by_type("IfcGroup"):
                try:
                    data = json.loads(g.Description or "")
                except Exception:
                    continue
                if (isinstance(data, dict) and data.get("type") == "BBIM_Search"
                        and data.get("query")):
                    items.append((str(g.id()), g.Name or "Unnamed", data["query"]))
    except Exception:
        pass
    _search_items_cache = items or [
        ("NONE", "No saved searches found",
         "Save a search in Bonsai's Search panel first")]
    return _search_items_cache


def _get_ops_collection(context, section):
    return context.scene.MPPPreOps if section == "pre" else context.scene.MPPPostOps


def _register_experimental():
    """Define + register the classes that need Bonsai's Attribute PG."""
    global _exp_classes, _exp_error
    if _exp_classes:
        return True
    try:
        from bonsai.bim.prop import Attribute
        if not getattr(Attribute, "is_registered", False):
            raise RuntimeError("bonsai.bim.prop.Attribute not registered yet")
    except Exception as e:
        _exp_error = str(e)
        return False

    class MPP_SavedSearchRef(PropertyGroup):
        name: StringProperty()
        query: StringProperty()

    class MPP_OpFileItem(PropertyGroup):
        filepath: StringProperty()
        selected: BoolProperty(default=True)

    class MPP_Operation(PropertyGroup):
        op_type: EnumProperty(
            name="Operation",
            items=[
                ("RECIPE", "Recipe", "Run an ifcpatch recipe"),
                ("TAKEOFF", "Quantity Take-off",
                 "Recalculate IFC quantity sets (same as Bonsai's "
                 "Perform Quantity Take-off)"),
            ],
            update=_update_op_type,
        )
        recipe: EnumProperty(items=_recipe_enum_items, name="Recipe",
                             update=_update_recipe_args)
        args: CollectionProperty(type=Attribute)
        qto_rule: EnumProperty(items=_qto_rule_enum_items, name="Qto Rule")
        qto_fallback: BoolProperty(
            name="Fallback To Other Calculators",
            description="If currently selected calculator does not support "
                        "quantification of some class/quantity set, to try "
                        "other available calculators.",
            default=False,
        )
        searches: CollectionProperty(type=MPP_SavedSearchRef)
        apply_to_all: BoolProperty(name="Apply to all files", default=True,
                                   update=_update_apply_to_all)
        files: CollectionProperty(type=MPP_OpFileItem)

    class MPP_OT_op_add(Operator):
        bl_idname = "mpp.op_add"
        bl_label = "Add Operation"
        bl_description = "Add a pre/post-merge operation"
        section: StringProperty()

        def execute(self, context):
            op = _get_ops_collection(context, self.section).add()
            _update_recipe_args(op, context)
            return {"FINISHED"}

    class MPP_OT_op_remove(Operator):
        bl_idname = "mpp.op_remove"
        bl_label = "Remove Operation"
        section: StringProperty()
        index: bpy.props.IntProperty()

        def execute(self, context):
            coll = _get_ops_collection(context, self.section)
            if 0 <= self.index < len(coll):
                coll.remove(self.index)
            return {"FINISHED"}

    class MPP_OT_op_add_search(Operator):
        bl_idname = "mpp.op_add_search"
        bl_label = "Add Saved Search"
        bl_description = "Scope this take-off with a saved search from the loaded project"
        section: StringProperty()
        index: bpy.props.IntProperty()
        saved_search: EnumProperty(items=_saved_search_enum_items,
                                   name="Saved Search")

        def invoke(self, context, event):
            return context.window_manager.invoke_props_dialog(self)

        def draw(self, context):
            self.layout.prop(self, "saved_search", text="")

        def execute(self, context):
            if self.saved_search == "NONE":
                self.report({"WARNING"}, "No saved searches in the loaded project.")
                return {"CANCELLED"}
            coll = _get_ops_collection(context, self.section)
            if not (0 <= self.index < len(coll)):
                return {"CANCELLED"}
            name = query = ""
            for ident, label, q in _search_items_cache:
                if ident == self.saved_search:
                    name, query = label, q
                    break
            if not query:
                self.report({"WARNING"}, "Could not read the saved search query.")
                return {"CANCELLED"}
            item = coll[self.index].searches.add()
            item.name = name
            item.query = query
            return {"FINISHED"}

    class MPP_OT_op_remove_search(Operator):
        bl_idname = "mpp.op_remove_search"
        bl_label = "Remove Saved Search"
        section: StringProperty()
        index: bpy.props.IntProperty()
        search_index: bpy.props.IntProperty()

        def execute(self, context):
            coll = _get_ops_collection(context, self.section)
            if 0 <= self.index < len(coll):
                op = coll[self.index]
                if 0 <= self.search_index < len(op.searches):
                    op.searches.remove(self.search_index)
            return {"FINISHED"}

    class MPP_OT_op_sync_files(Operator):
        bl_idname = "mpp.op_sync_files"
        bl_label = "Refresh File List"
        bl_description = "Refresh this operation's file list from the merge selection"
        section: StringProperty()
        index: bpy.props.IntProperty()

        def execute(self, context):
            coll = _get_ops_collection(context, self.section)
            if 0 <= self.index < len(coll):
                _sync_op_files(coll[self.index], context)
            return {"FINISHED"}

    classes = [MPP_SavedSearchRef, MPP_OpFileItem, MPP_Operation,
               MPP_OT_op_add, MPP_OT_op_remove, MPP_OT_op_add_search,
               MPP_OT_op_remove_search, MPP_OT_op_sync_files]
    try:
        for c in classes:
            bpy.utils.register_class(c)
        bpy.types.Scene.MPPPreOps = CollectionProperty(type=MPP_Operation)
        bpy.types.Scene.MPPPostOps = CollectionProperty(type=MPP_Operation)
    except Exception as e:
        _exp_error = str(e)
        for c in reversed(classes):
            try:
                bpy.utils.unregister_class(c)
            except Exception:
                pass
        return False
    _exp_classes = classes
    print("[MergeProjectsPlus] experimental operations registered")
    return True


def _register_experimental_deferred():
    if _register_experimental():
        return
    state = {"tries": 0}

    def _retry():
        state["tries"] += 1
        if _register_experimental() or state["tries"] >= 20:
            return None
        return 0.5

    try:
        bpy.app.timers.register(_retry, first_interval=0.5)
    except Exception:
        pass


def _unregister_experimental():
    global _exp_classes
    if not _exp_classes:
        return
    for attr in ("MPPPreOps", "MPPPostOps"):
        try:
            delattr(bpy.types.Scene, attr)
        except Exception:
            pass
    for c in reversed(_exp_classes):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
    _exp_classes = []


def _draw_operation(box, context, op, idx, section):
    b = box.box()
    row = b.row(align=True)
    row.prop(op, "op_type", text="")
    rm = row.operator("mpp.op_remove", text="", icon="X")
    rm.section = section
    rm.index = idx

    if op.op_type == "RECIPE":
        drew = False
        try:
            from bonsai.bim.helper import draw_attributes, prop_with_search
            prop_with_search(b.row(), op, "recipe")
            if op.args:
                draw_attributes(op.args, b)
            drew = True
        except Exception as e:
            print(f"[MergeProjectsPlus] recipe draw fallback: {e}")
        if not drew:
            b.prop(op, "recipe")
    else:
        b.prop(op, "qto_rule")
        b.prop(op, "qto_fallback")
        add = b.operator("mpp.op_add_search", icon="ADD")
        add.section = section
        add.index = idx
        if not op.searches:
            b.label(text="No searches — all elements will be quantified.", icon="INFO")
        for sidx, s in enumerate(op.searches):
            r = b.row(align=True)
            r.label(text=s.name, icon="VIEWZOOM")
            d = r.operator("mpp.op_remove_search", text="", icon="X")
            d.section = section
            d.index = idx
            d.search_index = sidx

    if section == "pre":
        b.prop(op, "apply_to_all")
        if not op.apply_to_all:
            r = b.row(align=True)
            r.label(text="Apply to:")
            sy = r.operator("mpp.op_sync_files", text="", icon="FILE_REFRESH")
            sy.section = section
            sy.index = idx
            if not op.files:
                b.label(text="Press refresh to load the merge file list.", icon="INFO")
            col = b.column(align=True)
            for fitem in op.files:
                fr = col.row(align=True)
                fr.prop(fitem, "selected", text="")
                fr.label(text=os.path.basename(fitem.filepath), icon="FILE")


def _draw_experimental(layout, context):
    if not _experimental_ready():
        bx = layout.box()
        bx.label(text="Needs Bonsai loaded — restart Blender.", icon="ERROR")
        if _exp_error:
            bx.label(text=_exp_error[:60])
        return
    scene = context.scene
    for label, section, coll in (
            ("Pre-merge operations", "pre", scene.MPPPreOps),
            ("Post-merge operations", "post", scene.MPPPostOps)):
        box = layout.box()
        row = box.row(align=True)
        row.label(text=label, icon="MODIFIER")
        add = row.operator("mpp.op_add", text="", icon="ADD")
        add.section = section
        for idx, op in enumerate(coll):
            _draw_operation(box, context, op, idx, section)


# ─────────────────────────────────────────────────────────────
# Shared draw
# ─────────────────────────────────────────────────────────────
def _draw_ui(layout, context):
    props = context.scene.MPPProps

    # active project
    active = _get_active_ifc_path(context)
    box = layout.box()
    box.label(text="Active Project:", icon="FILE_BLANK")
    box.label(text=os.path.basename(active) if active else "(none)",
              icon="CHECKMARK" if active else "INFO")
    layout.prop(props, "include_active")
    layout.separator()

    # linked files
    layout.label(text="Linked IFC Files:", icon="LINKED")
    row = layout.row(align=True)
    row.operator("mpp.refresh_links", icon="FILE_REFRESH")
    row.operator("mpp.links_all")
    row.operator("mpp.links_none")
    if not props.linked_files:
        layout.box().label(text="None — press Refresh.", icon="INFO")
    else:
        b = layout.box().column(align=True)
        for i in props.linked_files:
            r = b.row(align=True)
            r.prop(i, "selected", text="")
            r.label(text=os.path.basename(i.filepath), icon="FILE")
    layout.separator()

    # manual paths
    layout.prop(props, "use_manual_paths")
    if props.use_manual_paths:
        b = layout.box()
        b.operator("mpp.add_manual", icon="ADD")
        if props.manual_files:
            col = b.column(align=True)
            for idx, m in enumerate(props.manual_files):
                r = col.row(align=True)
                r.prop(m, "selected", text="")
                r.label(text=os.path.basename(m.filepath), icon="FILE")
                op = r.operator("mpp.remove_manual", text="", icon="X")
                op.index = idx
    layout.separator()

    # options
    layout.label(text="Options:", icon="SETTINGS")
    layout.prop(props, "use_incremental")
    if props.use_incremental:
        layout.prop(props, "keep_temp")
    layout.prop(props, "merge_sites_by_name")
    layout.prop(props, "merge_buildings_by_name")
    layout.prop(props, "merge_storeys_by_name")
    if props.merge_storeys_by_name:
        r = layout.row()
        r.separator(factor=2.0)
        r.prop(props, "storeys_same_elevation_only")
    layout.separator()

    # experimental pre/post-merge operations
    layout.prop(props, "show_experimental")
    if props.show_experimental:
        _draw_experimental(layout, context)
    layout.separator()

    # output + run
    layout.label(text="Output File:", icon="EXPORT")
    layout.prop(props, "output_path", text="")
    layout.separator()

    n = sum(1 for i in props.linked_files if i.selected)
    if props.use_manual_paths:
        n += sum(1 for m in props.manual_files if m.selected)
    if props.include_active and active:
        n += 1
    row = layout.row()
    row.scale_y = 1.6
    row.enabled = engine is not None and n >= 2 and bool(props.output_path)
    row.operator("mpp.run", text=f"Merge  {n}  Files", icon="IMPORT")
    if n < 2:
        layout.label(text="Select at least 2 files.", icon="ERROR")


# ─────────────────────────────────────────────────────────────
# Panel (own panel under Scene Properties)
# ─────────────────────────────────────────────────────────────
class MPP_PT_panel(Panel):
    bl_label = "Merge Project Plus"
    bl_idname = "MPP_PT_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    # No bl_context on purpose: placement comes from the parent panel, and
    # declaring "scene" would make Bonsai's load_post scene-panel hijack
    # pick this panel up, crash its parents-first sort (our parent is a
    # Bonsai panel it excludes), and abort the hiding of default Blender
    # scene panels — which then randomly reappear.
    bl_parent_id = "BIM_PT_tab_quality_control"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, _context):
        return _bonsai_available()

    def draw(self, context):
        if not _bonsai_available():
            self.layout.label(text="Bonsai not found", icon="ERROR")
            return
        _draw_ui(self.layout, context)


# ─────────────────────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────────────────────
_classes = [
    MPP_LinkedItem, MPP_ManualItem, MPP_Props,
    MPP_OT_refresh_links, MPP_OT_links_all, MPP_OT_links_none,
    MPP_OT_add_manual, MPP_OT_remove_manual, MPP_OT_run,
    MPP_PT_panel,
]

def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.MPPProps = PointerProperty(type=MPP_Props)
    _register_experimental_deferred()

def unregister():
    _unregister_experimental()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    try:
        del bpy.types.Scene.MPPProps
    except AttributeError:
        pass

if __name__ == "__main__":
    register()