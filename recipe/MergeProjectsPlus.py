# MergeProjectsPlus — ifcpatch recipe
# Merges another IFC model into the current one (reusing the bundled
# MergeProjects recipe for unit conversion and geolocation alignment),
# then optionally combines same-named sites / buildings / storeys so the
# result has a single spatial hierarchy instead of duplicates.
#
# Install: copy this file into <site-packages>/ifcpatch/recipes/ — it then
# appears in Bonsai under Scene Properties → Quality and Control → IFC Patch.

import logging
from typing import Optional

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.unit
from ifcpatch.recipes.MergeProjects import Patcher as MergeProjects

log = logging.getLogger(__name__)


def get_aggregate_parent(f, elem):
    for rel in f.by_type("IfcRelAggregates"):
        if elem in (rel.RelatedObjects or ()):
            return rel.RelatingObject
    return None


def merge_duplicate_into(f, keeper, dup):
    # Detach dup from its parent aggregation (keeper already hangs there;
    # Decomposes is SET [0:1], so dup may not simply be repointed).
    for rel in f.by_type("IfcRelAggregates"):
        if dup in (rel.RelatedObjects or ()):
            remaining = [o for o in rel.RelatedObjects if o != dup]
            if remaining:
                rel.RelatedObjects = remaining
            else:
                try:
                    f.remove(rel)
                except Exception:
                    pass
    # Everything else referencing dup (children aggregations, contained
    # elements, psets, ...) now points at keeper instead.
    for inv in f.get_inverse(dup):
        try:
            ifcopenshell.util.element.replace_attribute(inv, dup, keeper)
        except Exception:
            pass
    # Keep dup's placement if children still chain through it, so geometry
    # stays where it was; drop it only when nothing references it anymore.
    placement = getattr(dup, "ObjectPlacement", None)
    try:
        f.remove(dup)
    except Exception:
        pass
    if placement is not None:
        try:
            if not f.get_inverse(placement):
                f.remove(placement)
        except Exception:
            pass


def merge_spatial_by_name(f, ifc_class, match_elevation=False, logger=log):
    """Merge same-named ifc_class elements that share the same parent.
    With match_elevation, storeys also need (near-)equal Elevation."""
    groups = {}
    for e in f.by_type(ifc_class):
        name = (e.Name or "").strip()
        if not name:
            continue  # never merge unnamed elements
        parent = get_aggregate_parent(f, e)
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
                merge_duplicate_into(f, keeper, dup)
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


class Patcher(MergeProjects):
    def __init__(
        self,
        file: ifcopenshell.file,
        logger: Optional[logging.Logger] = None,
        filepath: str = "",
        merge_sites: bool = False,
        merge_buildings: bool = False,
        merge_storeys: bool = False,
        storeys_same_elevation: bool = True,
        align_geolocation: bool = False,
    ):
        """Merge another IFC model into this one, combining same-named sites, buildings and storeys

        Builds on the MergeProjects recipe (same automatic length unit
        conversion), then optionally combines spatial elements that share
        the same name, so the merged model gets a single spatial hierarchy
        instead of duplicated sites, buildings and storeys.

        Elements are only combined when they sit under the same parent:
        same-named buildings merge only within the same site, same-named
        storeys only within the same building. Unnamed elements are never
        combined. Run the recipe again to merge additional models.

        :param filepath: The other IFC model to merge into the current one.
        :filter_glob filepath: *.ifc;*.ifczip;*.ifcxml
        :param merge_sites: Combine same-named IfcSite elements into one.
        :param merge_buildings: Combine same-named IfcBuilding elements into one.
        :param merge_storeys: Combine same-named IfcBuildingStorey elements into one.
        :param storeys_same_elevation: Only combine same-named storeys when
            their Elevation also matches. Has no effect unless merge_storeys
            is enabled.
        :param align_geolocation: Use MergeProjects' map-coordinate alignment
            (SetFalseOrigin) when the models' georeferencing differs. Leave
            disabled when all models share the same coordinate system: the
            alignment mixes up project and map units (e.g. millimetres vs
            metres) and can shift or scale the merged model.

        Example:

        .. code:: python

            ifcpatch.execute({"input": "input.ifc", "file": model, "recipe": "MergeProjectsPlus",
                "arguments": ["/path/to/model2.ifc", True, True, True, True]})
        """
        super().__init__(file, logger, filepaths=[filepath] if filepath else [])
        self.merge_sites = merge_sites
        self.merge_buildings = merge_buildings
        self.merge_storeys = merge_storeys
        self.storeys_same_elevation = storeys_same_elevation
        self.align_geolocation = align_geolocation

    def merge(self, other: ifcopenshell.file) -> None:
        if self.align_geolocation:
            return super().merge(other)
        # Same as MergeProjects.merge but without the SetFalseOrigin
        # geolocation alignment, which corrupts geometry when the models'
        # georeferencing differs (it passes project-unit coordinates where
        # map units are expected — a 1000x error for millimetre models).
        if (main_unit := self.get_unit_name(self.file)) != self.get_unit_name(other):
            other = ifcopenshell.util.unit.convert_file_length_units(other, main_unit)

        self.existing_contexts = self.file.by_type("IfcGeometricRepresentationContext")
        self.added_contexts = set()

        original_project = self.file.by_type("IfcProject")[0]
        merged_project = self.file.add(other.by_type("IfcProject")[0])

        for element in other.by_type("IfcGeometricRepresentationContext"):
            self.added_contexts.add(self.file.add(element))

        for element in other:
            self.file.add(element)

        for inverse in self.file.get_inverse(merged_project):
            ifcopenshell.util.element.replace_attribute(inverse, merged_project, original_project)
        self.file.remove(merged_project)

        self.reuse_existing_contexts()

    def patch(self):
        super().patch()
        apply_spatial_merges(
            self.file,
            merge_sites=self.merge_sites,
            merge_buildings=self.merge_buildings,
            merge_storeys=self.merge_storeys,
            storeys_same_elevation=self.storeys_same_elevation,
            logger=self.logger or log,
        )
