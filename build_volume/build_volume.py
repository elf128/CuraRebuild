#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# build_volume/build_volume.py
#
#   Created on:    Mar 27, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
# Task panels for all CuraRebuild commands.
# Built programmatically from the settings schema — no .ui files needed.
#
# FreeCAD task panels are objects with:
#   self.form  — a QWidget shown in the task panel area
#   accept()   — called when the user clicks OK
#   reject()   — called when the user clicks Cancel
#   getStandardButtons() — bitmask of buttons to show
#
#   Copyright (c) 2026                                                    
#                                                                         
#   This program is free software; you can redistribute it and/or modify  
#   it under the terms of the GNU Lesser General Public License (LGPL)    
#   as published by the Free Software Foundation; either version 2 of     
#   the License, or (at your option) any later version.                   
#   for detail see the LICENCE text file.                                 
#                                                                         
#   This program is distributed in the hope that it will be useful,       
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         
#   GNU Library General Public License for more details.                  
#                                                                         
#   You should have received a copy of the GNU Library General Public     
#   License along with this program; if not, write to the Free Software   
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  
#   USA                                                                   

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import FreeCAD
from FreeCAD import Base, Console

if TYPE_CHECKING:
    from settings.stack import SettingsStack, SettingsRegistry

_GRP_VOLUME    = "Build Volume"
_GRP_STACK     = "Settings Stack"
_GRP_BODIES    = "Assigned Bodies"

MESH_TYPES = [
    "normal",
    "infill_mesh",
    "cutting_mesh",
    "support_mesh",
    "anti_overhang_mesh",
]


class BodyConfig:
    """Per-body slicer configuration stored in BuildVolume.BodyConfigJson."""

    __slots__ = ( "mesh_type", "extruder_nr", "override_layer_id" )

    def __init__(
        self,
        mesh_type:         str = "normal",
        extruder_nr:       int = 0,
        override_layer_id: str = "",
    ):
        self.mesh_type         = mesh_type
        self.extruder_nr       = extruder_nr
        self.override_layer_id = override_layer_id

    def to_dict( self ) -> dict:
        return {
            "mesh_type":         self.mesh_type,
            "extruder_nr":       self.extruder_nr,
            "override_layer_id": self.override_layer_id,
        }

    @classmethod
    def from_dict( cls, d: dict ) -> "BodyConfig":
        return cls(
            mesh_type         = d.get( "mesh_type",         "normal" ),
            extruder_nr       = int( d.get( "extruder_nr",  0        ) ),
            override_layer_id = d.get( "override_layer_id", ""       ),
        )


def get_body_configs( fp: "FreeCAD.DocumentObject" ) -> dict[str, BodyConfig]:
    """Return {body.Name: BodyConfig} from BuildVolume.BodyConfigJson."""
    import json
    try:
        raw = getattr( fp, "BodyConfigJson", "{}" ) or "{}"
        data = json.loads( raw )
        return { k: BodyConfig.from_dict( v ) for k, v in data.items() }
    except Exception:
        return {}


def set_body_configs(
    fp:      "FreeCAD.DocumentObject",
    configs: dict[str, BodyConfig],
) -> None:
    """Write {body.Name: BodyConfig} to BuildVolume.BodyConfigJson."""
    import json
    fp.BodyConfigJson = json.dumps(
        { k: v.to_dict() for k, v in configs.items() },
        ensure_ascii=False,
    )


def get_body_config( fp, body_name: str ) -> BodyConfig:
    """Return BodyConfig for a single body, defaulting if not set."""
    return get_body_configs( fp ).get( body_name, BodyConfig() )


def set_body_config( fp, body_name: str, cfg: BodyConfig ) -> None:
    """Update BodyConfig for a single body."""
    configs = get_body_configs( fp )
    configs[ body_name ] = cfg
    set_body_configs( fp, configs )
_GRP_TRANSFORM = "Transform"


class BuildVolume:
    """
    FreeCAD FeaturePython proxy for the Build Volume object.

    Properties:
        Width, Depth, Height  — build envelope dimensions (mm)
        MachineLayer          — App::PropertyLink to the MachineLayer FP object
        UserLayers            — App::PropertyLinkList of UserLayer FP objects
        AssignedBodies        — App::PropertyLinkList of assigned FreeCAD bodies
    """

    def __init__( self, fp: FreeCAD.DocumentObject, name: str = "BuildVolume" ):
        self.Type = "BuildVolume"
        fp.Proxy  = self
        self._init_properties( fp )

    def _init_properties( self, fp: FreeCAD.DocumentObject ) -> None:
        existing = set( fp.PropertiesList )

        if "Width" not in existing:
            fp.addProperty(
                "App::PropertyFloat", "Width", _GRP_VOLUME,
                "Build envelope X dimension (mm)"
            ).Width = 220.0

        if "Depth" not in existing:
            fp.addProperty(
                "App::PropertyFloat", "Depth", _GRP_VOLUME,
                "Build envelope Y dimension (mm)"
            ).Depth = 220.0

        if "Height" not in existing:
            fp.addProperty(
                "App::PropertyFloat", "Height", _GRP_VOLUME,
                "Build envelope Z dimension (mm)"
            ).Height = 220.0   # sensible default; overridden from machine layer



        # Native FreeCAD links — show in tree, resolve automatically
        if "MachineLayer" not in existing:
            fp.addProperty(
                "App::PropertyLink", "MachineLayer", _GRP_STACK,
                "Linked MachineLayer settings object"
            )

        if "UserLayers" not in existing:
            fp.addProperty(
                "App::PropertyLinkList", "UserLayers", _GRP_STACK,
                "Ordered list of UserLayer settings objects (lowest priority first)"
            )

        if "AssignedBodies" not in existing:
            fp.addProperty(
                "App::PropertyLinkList", "AssignedBodies", _GRP_BODIES,
                "FreeCAD bodies assigned to this build volume"
            )

        if "BodyConfigJson" not in existing:
            fp.addProperty(
                "App::PropertyString", "BodyConfigJson", _GRP_BODIES,
                "Per-body mesh type, extruder, and override layer (JSON)"
            ).BodyConfigJson = "{}"
        fp.setEditorMode( "BodyConfigJson", 2 )   # hidden

        # Placement — makes the object movable in the viewport
        if "Placement" not in existing:
            fp.addProperty(
                "App::PropertyPlacement", "Placement", _GRP_VOLUME,
                "Position and orientation of the build volume in world space"
            )

        # Cura-to-printer coordinate offset (mm)
        # CuraEngine places objects with (0,0) = bed front-left.
        # If your printer's X range is [-15, 205], set OffsetX = -15
        # so Cura X=0 maps to printer X=-15.
        if "PrinterOffsetX" not in existing:
            fp.addProperty(
                "App::PropertyFloat", "PrinterOffsetX", _GRP_VOLUME,
                "X coordinate of the Cura object space origin in G-code space. "
                "Typically machine_width / 2 for center-origin machines. "
                "The build volume box and G-code display are shifted by this amount."
            ).PrinterOffsetX = 0.0

        if "PrinterOffsetY" not in existing:
            fp.addProperty(
                "App::PropertyFloat", "PrinterOffsetY", _GRP_VOLUME,
                "Y coordinate of the Cura object space origin in G-code space. "
                "Typically machine_depth / 2 for center-origin machines."
            ).PrinterOffsetY = 0.0

        # Auto-slice settings
        _GRP_SLICE = "Slicing"
        if "GCodeOutputFile" not in existing:
            fp.addProperty(
                "App::PropertyFile", "GCodeOutputFile", _GRP_SLICE,
                "Path to write the sliced G-code file"
            ).GCodeOutputFile = ""

        if "EnableAutoSlice" not in existing:
            fp.addProperty(
                "App::PropertyBool", "EnableAutoSlice", _GRP_SLICE,
                "Automatically re-slice when settings or bodies change"
            ).EnableAutoSlice = False

        # G-code viewer properties
        _GRP_VIZ = "G-Code Viewer"
        if "ShowGCode" not in existing:
            fp.addProperty(
                "App::PropertyBool", "ShowGCode", _GRP_VIZ,
                "Show G-code toolpaths in the 3D viewport"
            ).ShowGCode = True

        if "GCodeLayerFrom" not in existing:
            fp.addProperty(
                "App::PropertyInteger", "GCodeLayerFrom", _GRP_VIZ,
                "First layer to display (0 = first)"
            ).GCodeLayerFrom = 0

        if "GCodeLayerTo" not in existing:
            fp.addProperty(
                "App::PropertyInteger", "GCodeLayerTo", _GRP_VIZ,
                "Last layer to display (-1 = all)"
            ).GCodeLayerTo = -1

        if "GCodeShowTravel" not in existing:
            fp.addProperty(
                "App::PropertyBool", "GCodeShowTravel", _GRP_VIZ,
                "Show travel moves"
            ).GCodeShowTravel = False

        if "GCodeColourMode" not in existing:
            fp.addProperty(
                "App::PropertyEnumeration", "GCodeColourMode", _GRP_VIZ,
                "Toolpath colour mode"
            )
            fp.GCodeColourMode = ["Feature", "Speed", "Extruder"]
            fp.GCodeColourMode = "Feature"

        for feat in ( "WallOuter", "WallInner", "Fill", "Skin",
                      "Support", "Skirt", "PrimeTower" ):
            prop = f"GCodeShow{feat}"
            if prop not in existing:
                fp.addProperty(
                    "App::PropertyBool", prop, _GRP_VIZ,
                    f"Show {feat} moves"
                )
                setattr( fp, prop, True )

    # ------------------------------------------------------------------
    # FreeCAD object protocol

    def execute( self, fp: FreeCAD.DocumentObject ) -> None:
        """Called by FreeCAD on recompute — after all properties are set."""
        # Update geometry now that all properties are available
        if FreeCAD.GuiUp:
            vp = getattr( fp, "ViewObject", None )
            if vp and getattr( vp, "Proxy", None ):
                try:
                    vp.Proxy.update_geometry( fp )
                    # Cycle display mode to force FreeCAD to re-read the scene.
                    # This is the correct place — execute() fires after recompute
                    # when all properties are guaranteed to be set.
                    current = vp.DisplayMode
                    vp.DisplayMode = "Wireframe" if current != "Wireframe" else "Flat Lines"
                    vp.DisplayMode = current
                except Exception:
                    pass

        if getattr( fp, "EnableAutoSlice", False ) and                 getattr( fp, "GCodeOutputFile", "" ):
            self._run_slice( fp )

    def onChanged( self, fp: FreeCAD.DocumentObject, prop: str ) -> None:
        if prop in ( "Width", "Depth", "Height", "Placement",
                     "PrinterOffsetX", "PrinterOffsetY" ):
            vp = getattr( fp, "ViewObject", None )
            if vp and getattr( vp, "Proxy", None ):
                try:
                    vp.Proxy.onObjectChanged( vp, prop )
                except Exception:
                    pass
                if prop in ( "PrinterOffsetX", "PrinterOffsetY" ):
                    try:
                        vp.Proxy._loaded_gcode_mtime = 0
                        vp.Proxy.onObjectChanged( vp, "ShowGCode" )
                    except Exception:
                        pass

        # Sync dimensions from machine layer when it changes
        if prop == "MachineLayer":
            self._sync_dims_from_machine( fp )

        # Mark dirty for recompute when slice-relevant props change
        if prop in ( "MachineLayer", "UserLayers", "AssignedBodies" ):
            try:
                fp.touch()
            except Exception:
                pass

        # Notify view provider of GCode property changes directly
        # (updateData is not called for property changes in App::FeaturePython)
        gcode_props = {
            "ShowGCode", "GCodeLayerFrom", "GCodeLayerTo", "GCodeShowTravel",
            "GCodeColourMode", "GCodeOutputFile",
            "GCodeShowWallOuter","GCodeShowWallInner","GCodeShowFill",
            "GCodeShowSkin","GCodeShowSupport","GCodeShowSkirt",
            "GCodeShowPrimeTower",
        }
        if prop in gcode_props:
            vp = getattr( fp, "ViewObject", None )
            if vp and getattr( vp, "Proxy", None ):
                try:
                    vp.Proxy.onObjectChanged( vp, prop )
                except Exception:
                    pass
                # Switch display mode automatically
                if prop == "ShowGCode":
                    try:
                        show = getattr( fp, "ShowGCode", False )
                        vp.DisplayMode = "Flat Lines" if show else "Wireframe"
                    except Exception:
                        pass

    def onDocumentRestored( self, fp: FreeCAD.DocumentObject ) -> None:
        """Re-run _init_properties to add any new properties added since creation."""
        self._init_properties( fp )

    def __getstate__( self ):
        return "BuildVolume"

    def __setstate__( self, state ):
        self.Type = "BuildVolume"

    # ------------------------------------------------------------------
    # Dimension sync from MachineLayer

    def _run_slice( self, fp: FreeCAD.DocumentObject ) -> None:
        """Run the slicer and write output to GCodeOutputFile."""
        try:
            from registry_object import get_registry
            from slicer.engine import slice_build_volume
            from Common import Log, LogLevel

            registry = get_registry( fp.Document )
            if registry is None:
                return
            stack  = fp.Proxy.resolve_stack( fp, registry )
            result = slice_build_volume(
                fp, stack,
                output_dir=None,
                progress_cb=lambda msg: Log( LogLevel.info,
                    f"[AutoSlice] { msg }\n" ),
            )
            if result.success and result.gcode_path:
                import shutil
                shutil.copy2( str( result.gcode_path ),
                              fp.GCodeOutputFile )
                Log( LogLevel.info,
                    f"[AutoSlice] G-code written to { fp.GCodeOutputFile }\n" )
                # Trigger G-code viewer refresh if visible
                if getattr( fp, "ShowGCode", False ):
                    vp = getattr( fp, "ViewObject", None )
                    if vp and hasattr( vp, "Proxy" ) and hasattr( vp.Proxy, "update_gcode" ):
                        # Reset mtime cache so update_gcode re-parses
                        vp.Proxy._loaded_gcode_mtime = 0
                        vp.Proxy.update_gcode( fp )
            elif not result.success:
                Log( LogLevel.warning,
                    f"[AutoSlice] Slice failed: { result.error }\n" )
        except Exception as e:
            import traceback
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[AutoSlice] Error: { e }\n{ traceback.format_exc() }\n" )

    def _sync_dims_from_machine( self, fp: FreeCAD.DocumentObject ) -> None:
        """Read machine dimensions and center offset from the linked MachineLayer."""
        ml_fp = getattr( fp, "MachineLayer", None )
        if ml_fp is None:
            return
        try:
            from registry_object import get_registry
            registry = get_registry( fp.Document )
            if registry is None:
                return
            layer = registry.get_machine_layer(
                getattr( ml_fp, "LayerId", "" )
            )
            if layer is None:
                return
            w = layer.get( "machine_width" )
            d = layer.get( "machine_depth" )
            h = layer.get( "machine_height" )
            center = layer.get( "machine_center_is_zero" )
            if w is not None:
                fp.Width  = float( w )
            if d is not None:
                fp.Depth  = float( d )
            if h is not None:
                fp.Height = float( h )
            # Auto-set offset: if center_is_zero, Cura origin = bed center
            # Otherwise Cura origin = bed front-left corner (offset = 0)
            if center and w is not None and d is not None:
                fp.PrinterOffsetX = 0.0
                fp.PrinterOffsetY = 0.0
            else:
                fp.PrinterOffsetX = -float( w ) / 2.0
                fp.PrinterOffsetY = -float( d ) / 2.0
        except Exception as e:
            Console.PrintWarning(
                f"[BuildVolume] Could not sync dims from machine: { e }\n" )

    # ------------------------------------------------------------------
    # Dimension helpers

    def get_dimensions_mm( self, fp: FreeCAD.DocumentObject ) -> tuple[float, float, float]:
        # App::PropertyLength always returns mm
        return (
            float( fp.Width  ),
            float( fp.Depth  ),
            float( fp.Height ),
        )

    # ------------------------------------------------------------------
    # Coordinate transforms

    def get_world_to_printer( self, fp: FreeCAD.DocumentObject ) -> Base.Matrix:
        m = fp.Placement.toMatrix()
        m = m.inverse()
        return m

    def get_printer_to_world( self, fp: FreeCAD.DocumentObject ) -> Base.Matrix:
        m = fp.Placement.toMatrix()
        return m

    def transform_shape_to_printer( self, fp, shape ):
        """
        Transform a FreeCAD shape into printer/CuraEngine coordinate space.
        Applies only the BuildVolume Placement (world → printer).
        PrinterOffsetX/Y is NOT applied here — it only affects the visual
        representation of the build volume and G-code display.
        """
        import Part
        m = self.get_world_to_printer( fp )
        return shape.transformGeometry( m )

    def transform_vector_to_printer( self, fp, v: Base.Vector ) -> Base.Vector:
        m = self.get_world_to_printer( fp )
        return m.multVec( v )

    def transform_vector_from_printer( self, fp, v: Base.Vector ) -> Base.Vector:
        m = self.get_printer_to_world( fp )
        return m.multVec( v )

    def transform_gcode_point(
        self, fp,
        x: float, y: float, z: float,
        scale: float = 1.0
    ) -> tuple[float, float, float]:
        pv = Base.Vector( x * scale, y * scale, z * scale )
        wv = self.transform_vector_from_printer( fp, pv )
        inv = 1.0 / scale if scale else 1.0
        return float( wv.x ) * inv, float( wv.y ) * inv, float( wv.z ) * inv

    # ------------------------------------------------------------------
    # Layer accessors (link-based)

    def get_machine_layer_id( self, fp: FreeCAD.DocumentObject ) -> str:
        ml = getattr( fp, "MachineLayer", None )
        if ml is None:
            return ""
        return getattr( ml, "LayerId", "" )

    def get_user_layer_ids( self, fp: FreeCAD.DocumentObject ) -> list[str]:
        layers = getattr( fp, "UserLayers", None ) or []
        return [ getattr( l, "LayerId", "" ) for l in layers if l ]

    def set_machine_layer_fp( self, fp: FreeCAD.DocumentObject, layer_fp ) -> None:
        fp.MachineLayer = layer_fp

    def set_user_layer_fps( self, fp: FreeCAD.DocumentObject, layer_fps: list ) -> None:
        fp.UserLayers = layer_fps

    def resolve_stack(
        self,
        fp: FreeCAD.DocumentObject,
        registry: "SettingsRegistry",
    ) -> "SettingsStack":
        from settings.stack import SettingsStack
        machine_id  = self.get_machine_layer_id( fp )
        machine     = registry.get_machine_layer( machine_id )
        user_layers = [
            registry.get_user_layer( lid )
            for lid in self.get_user_layer_ids( fp )
            if lid
        ]
        user_layers = [ l for l in user_layers if l is not None ]
        # SettingsStack treats index -1 as highest priority.
        # UserLayers list order: index 0 = top of UI = lowest priority,
        # last item = bottom of UI = highest priority.
        # No reversal needed — bottom of UI list = highest priority.
        return SettingsStack( machine, user_layers )

    # ------------------------------------------------------------------
    # Assigned bodies (link-based)

    def get_assigned_body_objects(
        self, fp: FreeCAD.DocumentObject
    ) -> list:
        return list( getattr( fp, "AssignedBodies", None ) or [] )

    def get_assigned_body_names(
        self, fp: FreeCAD.DocumentObject
    ) -> list[str]:
        return [ b.Name for b in self.get_assigned_body_objects( fp ) if b ]

    def assign_body(
        self, fp: FreeCAD.DocumentObject, body_fp
    ) -> None:
        bodies = list( getattr( fp, "AssignedBodies", None ) or [] )
        if body_fp not in bodies:
            bodies.append( body_fp )
            fp.AssignedBodies = bodies

    def unassign_body(
        self, fp: FreeCAD.DocumentObject, body_fp
    ) -> None:
        bodies = list( getattr( fp, "AssignedBodies", None ) or [] )
        if body_fp in bodies:
            bodies.remove( body_fp )
            fp.AssignedBodies = bodies

    # Keep old string-based API for backward compat with any existing code
    def get_assigned_bodies( self, fp ):
        return self.get_assigned_body_names( fp )


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def make_build_volume(
    doc: FreeCAD.Document,
    name:   str   = "BuildVolume",
    width:  float = 220.0,
    depth:  float = 220.0,
    height: float = 220.0,
) -> FreeCAD.DocumentObject:
    fp = doc.addObject( "App::FeaturePython", name )
    BuildVolume( fp, name )
    fp.Width  = width
    fp.Depth  = depth
    fp.Height = height
    fp.setPropertyStatus( "Label", "ReadOnly" )

    if FreeCAD.GuiUp:
        from build_volume.view_provider import BuildVolumeViewProvider
        BuildVolumeViewProvider( fp.ViewObject )
        # Do NOT call attach() here — FreeCAD calls it naturally when the
        # object appears in the 3D view, at which point all properties are
        # already set and geometry will be correct on first render.

    doc.recompute()

    return fp
