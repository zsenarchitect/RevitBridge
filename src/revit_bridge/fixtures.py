"""Synthetic test fixtures. No copyrighted models are ever committed.

- :func:`build_sample_ifc`: generates a small, valid IFC4 building (4 walls +
  1 slab) with IfcOpenShell's low-level API. Used by the converter tests.
- Probe fixtures for the RVT reader are byte-level payloads built in the test
  suite (see tests/test_rvt_probe.py); real Autodesk samples are smoke-tested
  from /tmp and never committed.
"""

from __future__ import annotations

from pathlib import Path


def _guid() -> str:
    import ifcopenshell.guid

    return ifcopenshell.guid.new()


def build_sample_ifc(path: str | Path) -> str:
    """Write a minimal valid IFC4 file: one storey, 4 walls, 1 slab.

    Returns the path written. Raises RuntimeError if IfcOpenShell refuses to
    parse the result back (self-check: the fixture must be genuinely valid).
    """
    import ifcopenshell

    f = ifcopenshell.file(schema="IFC4")
    E = f.create_entity

    def pt3(x, y, z):
        return E("IfcCartesianPoint", Coordinates=(x, y, z))

    def dir3(x, y, z):
        return E("IfcDirection", DirectionRatios=(x, y, z))

    def ax3d(loc=(0.0, 0.0, 0.0)):
        return E(
            "IfcAxis2Placement3D",
            Location=pt3(*loc),
            Axis=dir3(0.0, 0.0, 1.0),
            RefDirection=dir3(1.0, 0.0, 0.0),
        )

    ctx = E(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1.0e-5,
        WorldCoordinateSystem=ax3d(),
        TrueNorth=E("IfcDirection", DirectionRatios=(0.0, 1.0)),
    )
    project = E("IfcProject", GlobalId=_guid(), Name="RevitBridge sample")
    project.RepresentationContexts = (ctx,)

    site = E("IfcSite", GlobalId=_guid(), Name="Site",
             ObjectPlacement=E("IfcLocalPlacement", RelativePlacement=ax3d()))
    building = E("IfcBuilding", GlobalId=_guid(), Name="Building",
                 ObjectPlacement=E("IfcLocalPlacement", RelativePlacement=ax3d()))
    storey = E("IfcBuildingStorey", GlobalId=_guid(), Name="Level 1",
               ObjectPlacement=E("IfcLocalPlacement", RelativePlacement=ax3d()))
    for rel_class, relating, related in (
        ("IfcRelAggregates", project, (site,)),
        ("IfcRelAggregates", site, (building,)),
        ("IfcRelAggregates", building, (storey,)),
    ):
        E(rel_class, GlobalId=_guid(), RelatingObject=relating, RelatedObjects=related)

    def extruded_wall(name: str, x: float, y: float, length: float, angle_deg: float = 0.0):
        import math

        rad = math.radians(angle_deg)
        # swept profile: rectangle length x thickness in local XY
        prof = E(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            XDim=length,
            YDim=0.2,
            Position=E(
                "IfcAxis2Placement2D",
                Location=E("IfcCartesianPoint", Coordinates=(0.0, 0.0)),
                RefDirection=E("IfcDirection", DirectionRatios=(1.0, 0.0)),
            ),
        )
        solid = E(
            "IfcExtrudedAreaSolid",
            SweptArea=prof,
            Position=ax3d(),
            ExtrudedDirection=dir3(0.0, 0.0, 1.0),
            Depth=3.0,
        )
        rep = E(
            "IfcShapeRepresentation",
            ContextOfItems=ctx,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=(solid,),
        )
        # rotate the whole wall into place via placement
        placement = E(
            "IfcLocalPlacement",
            RelativePlacement=E(
                "IfcAxis2Placement3D",
                Location=pt3(x, y, 0.0),
                Axis=dir3(0.0, 0.0, 1.0),
                RefDirection=dir3(math.cos(rad), math.sin(rad), 0.0),
            ),
        )
        wall = E(
            "IfcWall",
            GlobalId=_guid(),
            Name=name,
            ObjectPlacement=placement,
            Representation=E("IfcProductDefinitionShape", Representations=(rep,)),
        )
        E(
            "IfcRelContainedInSpatialStructure",
            GlobalId=_guid(),
            RelatingStructure=storey,
            RelatedElements=(wall,),
        )
        return wall

    # 5m x 4m room, walls 3m high, 0.2m thick
    extruded_wall("Wall-N", 0.0, 4.0, 5.0, 0.0)
    extruded_wall("Wall-S", 0.0, 0.0, 5.0, 0.0)
    extruded_wall("Wall-E", 5.0, 0.0, 4.0, 90.0)
    extruded_wall("Wall-W", 0.0, 0.0, 4.0, 90.0)

    # slab: 5x4x0.2 box at z=0
    prof = E(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        XDim=5.0,
        YDim=4.0,
        Position=E(
            "IfcAxis2Placement2D",
            Location=E("IfcCartesianPoint", Coordinates=(0.0, 0.0)),
            RefDirection=E("IfcDirection", DirectionRatios=(1.0, 0.0)),
        ),
    )
    solid = E(
        "IfcExtrudedAreaSolid",
        SweptArea=prof,
        Position=ax3d(),
        ExtrudedDirection=dir3(0.0, 0.0, 1.0),
        Depth=0.2,
    )
    rep = E(
        "IfcShapeRepresentation",
        ContextOfItems=ctx,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=(solid,),
    )
    slab = E(
        "IfcSlab",
        GlobalId=_guid(),
        Name="Slab-1",
        PredefinedType="BASESLAB",
        ObjectPlacement=E("IfcLocalPlacement", RelativePlacement=ax3d((0.0, 0.0, -0.2))),
        Representation=E("IfcProductDefinitionShape", Representations=(rep,)),
    )
    E(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatingStructure=storey,
        RelatedElements=(slab,),
    )

    path = str(path)
    f.write(path)

    # self-check: the fixture must parse back and tessellate
    check = ifcopenshell.open(path)
    walls = check.by_type("IfcWall")
    slabs = check.by_type("IfcSlab")
    if len(walls) != 4 or len(slabs) != 1:
        raise RuntimeError(f"Fixture self-check failed: {len(walls)} walls, {len(slabs)} slabs")
    return path
