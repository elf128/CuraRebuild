#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# registry_object.py
#
#   Created on:    Mar 15, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   The SettingsRegistry as a FreeCAD FeaturePython document object.
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

import json

import FreeCAD
from FreeCAD import Console

from settings.stack import SettingsRegistry, MachineLayer, UserLayer, BaseLayer
from Common         import Log, LogLevel


REGISTRY_OBJECT_NAME = "__CuraRebuildRegistry__"
_GRP = "Slicer"


class RegistryObject:
    """
    FeaturePython proxy that wraps a live SettingsRegistry.
    Maintains a dict of layer_id → FP object name for child layer objects.
    """

    def __init__( self, fp: FreeCAD.DocumentObject ):
        self._registry:  SettingsRegistry = SettingsRegistry()
        self._layer_fps: dict[str, str]   = {}  # layer_id → fp.Name
        # GroupExtension must be added before fp.Proxy is set
        if not hasattr( fp, "Group" ):
            try:
                fp.addExtension( "App::GroupExtensionPython" )
            except Exception:
                pass
        self._init_properties( fp )
        fp.Proxy  = self
        self.Type = "CuraRebuildRegistry"

    def _init_properties( self, fp: FreeCAD.DocumentObject ) -> None:
        if not hasattr( fp, "RegistryJson" ):
            fp.addProperty(
                "App::PropertyString", "RegistryJson", _GRP,
                "Serialised SettingsRegistry (JSON)"
            ).RegistryJson = "{}"
        fp.setEditorMode( "RegistryJson", 2 )   # hidden

        # GroupExtension is added in __init__ before Proxy is set.

    # ------------------------------------------------------------------
    # Live registry access

    @property
    def registry( self ) -> SettingsRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Layer FP management

    def _create_layer_fp(
        self,
        fp:    FreeCAD.DocumentObject,
        layer: BaseLayer,
    ) -> None:
        """Create a child LayerFpObject for a newly added layer."""
        try:
            from layer_fp_object import create_layer_fp
            child_fp = create_layer_fp( fp.Document, layer, fp )
            self._layer_fps[ layer.id ] = child_fp.Name
            Log( LogLevel.info,
                f"[CuraRebuildRegistry] Created layer FP '{ child_fp.Name }' "
                f"for '{ layer.name }'\n" )
            fp.Document.recompute()
        except Exception as e:
            import traceback
            Log( LogLevel.error,
                f"[CuraRebuildRegistry] Could not create layer FP: { e }\n" )
            Log( LogLevel.error, traceback.format_exc() + "\n" )

    def _restore_layer_fps( self, fp: FreeCAD.DocumentObject ) -> None:
        """
        After document restore: re-link all child LayerFpObjects to their
        freshly-restored layer instances.
        """
        if not FreeCAD.GuiUp:
            return
        try:
            from layer_fp_object import link_layer_fp
        except Exception:
            return

        all_layers: list[BaseLayer] = (
            self._registry.all_machine_layers() +
            self._registry.all_user_layers()
        )
        layer_by_id = { l.id: l for l in all_layers }

        for layer_id, fp_name in list( self._layer_fps.items() ):
            child_fp = fp.Document.getObject( fp_name )
            layer    = layer_by_id.get( layer_id )
            if child_fp and layer:
                link_layer_fp( child_fp, layer )
                # Restore linked file path now that layer is a real BaseLayer
                linked = getattr( child_fp, "LinkedFile", "" )
                if linked:
                    layer.link( linked )
            else:
                # Orphan — remove from tracking
                self._layer_fps.pop( layer_id, None )

        # Create FP objects for any layers that don't have one yet
        for layer in all_layers:
            if layer.id not in self._layer_fps:
                self._create_layer_fp( fp, layer )

    def create_machine_layer(
        self,
        fp:   FreeCAD.DocumentObject,
        name: str,
    ) -> MachineLayer:
        """Create a new MachineLayer, register it, and create its FP child."""
        layer = self._registry.create_machine_layer( name )
        self._create_layer_fp( fp, layer )
        return layer

    def create_user_layer(
        self,
        fp:   FreeCAD.DocumentObject,
        name: str,
    ) -> UserLayer:
        """Create a new UserLayer, register it, and create its FP child."""
        layer = self._registry.create_user_layer( name )
        self._create_layer_fp( fp, layer )
        return layer

    def add_layer(
        self,
        fp:    FreeCAD.DocumentObject,
        layer: BaseLayer,
    ) -> None:
        """Add an existing layer (e.g. imported) and create its FP child."""
        Log( LogLevel.info,
            f"[CuraRebuildRegistry] add_layer called: '{ layer.name }' "
            f"id={ layer.id[:8] } "
            f"type={ type( layer ).__name__ }\n" )
        try:
            if isinstance( layer, MachineLayer ):
                self._registry.add_machine_layer( layer )
            else:
                self._registry.add_user_layer( layer )
        except Exception as e:
            Log( LogLevel.error,
                f"[CuraRebuildRegistry] add_layer registry add failed: { e }\n" )
            return
        self._create_layer_fp( fp, layer )

    def remove_layer(
        self,
        fp:       FreeCAD.DocumentObject,
        layer_id: str,
    ) -> None:
        """Remove a layer from the registry and delete its FP child."""
        fp_name = self._layer_fps.pop( layer_id, None )
        if fp_name:
            child_fp = fp.Document.getObject( fp_name )
            if child_fp:
                fp.Document.removeObject( fp_name )

        # Try both layer types
        try:
            self._registry.remove_machine_layer( layer_id )
        except KeyError:
            pass
        try:
            self._registry.remove_user_layer( layer_id )
        except KeyError:
            pass

    # ------------------------------------------------------------------
    # Persistence

    def save_to_fp( self, fp: FreeCAD.DocumentObject ) -> None:
        try:
            data = self._registry.to_plain_dict()
            data[ "__layer_fps__" ] = self._layer_fps
            fp.RegistryJson = json.dumps( data, ensure_ascii=False )
        except Exception as e:
            Console.PrintError(
                f"[CuraRebuildRegistry] Serialise failed: { e }\n" )

    def load_from_fp( self, fp: FreeCAD.DocumentObject ) -> None:
        try:
            raw = fp.RegistryJson
            if raw and raw.strip() not in ( "", "{}" ):
                data = json.loads( raw )
                self._layer_fps = data.pop( "__layer_fps__", {} )
                self._registry  = SettingsRegistry.from_plain_dict( data )
            else:
                self._registry  = SettingsRegistry()
                self._layer_fps = {}
        except Exception as e:
            Console.PrintError(
                f"[CuraRebuildRegistry] Deserialise failed: { e }\n" )
            self._registry  = SettingsRegistry()
            self._layer_fps = {}

    # ------------------------------------------------------------------
    # FreeCAD protocol

    def execute( self, fp: FreeCAD.DocumentObject ) -> None:
        pass

    def onChanged( self, fp: FreeCAD.DocumentObject, prop: str ) -> None:
        pass

    def onDocumentRestored( self, fp: FreeCAD.DocumentObject ) -> None:
        self.load_from_fp( fp )
        self._restore_layer_fps( fp )
        if FreeCAD.GuiUp:
            fp.setPropertyStatus( "Label", "ReadOnly" )

        # Reload any linked layers from their files
        warned = []
        all_layers = (
            list( self._registry.all_machine_layers() ) +
            list( self._registry.all_user_layers() )
        )
        for layer in all_layers:
            if hasattr( layer, "is_linked" ) and layer.is_linked():
                ok = layer.reload_from_file()
                if not ok:
                    warned.append( layer.linked_path )
                    Log( LogLevel.warning,
                        f"[CuraRebuildRegistry] Linked file not found: "
                        f"'{ layer.linked_path }' for layer '{ layer.name }'\n" )
        if warned:
            try:
                import FreeCADGui
                from PySide2.QtWidgets import QMessageBox
                QMessageBox.warning(
                    None,
                    "Linked files not found",
                    "The following linked layer files could not be found:\n\n" +
                    "\n".join( warned ) +
                    "\n\nFalling back to last known values."
                )
            except Exception:
                pass

        Log( LogLevel.info,
            f"[CuraRebuildRegistry] Restored: "
            f"{ len( self._registry.all_machine_layers() ) } machine(s), "
            f"{ len( self._registry.all_user_layers() ) } user layer(s)\n" )

    def __getstate__( self ):
        # Return plain string — FreeCAD uses this for pickle-based save/restore.
        return "CuraRebuildRegistry"

    def __setstate__( self, state ):
        self.Type        = "CuraRebuildRegistry"
        self._registry   = SettingsRegistry()
        self._layer_fps  = {}

    # Make json.dumps(proxy) safe by implementing the Mapping protocol.
    # json.dumps checks for keys() and treats the object as a dict-like,
    # so it only serializes what we expose here — no private attrs.
    def keys( self ):
        return ( "Type", )

    def __getitem__( self, key ):
        if key == "Type":
            return self.Type
        raise KeyError( key )


class RegistryViewProvider:
    """View provider — group icon, double-click opens Registry panel."""

    def __init__( self, vp ):
        vp.addExtension( "Gui::ViewProviderGroupExtensionPython" )
        vp.Proxy = self

    def getIcon( self ) -> str:
        from Common import getIconPath
        return getIconPath( "Settings.svg" )

    def attach( self, vp ): pass
    def updateData( self, fp, prop ): pass
    def onChanged( self, vp, prop ): pass

    def doubleClicked( self, vp ):
        """Tree double-click — open the Registry panel."""
        try:
            import FreeCADGui
            from registry_object import get_or_create_registry
            fp       = vp.Object
            fp_reg, registry = get_or_create_registry( fp.Document )
            from ui.panels import RegistryPanel
            panel = RegistryPanel( fp_reg, registry )
            FreeCADGui.Control.showDialog( panel )
        except Exception as e:
            import traceback
            from Common import Log, LogLevel
            Log( LogLevel.error,
                f"[CuraRebuildRegistry] doubleClicked failed: { e }\n" )
            Log( LogLevel.error, traceback.format_exc() + "\n" )
        return True

    def setEdit( self, vp, mode=0 ):
        return self.doubleClicked( vp )

    def unsetEdit( self, vp, mode=0 ):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def __getstate__( self ): return None
    def __setstate__( self, state ): pass


# ---------------------------------------------------------------------------
# Document-level helpers
# ---------------------------------------------------------------------------

def get_registry( doc: FreeCAD.Document | None = None ) -> SettingsRegistry | None:
    doc = doc or FreeCAD.ActiveDocument
    if doc is None:
        return None
    fp = doc.getObject( REGISTRY_OBJECT_NAME )
    if fp is None or not hasattr( fp, "Proxy" ):
        return None
    return fp.Proxy.registry


def get_registry_fp( doc: FreeCAD.Document | None = None ) -> FreeCAD.DocumentObject | None:
    doc = doc or FreeCAD.ActiveDocument
    if doc is None:
        return None
    return doc.getObject( REGISTRY_OBJECT_NAME )


def get_or_create_registry(
    doc: FreeCAD.Document | None = None,
) -> tuple[FreeCAD.DocumentObject, SettingsRegistry]:
    doc = doc or FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError( "No active FreeCAD document." )

    fp = doc.getObject( REGISTRY_OBJECT_NAME )
    if fp is not None and hasattr( fp, "Proxy" ):
        return fp, fp.Proxy.registry

    fp        = doc.addObject( "App::FeaturePython", REGISTRY_OBJECT_NAME )
    fp.Label  = "CuraRebuild Settings"
    proxy     = RegistryObject( fp )

    if FreeCAD.GuiUp:
        RegistryViewProvider( fp.ViewObject )
        # Prevent FreeCAD's default rename-on-double-click behaviour.
        # In 0.21 this is the only reliable way — mark Label read-only
        # in the property editor so the tree widget doesn't enter edit mode.
        fp.setPropertyStatus( "Label", "ReadOnly" )

    Log( LogLevel.info, "[CuraRebuildRegistry] Created new SettingsRegistry.\n" )
    return fp, proxy.registry


def flush_registry( doc: FreeCAD.Document | None = None ) -> None:
    doc = doc or FreeCAD.ActiveDocument
    if doc is None:
        return
    fp = doc.getObject( REGISTRY_OBJECT_NAME )
    if fp is not None and hasattr( fp, "Proxy" ):
        fp.Proxy.save_to_fp( fp )
