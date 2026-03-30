#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# Commands.py
#
#   Created on:    Mar 15, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   FreeCAD command classes for CuraRebuild.
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

import FreeCAD
import FreeCADGui
from FreeCAD import Console
from Common  import Log, LogLevel, getIconPath


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _require_active_doc( cmd_name: str ) -> FreeCAD.Document | None:
    doc = FreeCAD.ActiveDocument
    if doc is None:
        from PySide2.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "No Document",
            f"{ cmd_name } requires an open document.",
        )
    return doc


# ---------------------------------------------------------------------------
# Command: Create Build Volume
# ---------------------------------------------------------------------------

class CmdCreateBuildVolume:
    """Add a new BuildVolume object to the document."""

    def GetResources( self ):
        return {
            "MenuText": "Create Build Volume",
            "ToolTip":  "Add a new printer build volume to the scene",
            "Pixmap":   getIconPath( "Volume.svg" ),
        }

    def IsActive( self ):
        return FreeCAD.ActiveDocument is not None

    def Activated( self ):
        doc = _require_active_doc( "Create Build Volume" )
        if doc is None:
            return

        from registry_object import get_or_create_registry
        fp_reg, registry = get_or_create_registry( doc )

        if not registry.all_machine_layers():
            from ui.panels import MachineLayerPanel
            Log( LogLevel.info, "[CuraRebuild] No machine layers found — opening creator.\n" )
            panel = MachineLayerPanel( registry, doc )
            FreeCADGui.Control.showDialog( panel )
            return

        from ui.panels import BuildVolumeCreationPanel
        panel = BuildVolumeCreationPanel( registry, doc )
        FreeCADGui.Control.showDialog( panel )


# ---------------------------------------------------------------------------
# Command: Edit Build Volume
# ---------------------------------------------------------------------------

class CmdEditBuildVolume:
    """Open the settings panel for the selected BuildVolume."""

    def GetResources( self ):
        return {
            "MenuText": "Edit Build Volume",
            "ToolTip":  "Edit settings and layer stack for the selected build volume",
            "Pixmap":   "Part_Box",
        }

    def IsActive( self ):
        sel = FreeCADGui.Selection.getSelection()
        if not sel:
            return False
        return (
            hasattr( sel[0], "Proxy" )
            and getattr( sel[0].Proxy, "Type", "" ) == "BuildVolume"
        )

    def Activated( self ):
        sel = FreeCADGui.Selection.getSelection()
        if not sel:
            return

        fp = sel[0]
        if not ( hasattr( fp, "Proxy" ) and fp.Proxy.Type == "BuildVolume" ):
            return

        from registry_object import get_registry
        registry = get_registry()
        if registry is None:
            Log( LogLevel.error, "[CuraRebuild] No SettingsRegistry found in document.\n" )
            return

        from ui.panels import BuildVolumePanel
        panel = BuildVolumePanel( fp, registry )
        FreeCADGui.Control.showDialog( panel )


# ---------------------------------------------------------------------------
# Command: Assign Bodies to Build Volume
# ---------------------------------------------------------------------------

class CmdAssignBodies:
    """Assign selected Part/Body objects to a Build Volume."""

    def GetResources( self ):
        return {
            "MenuText": "Assign to Build Volume",
            "ToolTip":  "Assign selected bodies to a build volume for slicing",
            "Pixmap":   "Part_Fuse",
        }

    def IsActive( self ):
        return (
            FreeCAD.ActiveDocument is not None
            and len( FreeCADGui.Selection.getSelection() ) > 0
        )

    def Activated( self ):
        doc = _require_active_doc( "Assign Bodies" )
        if doc is None:
            return

        sel = FreeCADGui.Selection.getSelection()
        if not sel:
            return

        build_volumes = [
            obj for obj in doc.Objects
            if hasattr( obj, "Proxy" )
            and getattr( obj.Proxy, "Type", "" ) == "BuildVolume"
        ]

        if not build_volumes:
            from PySide2.QtWidgets import QMessageBox
            QMessageBox.warning(
                None,
                "No Build Volumes",
                "Create a Build Volume first before assigning bodies.",
            )
            return

        from ui.panels import AssignBodiesPanel
        panel = AssignBodiesPanel( sel, build_volumes )
        FreeCADGui.Control.showDialog( panel )


# ---------------------------------------------------------------------------
# Command: Slice
# ---------------------------------------------------------------------------

class CmdSlice:
    """Run CuraEngine on the selected or active Build Volume."""

    def GetResources( self ):
        return {
            "MenuText": "Slice",
            "ToolTip":  "Slice the selected Build Volume with CuraEngine",
            "Pixmap":   getIconPath( "3DPrint.svg" ),
        }

    def IsActive( self ):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return False
        for obj in doc.Objects:
            if (
                hasattr( obj, "Proxy" )
                and getattr( obj.Proxy, "Type", "" ) == "BuildVolume"
                and obj.Proxy.get_assigned_bodies( obj )
            ):
                return True
        return False

    def Activated( self ):
        doc = _require_active_doc( "Slice" )
        if doc is None:
            return

        from registry_object import get_registry
        registry = get_registry( doc )
        if registry is None:
            Log( LogLevel.error,
                "[CuraRebuild] No SettingsRegistry in document. "
                "Create a Build Volume first.\n"
            )
            return

        from ui.panels import SlicePanel
        panel = SlicePanel( doc, registry )
        FreeCADGui.Control.showDialog( panel )


# ---------------------------------------------------------------------------
# Command: Create User Layer
# ---------------------------------------------------------------------------

class CmdCreateUserLayer:
    """Add a new named user layer to the registry."""

    def GetResources( self ):
        return {
            "MenuText": "New Settings Layer",
            "ToolTip":  "Create a new named settings layer in the registry",
            "Pixmap":   getIconPath( "Tool.svg" ),
        }

    def IsActive( self ):
        return FreeCAD.ActiveDocument is not None

    def Activated( self ):
        doc = _require_active_doc( "New Settings Layer" )
        if doc is None:
            return

        from registry_object import get_or_create_registry
        fp_reg, registry = get_or_create_registry( doc )

        from ui.panels import UserLayerPanel
        panel = UserLayerPanel( registry, doc )
        panel.show_as_dialog()


# ---------------------------------------------------------------------------
# Command: Create Machine Layer
# ---------------------------------------------------------------------------

class CmdCreateMachineLayer:
    """Add a new machine definition to the registry."""

    def GetResources( self ):
        return {
            "MenuText": "New Machine Definition",
            "ToolTip":  "Create a new printer machine definition",
            "Pixmap":   getIconPath( "Settings.svg" ),
        }

    def IsActive( self ):
        return FreeCAD.ActiveDocument is not None

    def Activated( self ):
        doc = _require_active_doc( "New Machine Definition" )
        if doc is None:
            return

        from registry_object import get_or_create_registry
        fp_reg, registry = get_or_create_registry( doc )

        from ui.panels import MachineLayerPanel
        panel = MachineLayerPanel( registry, doc )
        panel.show_as_dialog()


# ---------------------------------------------------------------------------
# G-Code Reload
# ---------------------------------------------------------------------------

class CmdReloadGCode:
    def GetResources( self ):
        return {
            "Pixmap":   "Path-Topo-Shape",
            "MenuText": "Reload G-Code",
            "ToolTip":  "Re-parse the G-code file and refresh the 3D viewport",
        }

    def IsActive( self ):
        doc = FreeCAD.ActiveDocument
        if not doc:
            return False
        for obj in doc.Objects:
            if getattr( getattr(obj,"Proxy",None), "Type", "" ) == "BuildVolume":
                return bool( getattr( obj, "GCodeOutputFile", "" ) )
        return False

    def Activated( self ):
        doc = FreeCAD.ActiveDocument
        if not doc:
            return
        bv_fp = None
        sel = FreeCADGui.Selection.getSelection( doc.Name )
        for obj in sel:
            if getattr( getattr(obj,"Proxy",None), "Type", "" ) == "BuildVolume":
                bv_fp = obj; break
        if bv_fp is None:
            for obj in doc.Objects:
                if getattr( getattr(obj,"Proxy",None), "Type", "" ) == "BuildVolume":
                    bv_fp = obj; break
        if bv_fp is None:
            return
        vp = getattr( bv_fp, "ViewObject", None )
        if vp and hasattr( vp, "Proxy" ) and hasattr( vp.Proxy, "update_gcode" ):
            vp.Proxy._loaded_gcode_mtime = 0
            vp.Proxy.update_gcode( bv_fp )


# ---------------------------------------------------------------------------
# Register all commands with FreeCAD
# ---------------------------------------------------------------------------

_registered = False

def register_all():
    global _registered
    if _registered:
        return
    FreeCADGui.addCommand( "CuraRebuild_CreateBuildVolume",  CmdCreateBuildVolume() )
    FreeCADGui.addCommand( "CuraRebuild_EditBuildVolume",    CmdEditBuildVolume() )
    FreeCADGui.addCommand( "CuraRebuild_AssignBodies",       CmdAssignBodies() )
    FreeCADGui.addCommand( "CuraRebuild_Slice",              CmdSlice() )
    FreeCADGui.addCommand( "CuraRebuild_ReloadGCode",        CmdReloadGCode() )
    FreeCADGui.addCommand( "CuraRebuild_CreateUserLayer",    CmdCreateUserLayer() )
    FreeCADGui.addCommand( "CuraRebuild_CreateMachineLayer", CmdCreateMachineLayer() )
    _registered = True


# ---------------------------------------------------------------------------
# Hot-reload support
#
# Called by InitGui.Reload() on every Activated().
# Reloads all workbench modules in dependency order (leaves first)
# so that live edits take effect without restarting FreeCAD.
# ---------------------------------------------------------------------------

def Reload():
    from importlib import reload
    import sys

    # Proxy classes on live document objects (registry_object, layer_fp_object,
    # build_volume.build_volume) cannot be hot-reloaded — FreeCAD holds C++
    # refs to existing instances which were created from the old class.
    # Everything else — UI, settings logic, import code — reloads cleanly.
    _modules = [
        "Common",
        "settings.schema",
        "settings.stack",
        "settings.storage",
        "settings.cura_export",
        "layer_fp_object",
        "registry_object",
        "build_volume.view_provider",
        "build_volume.build_volume",
        "gcode_viewer.parser",
        "gcode_viewer.renderer",
        "ui.cura_import",

        "ui.panels",
        "slicer.engine",
    ]

    for name in _modules:
        if name in sys.modules:
            try:
                reload( sys.modules[ name ] )
                Log( LogLevel.debug, f"[CuraRebuild] Reloaded {name}\n" )
            except Exception as e:
                import traceback
                Log( LogLevel.warning,
                    f"[CuraRebuild] Reload failed for {name}: {e}\n" )
                Log( LogLevel.warning, traceback.format_exc() + "\n" )

    # Reload Commands last and re-register so new command code takes effect
    global _registered
    _registered = False
    if "Commands" in sys.modules:
        try:
            reload( sys.modules[ "Commands" ] )
        except Exception as e:
            Log( LogLevel.warning,
                f"[CuraRebuild] Reload failed for Commands: {e}\n" )
    register_all()

    # Rebind view provider proxies on all live layer and registry objects
    # so that methods added/changed during reload take effect immediately
    # without requiring object deletion and recreation.
    try:
        import FreeCAD, FreeCADGui
        from layer_fp_object  import LayerFpObject, LayerViewProvider
        from registry_object  import RegistryObject, RegistryViewProvider, REGISTRY_OBJECT_NAME

        doc = FreeCAD.ActiveDocument
        if doc:
            for obj in doc.Objects:
                if not hasattr( obj, "Proxy" ):
                    continue
                # Rebind data proxy
                if isinstance( obj.Proxy, LayerFpObject ):
                    obj.Proxy.__class__ = LayerFpObject
                elif isinstance( obj.Proxy, RegistryObject ):
                    obj.Proxy.__class__ = RegistryObject
                # Rebind view provider proxy
                if FreeCAD.GuiUp and hasattr( obj, "ViewObject" ) and obj.ViewObject:
                    vp = obj.ViewObject
                    if hasattr( vp, "Proxy" ):
                        if isinstance( vp.Proxy, LayerViewProvider ):
                            vp.Proxy.__class__ = LayerViewProvider
                        elif isinstance( vp.Proxy, RegistryViewProvider ):
                            vp.Proxy.__class__ = RegistryViewProvider
        Log( LogLevel.debug, "[CuraRebuild] Proxy classes rebound.\n" )
    except Exception as e:
        Log( LogLevel.warning, f"[CuraRebuild] Proxy rebind failed: {e}\n" )

    Log( LogLevel.info, "[CuraRebuild] Hot-reload complete.\n" )
