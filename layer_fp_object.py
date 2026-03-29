#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# layer_fp_object.py
#
#   Created on:    Mar 17, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
# FeaturePython wrapper for a single MachineLayer or UserLayer.
# Exposes every setting as a typed App::Property so the user can
# edit values directly in FreeCAD's Properties panel.
#
# Each setting maps to:
#   bool   → App::PropertyBool
#   int    → App::PropertyInteger
#   float  → App::PropertyFloat   (with unit where applicable)
#   str    → App::PropertyString
#
# Settings are grouped by their schema Category into property groups.
# The group name is the category name, visible as a collapsible section
# in the Properties panel.
#
# Two-way sync:
#   layer → FP:  call sync_to_fp( fp )   — writes layer values to properties
#   FP → layer:  onChanged() fires on every edit — writes property back to layer
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
from FreeCAD import Console

from settings.schema import SCHEMA, BY_CATEGORY, SettingDef, Category, LayerRole
from settings.stack  import BaseLayer, MachineLayer, UserLayer
from Common          import Log, LogLevel


def _get_schema() -> dict:
    """Return the active schema dict from the registry."""
    try:
        from settings.schema import get_registry as _gr
        return _gr().schema
    except Exception:
        return SCHEMA


# Categories shown for machine layers
_MACHINE_CATEGORIES = [
    Category.MACHINE,
    Category.GCODE,
]

# Categories shown for user layers (everything except object-level)
_USER_CATEGORIES = [
    Category.MATERIAL,
    Category.QUALITY,
    Category.WALLS,
    Category.TOP_BOTTOM,
    Category.INFILL,
    Category.SPEED,
    Category.TRAVEL,
    Category.COOLING,
    Category.SUPPORT,
    Category.ADHESION,
]

# Map category → property group label shown in Properties panel
_GROUP_LABELS = {
    Category.MACHINE:    "Machine",
    Category.GCODE:      "G-Code",
    Category.MATERIAL:   "Material",
    Category.QUALITY:    "Quality",
    Category.WALLS:      "Walls",
    Category.TOP_BOTTOM: "Top / Bottom",
    Category.INFILL:     "Infill",
    Category.SPEED:      "Speed",
    Category.TRAVEL:     "Travel",
    Category.COOLING:    "Cooling",
    Category.SUPPORT:    "Support",
    Category.ADHESION:   "Adhesion",
}

# Property type string per dtype
_PROP_TYPE = {
    bool:  "App::PropertyBool",
    int:   "App::PropertyInteger",
    float: "App::PropertyFloat",
    str:   "App::PropertyString",
}

# Enum settings use App::PropertyEnumeration
def _prop_type_for( sdef ) -> str:
    if sdef.options:
        return "App::PropertyEnumeration"
    return _PROP_TYPE.get( sdef.dtype, "App::PropertyString" )


def _categories_for_layer( layer: BaseLayer ) -> list[str]:
    return _MACHINE_CATEGORIES if isinstance( layer, MachineLayer ) else _USER_CATEGORIES


def _prop_name( key: str ) -> str:
    """Convert a schema key to a valid FreeCAD property name (no dots, no spaces)."""
    return key.replace( ".", "_" )


def _tooltip( sdef: SettingDef ) -> str:
    tip = sdef.description or sdef.label
    if sdef.unit:
        tip += f" [{ sdef.unit }]"
    return tip


# ---------------------------------------------------------------------------
# LayerFpObject
# ---------------------------------------------------------------------------

class LayerFpObject:
    """
    FeaturePython proxy for one MachineLayer or UserLayer.

    The proxy holds a reference to the live layer object.
    Properties are created once in __init__ / _init_properties.
    onChanged() keeps the layer in sync when the user edits a property.
    """

    def __init__( self, fp: FreeCAD.DocumentObject, layer: BaseLayer ):
        self._layer             = layer
        self._syncing           = False   # guard against recursive onChanged
        self._init_in_progress  = True   # suppress onChanged during init
        fp.Proxy                = self
        self.Type               = "CuraRebuildLayer"
        self._init_properties( fp )
        self.sync_to_fp( fp )
        self._init_in_progress  = False

    def _init_properties( self, fp: FreeCAD.DocumentObject ) -> None:
        """Add App::Property* for every setting in the relevant categories."""
        existing = set( fp.PropertiesList )
        cats     = _categories_for_layer( self._layer )

        for cat in cats:
            group = _GROUP_LABELS.get( cat, cat )
            for sdef in BY_CATEGORY.get( cat, [] ):
                pname = _prop_name( sdef.key )
                if pname in existing:
                    continue
                ptype = _prop_type_for( sdef )
                try:
                    fp.addProperty( ptype, pname, group, _tooltip( sdef ) )
                except Exception as e:
                    Log( LogLevel.warning,
                        f"[LayerFP] Could not add property '{ pname }': { e }\n" )

        # Identity properties — used by BuildVolume to find back the layer
        if "LayerId" not in existing:
            fp.addProperty(
                "App::PropertyString", "LayerId",
                "CuraRebuild", "Unique layer UUID"
            )
            fp.setPropertyStatus( "LayerId", "ReadOnly" )

        if "LayerType" not in existing:
            fp.addProperty(
                "App::PropertyString", "LayerType",
                "CuraRebuild", "MachineLayer or UserLayer"
            )
            fp.setPropertyStatus( "LayerType", "ReadOnly" )

        # Linked file meta-property
        if "LinkedFile" not in existing:
            fp.addProperty(
                "App::PropertyString", "LinkedFile",
                "CuraRebuild",
                "Path to linked JSON file (empty = internal storage)"
            )

        # Extruder targeting — FreeCAD side only, not saved in JSON
        if "ApplyTo" not in existing:
            fp.addProperty(
                "App::PropertyString", "ApplyTo",
                "CuraRebuild",
                "Extruders this layer applies to: 'all' or comma-separated "
                "indices e.g. '0,1'"
            ).ApplyTo = "all"

    # ------------------------------------------------------------------
    # Two-way sync

    def sync_to_fp( self, fp: FreeCAD.DocumentObject ) -> None:
        """Write all layer values to FP properties."""
        self._syncing = True
        try:
            # Always keep identity properties in sync
            from settings.stack import BaseLayer
            if isinstance( self._layer, BaseLayer ):
                if hasattr( fp, "LayerId" ) and fp.LayerId != self._layer.id:
                    fp.LayerId   = self._layer.id
                if hasattr( fp, "LayerType" ):
                    fp.LayerType = self._layer.__class__.__name__
                if hasattr( fp, "Label" ) and fp.Label != self._layer.name:
                    fp.Label     = self._layer.name
            schema = _get_schema()
            for key, sdef in schema.items():
                pname = _prop_name( key )
                if not hasattr( fp, pname ):
                    continue
                val = self._layer.get( key )
                if val is None:
                    val = sdef.default

                # Skip if val is a Cura expression string (not a resolved value).
                # This happens when a layer was seeded with value_expr defaults.
                if isinstance( val, str ) and sdef.dtype != str:
                    continue
                if sdef.options and isinstance( val, str ):
                    # For enums, only set if the value is actually in the options list
                    if val not in sdef.options:
                        continue

                try:
                    if sdef.options:
                        cur = getattr( fp, pname, None )
                        if str( cur ) != str( val ):
                            try:
                                setattr( fp, pname, str( val ) )
                            except Exception:
                                setattr( fp, pname, sdef.options )
                                setattr( fp, pname, str( val ) )
                    else:
                        setattr( fp, pname, sdef.dtype( val ) )
                except Exception as e:
                    Log( LogLevel.debug,
                        f"[LayerFP] sync_to_fp: '{ pname }' = { val!r }: { e }\n" )
        finally:
            self._syncing = False
        # Sync linked file path
        if self._layer and hasattr( fp, "LinkedFile" ):
            try:
                linked = self._layer.linked_path or ""
                if fp.LinkedFile != linked:
                    fp.LinkedFile = linked
            except Exception:
                pass

    def sync_from_fp( self, fp: FreeCAD.DocumentObject ) -> None:
        """Read all FP properties back into the layer."""
        for key, sdef in SCHEMA.items():
            pname = _prop_name( key )
            if not hasattr( fp, pname ):
                continue
            try:
                val = getattr( fp, pname )
                self._layer.set( key, val )
            except Exception as e:
                Log( LogLevel.debug,
                    f"[LayerFP] sync_from_fp: '{ pname }': { e }\n" )

    # ------------------------------------------------------------------
    # FreeCAD protocol

    def execute( self, fp: FreeCAD.DocumentObject ) -> None:
        pass

    def onChanged( self, fp: FreeCAD.DocumentObject, prop: str ) -> None:
        """User edited a property in the Properties panel — sync to layer."""
        if self._syncing:
            return
        from settings.stack import BaseLayer
        if not isinstance( self._layer, BaseLayer ):
            return   # not yet linked — still None or str during restore

        # Look up in live schema
        schema = _get_schema()
        sdef   = schema.get( prop )
        if sdef is None:
            return   # not a settings property (Label, LinkedFile, etc.)

        # Guard: only sync if the value actually differs from what the layer has.
        # This prevents onChanged fires during addProperty() from polluting the layer.
        try:
            val = getattr( fp, prop )
        except Exception:
            return

        current = self._layer.get( prop )
        try:
            validated = sdef.safe_validate( val )
        except Exception:
            return

        if validated == current:
            return   # no actual change — skip (avoids init-time pollution)

        try:
            self._layer.set( prop, validated )
            # Debounce registry flush — only flush on explicit user edits,
            # not during bulk sync operations
            if not getattr( self, "_init_in_progress", False ):
                _flush_registry_for_fp( fp )
        except Exception as e:
            Log( LogLevel.debug,
                f"[LayerFP] onChanged '{ prop }': { e }\n" )

    def onDocumentRestored( self, fp: FreeCAD.DocumentObject ) -> None:
        # Layer content is restored from registry JSON by the registry object.
        # Once that's done, sync_to_fp is called by the registry.
        if FreeCAD.GuiUp:
            fp.setPropertyStatus( "Label", "ReadOnly" )
        # Restore linked file path onto the layer object.
        # Guard: self._layer may still be None or str at this point —
        # the registry re-links it later via _restore_layer_fps().
        from settings.stack import BaseLayer
        if isinstance( self._layer, BaseLayer ):
            linked = getattr( fp, "LinkedFile", "" )
            if linked:
                self._layer.link( linked )

    def __getstate__( self ):
        # Return plain string — FreeCAD uses this for pickle-based save/restore.
        return "CuraRebuildLayer"

    def __setstate__( self, state ):
        self.Type              = "CuraRebuildLayer"
        self._layer            = None
        self._syncing          = False
        self._init_in_progress = False

    # Mapping protocol so json.dumps(proxy) serializes safely.
    def keys( self ):
        return ( "Type", )

    def __getitem__( self, key ):
        if key == "Type":
            return self.Type
        raise KeyError( key )


class LayerViewProvider:
    """View provider — icon + double-click opens layer editor."""

    def __init__( self, vp ):
        vp.Proxy = self

    def getIcon( self ) -> str:
        from Common import getIconPath
        return getIconPath( "Tool.svg" )

    def attach( self, vp ): pass
    def updateData( self, fp, prop ): pass
    def onChanged( self, vp, prop ): pass

    def doubleClicked( self, vp ):
        """Intercept double-click — open the layer editor dialog."""
        try:
            import FreeCADGui
            from registry_object import get_registry_fp
            fp       = vp.Object
            doc      = fp.Document
            reg_fp   = get_registry_fp( doc )
            if reg_fp is None or not hasattr( reg_fp, "Proxy" ):
                return False

            registry = reg_fp.Proxy.registry
            proxy    = fp.Proxy
            if proxy._layer is None:
                return False

            from settings.stack import MachineLayer
            from ui.panels import MachineLayerPanel, UserLayerPanel

            if isinstance( proxy._layer, MachineLayer ):
                panel = MachineLayerPanel(
                    registry, doc, existing_layer=proxy._layer
                )
            else:
                panel = UserLayerPanel(
                    registry, doc, existing_layer=proxy._layer
                )
            panel.show_as_dialog()
        except Exception as e:
            import traceback
            from Common import Log, LogLevel
            Log( LogLevel.error,
                f"[LayerFP] doubleClicked failed: { e }\n" )
            Log( LogLevel.error, traceback.format_exc() + "\n" )
        return True

    def setEdit( self, vp, mode=0 ):
        if mode != 0:
            return False
        return self.doubleClicked( vp )

    def unsetEdit( self, vp, mode=0 ):
        return True

    def __getstate__( self ): return None
    def __setstate__( self, state ): pass


# ---------------------------------------------------------------------------
# Registry-level helpers
# ---------------------------------------------------------------------------

def _flush_registry_for_fp( fp: FreeCAD.DocumentObject ) -> None:
    """Find the registry object in the same document and flush it."""
    try:
        from registry_object import flush_registry
        flush_registry( fp.Document )
    except Exception:
        pass


def create_layer_fp(
    doc:       FreeCAD.Document,
    layer:     BaseLayer,
    parent_fp: FreeCAD.DocumentObject,
) -> FreeCAD.DocumentObject:
    """
    Create a LayerFpObject document object for a layer and nest it
    under the registry object in the model tree.
    """
    fp       = doc.addObject( "App::FeaturePython", f"Layer_{ layer.id[:8] }" )
    fp.Label = layer.name

    LayerFpObject( fp, layer )

    if FreeCAD.GuiUp:
        LayerViewProvider( fp.ViewObject )
        fp.setPropertyStatus( "Label", "ReadOnly" )

    # Nest under parent.
    # In FreeCAD 0.21 the reliable way to add a child to a group is to
    # directly set the Group property list on the parent.
    try:
        if hasattr( parent_fp, "Group" ):
            grp = list( parent_fp.Group )
            if fp not in grp:
                grp.append( fp )
                parent_fp.Group = grp
    except Exception as e:
        from Common import Log, LogLevel
        Log( LogLevel.warning,
            f"[LayerFP] Could not nest under parent: { e }\n" )

    return fp


def link_layer_fp(
    fp:    FreeCAD.DocumentObject,
    layer: BaseLayer,
) -> None:
    """
    Re-link an existing LayerFpObject to a (freshly restored) layer and
    sync all properties from the layer's current values.
    Called by the registry after document restore.
    """
    if not hasattr( fp, "Proxy" ) or not isinstance( fp.Proxy, LayerFpObject ):
        return
    fp.Proxy._layer = layer
    fp.Proxy.sync_to_fp( fp )
