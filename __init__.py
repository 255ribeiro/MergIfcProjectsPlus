# __init__.py — BIM: Merge Project Plus
bl_info = {
    "name": "BIM: Merge Project Plus",
    "author": "Custom",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "location": "Scene Properties → Quality and Control → IFC Patch area",
    "description": "Merge linked + manually-added IFC files into one output.",
    "category": "BIM",
}

import os
import importlib.util

import bpy
from bpy.props import (
    BoolProperty, StringProperty, CollectionProperty, PointerProperty,
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
    keep_temp: BoolProperty(
        name="Keep temp folder (debug)",
        default=True,
    )
    output_path: StringProperty(
        name="Output IFC", subtype="FILE_PATH", default="",
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

        # Gather all sources
        paths = [i.filepath for i in props.linked_files if i.selected and i.filepath]
        if props.use_manual_paths:
            paths += [m.filepath for m in props.manual_files if m.selected and m.filepath]

        active = _get_active_ifc_path(context)
        if props.include_active and active and active not in paths:
            paths.insert(0, active)

        # de-dup, preserve order
        seen, ordered = set(), []
        for p in paths:
            if p not in seen:
                seen.add(p); ordered.append(p)
        paths = ordered

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

        base_path, others = paths[0], paths[1:]
        self.report({"INFO"}, f"Merging {len(paths)} files…")
        try:
            engine.merge_files(
                base_path=base_path,
                other_paths=others,
                output_path=output,
                use_incremental=props.use_incremental,
                keep_temp=props.keep_temp,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Merge failed: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"✓ Saved to {output}")
        return {"FINISHED"}


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
    bl_context = "scene"
    bl_parent_id = "BIM_PT_patch"
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

def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    try:
        del bpy.types.Scene.MPPProps
    except AttributeError:
        pass

if __name__ == "__main__":
    register()