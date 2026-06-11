# __init__.py — BIM: MergeProjectsPlus Recipe Installer
# Tiny addon whose only job is to copy the MergeProjectsPlus.py ifcpatch
# recipe into Bonsai's bundled ifcpatch/recipes folder, so it shows up in
# the native IFC Patch recipe dropdown with auto-generated UI.
# Re-enable the addon (or press "Reinstall recipe") after a Bonsai update.

bl_info = {
    "name": "BIM: MergeProjectsPlus Recipe Installer",
    "author": "Fernando Ferraz Ribeiro",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Scene Properties → Quality and Control → IFC Patch → recipe MergeProjectsPlus",
    "description": "Installs the MergeProjectsPlus ifcpatch recipe into Bonsai",
    "category": "BIM",
}

import hashlib
import importlib.util
import os
import shutil

import bpy
from bpy.types import AddonPreferences, Operator

RECIPE_NAME = "MergeProjectsPlus.py"

# Last install attempt result, shown in the addon preferences.
_status = "Not installed yet."


def _find_recipe_source():
    """The recipe file shipped with this addon (next to __init__.py when
    packaged; one level up in the development repo layout)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, RECIPE_NAME),
                      os.path.join(os.path.dirname(here), RECIPE_NAME)):
        if os.path.isfile(candidate):
            return candidate
    return None


def _find_recipes_dir():
    """Bonsai's bundled ifcpatch/recipes directory, or None if not found."""
    try:
        spec = importlib.util.find_spec("ifcpatch")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        return None
    recipes = os.path.join(list(spec.submodule_search_locations)[0], "recipes")
    return recipes if os.path.isdir(recipes) else None


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def install_recipe():
    """Copy the recipe into ifcpatch/recipes if absent or outdated.
    Returns (ok, message)."""
    global _status
    src = _find_recipe_source()
    if src is None:
        _status = f"{RECIPE_NAME} not found inside the addon."
        return False, _status
    recipes_dir = _find_recipes_dir()
    if recipes_dir is None:
        _status = "ifcpatch not found — is the Bonsai extension installed and enabled?"
        return False, _status
    dst = os.path.join(recipes_dir, RECIPE_NAME)
    try:
        if os.path.isfile(dst) and _digest(dst) == _digest(src):
            _status = f"Already installed: {dst}"
            return True, _status
        shutil.copyfile(src, dst)
        _status = f"Installed: {dst}"
        return True, _status
    except Exception as e:
        _status = f"Install failed: {e}"
        return False, _status


def remove_recipe():
    global _status
    recipes_dir = _find_recipes_dir()
    if recipes_dir is None:
        return
    dst = os.path.join(recipes_dir, RECIPE_NAME)
    try:
        if os.path.isfile(dst):
            os.remove(dst)
            _status = "Recipe removed."
    except Exception as e:
        _status = f"Remove failed: {e}"


class MPPR_OT_install(Operator):
    bl_idname = "mppr.install_recipe"
    bl_label = "Install / Reinstall Recipe"
    bl_description = "Copy the MergeProjectsPlus recipe into Bonsai's ifcpatch recipes folder"

    def execute(self, context):
        ok, msg = install_recipe()
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MPPR_OT_remove(Operator):
    bl_idname = "mppr.remove_recipe"
    bl_label = "Remove Recipe"
    bl_description = "Delete the MergeProjectsPlus recipe from Bonsai's ifcpatch recipes folder"

    def execute(self, context):
        remove_recipe()
        self.report({"INFO"}, _status)
        return {"FINISHED"}


class MPPR_preferences(AddonPreferences):
    bl_idname = __package__ or __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text=_status, icon="INFO")
        row = layout.row()
        row.operator("mppr.install_recipe", icon="IMPORT")
        row.operator("mppr.remove_recipe", icon="X")
        layout.label(text="After a Bonsai update, press Install / Reinstall Recipe again.")


_classes = [MPPR_OT_install, MPPR_OT_remove, MPPR_preferences]


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    ok, msg = install_recipe()
    print(f"[MergeProjectsPlus Recipe Installer] {msg}")


def unregister():
    remove_recipe()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
