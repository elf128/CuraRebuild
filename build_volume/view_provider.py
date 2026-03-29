#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# build_volume/view_provider.py
#
#   Created on:    Mar 27, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
# Coin3D (OpenInventor) view provider for BuildVolume.
#
# Renders:
#   1. A wireframe box representing the full build envelope
#   2. A grid on the Z=0 plane representing the print bed surface
#
#   All geometry is rebuilt from scratch whenever dimensions or placement change.
#   We use raw Coin3D nodes for full control.
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
from FreeCAD import Console
from FreeCAD import Base

try:
    from pivy import coin
    import FreeCADGui
    _GUI_AVAILABLE = True
except ImportError:
    _GUI_AVAILABLE = False

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Visual constants (easy to tune)
# ---------------------------------------------------------------------------

# Envelope wireframe
_BOX_COLOR       = (0.2, 0.6, 1.0)   # light blue
_BOX_LINE_WIDTH  = 1.5

# Bed grid
_GRID_COLOR      = (0.3, 0.7, 0.3)   # green
_GRID_LINE_WIDTH = 1.0
_GRID_SPACING    = 10.0               # mm between grid lines

# Bed plane fill (semi-transparent)
_BED_COLOR       = (0.15, 0.55, 0.15)
_BED_ALPHA       = 0.15               # 0=transparent, 1=opaque

# Axis indicator length
_AXIS_LENGTH     = 20.0               # mm


# ---------------------------------------------------------------------------
# Helper: build a SoLineSet from a list of (start, end) pairs
# ---------------------------------------------------------------------------

def _make_lineset(
    lines: list[tuple[tuple, tuple]],
    color: tuple,
    line_width: float,
) -> coin.SoSeparator:
    """
    Returns a Separator containing a line set drawn with the given color
    and line width. Each element of `lines` is ((x0,y0,z0), (x1,y1,z1)).
    """
    sep = coin.SoSeparator()

    # Material
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(coin.SbColor(*color))
    mat.emissiveColor.setValue(coin.SbColor(*color))
    sep.addChild(mat)

    # Line width
    ds = coin.SoDrawStyle()
    ds.lineWidth = line_width
    sep.addChild(ds)

    # Coordinates
    coords = coin.SoCoordinate3()
    pts = []
    for (x0, y0, z0), (x1, y1, z1) in lines:
        pts.append((x0, y0, z0))
        pts.append((x1, y1, z1))
    coords.point.setValues(0, len(pts), pts)
    sep.addChild(coords)

    # Line set: each line is 2 vertices
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, len(lines), [2] * len(lines))
    sep.addChild(ls)

    return sep


def _make_quad(
    x0: float, y0: float, x1: float, y1: float, z: float,
    color: tuple, alpha: float,
) -> coin.SoSeparator:
    """Return a filled quad (bed plane) with transparency."""
    sep = coin.SoSeparator()

    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(coin.SbColor(*color))
    mat.transparency.setValue(1.0 - alpha)
    sep.addChild(mat)

    coords = coin.SoCoordinate3()
    coords.point.setValues(0, 4, [
        (x0, y0, z),
        (x1, y0, z),
        (x1, y1, z),
        (x0, y1, z),
    ])
    sep.addChild(coords)

    face = coin.SoFaceSet()
    face.numVertices.setValue(4)
    sep.addChild(face)

    return sep


# ---------------------------------------------------------------------------
# Geometry builders
# ---------------------------------------------------------------------------

def _build_envelope_lines( w: float, d: float, h: float ) -> list[tuple]:
    """12 edges of a box from (0,0,0) to (w,d,h). Offset applied via SoTransform."""
    lines = []
    corners = [
        (0, 0, 0), (w, 0, 0), (w, d, 0), (0, d, 0),
        (0, 0, h), (w, 0, h), (w, d, h), (0, d, h),
    ]
    edges = [
        (0,1),(1,2),(2,3),(3,0),   # bottom face
        (4,5),(5,6),(6,7),(7,4),   # top face
        (0,4),(1,5),(2,6),(3,7),   # verticals
    ]
    for a, b in edges:
        lines.append((corners[a], corners[b]))
    return lines


def _build_grid_lines( w: float, d: float, spacing: float ) -> list[tuple]:
    """Grid lines on Z=0 plane within [0..w] x [0..d]. Offset via SoTransform."""
    lines = []
    x = 0.0
    while x <= w + 1e-6:
        lines.append(((x, 0, 0), (x, d, 0)))
        x += spacing
    y = 0.0
    while y <= d + 1e-6:
        lines.append(((0, y, 0), (w, y, 0)))
        y += spacing
    return lines


def _build_axis_lines(length: float) -> coin.SoSeparator:
    """Small RGB axis indicator at the origin."""
    sep = coin.SoSeparator()
    ds = coin.SoDrawStyle()
    ds.lineWidth = 2.0
    sep.addChild(ds)

    axes = [
        ((1, 0, 0), (length, 0, 0)),   # X — red
        ((0, 1, 0), (0, length, 0)),   # Y — green
        ((0, 0, 1), (0, 0, length)),   # Z — blue
    ]
    colors = [(1,0,0), (0,1,0), (0,0,1)]

    for (color, (ex, ey, ez)) in zip(colors, [a[1] for a in axes]):
        axis_sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(coin.SbColor(*color))
        mat.emissiveColor.setValue(coin.SbColor(*color))
        axis_sep.addChild(mat)

        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 2, [(0,0,0), (ex,ey,ez)])
        axis_sep.addChild(coords)

        ls = coin.SoLineSet()
        ls.numVertices.setValue(2)
        axis_sep.addChild(ls)

        sep.addChild(axis_sep)

    return sep


# ---------------------------------------------------------------------------
# View Provider
# ---------------------------------------------------------------------------

class BuildVolumeViewProvider:
    """
    Coin3D view provider for BuildVolume.
    Renders a wireframe envelope + bed grid in the 3D viewport.
    """

    def __init__(self, vp):
        vp.Proxy    = self
        self._root  = None
        self._vp    = vp
        self._gcode_root         = None
        self._gcode_renderer     = None
        self._loaded_gcode_path  = None
        self._loaded_gcode_mtime = 0
        self._offset_transform   = None
        self._attached           = False

    # ------------------------------------------------------------------
    # Coin3D scene setup

    def attach(self, vp):
        self._ensure_attrs()
        self._vp = vp

        if self._root is None:
            # Build scene graph
            self._root = coin.SoSeparator()

            self._offset_transform = coin.SoMatrixTransform()
            self._root.addChild( self._offset_transform )

            self._envelope_node = coin.SoSeparator()
            self._grid_node     = coin.SoSeparator()
            self._bed_node      = coin.SoSeparator()
            self._axis_node     = coin.SoSeparator()

            self._root.addChild(self._envelope_node)
            self._root.addChild(self._grid_node)
            self._root.addChild(self._bed_node)
            self._root.addChild(self._axis_node)

            if _GUI_AVAILABLE:
                self._gcode_root = coin.SoSeparator()
                self._root.addChild( self._gcode_root )

            try:
                from gcode_viewer.renderer import GCodeRenderer
                self._gcode_renderer = GCodeRenderer()
            except Exception:
                self._gcode_renderer = None

        # Register display modes.
        # On repeated calls (property init firing attach multiple times),
        # switch display mode first to force FreeCAD to re-evaluate the scene.
        try:
            existing = vp.DisplayMode
            vp.DisplayMode = "Wireframe" if existing != "Wireframe" else "Flat Lines"
        except Exception:
            existing = "Flat Lines"
        vp.addDisplayMode(self._root, "Wireframe")
        vp.addDisplayMode(self._root, "Flat Lines")

        # Refresh geometry and force viewport redraw
        if hasattr(vp, "Object"):
            self.update_geometry(vp.Object)
            self.update_gcode(vp.Object)
        if self._root:
                self._root.touch()

    def update_geometry(self, fp) -> None:
        """Rebuild all Coin3D nodes from current fp dimensions."""
        self._ensure_attrs()
        if self._root is None:
            # Proxy instance mismatch — attach() ran on a different instance.
            # Re-attach using stored vp reference or fp.ViewObject.
            vp = self._vp or getattr( fp, "ViewObject", None )
            if vp is not None:
                self.attach( vp )
            if self._root is None:
                return

        try:
            w = float(fp.Width)
            d = float(fp.Depth)
            h = float(fp.Height)
            # App::PropertyLength returns mm; FreeCAD scene is also mm.
            # No scaling needed.
            ws      = w
            ds_     = d
            hs      = h
            spacing = _GRID_SPACING

        except Exception as e:
            Console.PrintWarning(f"BuildVolume geometry update error: {e}\n")
            return

        # Apply PrinterOffset via SoTransform — instant, no geometry rebuild
        ox = float( getattr( fp, "PrinterOffsetX", 0.0 ) )
        oy = float( getattr( fp, "PrinterOffsetY", 0.0 ) )
        
        if hasattr( self, "_offset_transform" ) and self._offset_transform:
            m  = fp.Proxy.get_printer_to_world( fp )
            b  = Base.Matrix()
            b.move( ox, oy, 0 )    
        
            r = m.multiply( b )
            sm = coin.SbMatrix()
            sm.setValue( [ [ r.A11, r.A21, r.A31, r.A41 ],
                           [ r.A12, r.A22, r.A32, r.A42 ],
                           [ r.A13, r.A23, r.A33, r.A43 ],
                           [ r.A14, r.A24, r.A34, r.A44 ] ] )

            self._offset_transform.matrix.setValue( sm )

        # --- Rebuild envelope (always at 0,0 — offset handled by SoTransform) ---
        self._rebuild_node(
            self._envelope_node,
            _make_lineset(
                _build_envelope_lines(ws, ds_, hs),
                _BOX_COLOR,
                _BOX_LINE_WIDTH,
            )
        )

        # --- Rebuild grid ---
        self._rebuild_node(
            self._grid_node,
            _make_lineset(
                _build_grid_lines(ws, ds_, spacing),
                _GRID_COLOR,
                _GRID_LINE_WIDTH,
            )
        )

        # --- Rebuild bed fill ---
        self._rebuild_node(
            self._bed_node,
            _make_quad(0, 0, ws, ds_, 0, _BED_COLOR, _BED_ALPHA)
        )

        # --- Rebuild axis indicator ---
        self._rebuild_node(
            self._axis_node,
            _build_axis_lines(_AXIS_LENGTH)
        )

        if self._root:
            self._root.touch()

    @staticmethod
    def _rebuild_node(parent: coin.SoSeparator, new_child: coin.SoNode) -> None:
        """Remove all existing children from parent and add new_child."""
        parent.removeAllChildren()
        parent.addChild(new_child)

    # ------------------------------------------------------------------
    # FreeCAD ViewProvider protocol

    def updateData(self, fp, prop: str) -> None:
        """Called when a document property changes."""
        if prop in ("Width", "Depth", "Height", "Placement",
                    "PrinterOffsetX", "PrinterOffsetY"):
            self.update_geometry(fp)
        gcode_props = {
            "ShowGCode", "GCodeLayer", "GCodeShowUpTo", "GCodeShowTravel",
            "GCodeColourMode", "GCodeOutputFile",
            "GCodeShowWallOuter","GCodeShowWallInner","GCodeShowFill",
            "GCodeShowSkin","GCodeShowSupport","GCodeShowSkirt",
            "GCodeShowPrimeTower",
        }
        if prop in gcode_props:
            self.update_gcode( fp )

    def getDisplayModes(self, vp) -> list[str]:
        return ["Wireframe", "Flat Lines"]

    def getDefaultDisplayMode(self) -> str:
        return "Flat Lines"

    def setDisplayMode(self, mode: str) -> str:
        return mode

    def onChanged(self, vp, prop: str) -> None:
        """Called when a ViewObject property changes."""
        pass

    def onDocumentRestored(self, vp) -> None:
        """Called after document restore — re-run attach if needed."""
        if self._root is None:
            self.attach( vp )

    def onObjectChanged(self, vp, prop: str) -> None:
        """Called by the object proxy when a data property changes."""
        # Geometry props — update wireframe box and grid
        if prop in ( "Width", "Depth", "Height", "Placement",
                     "PrinterOffsetX", "PrinterOffsetY" ):
            fp = getattr( vp, "Object", None )
            if fp:
                self.update_geometry( fp )
                if self._root:
                                self._root.touch() 

        gcode_props = {
            "ShowGCode", "GCodeLayer", "GCodeShowUpTo", "GCodeShowTravel",
            "GCodeColourMode", "GCodeOutputFile",
            "GCodeShowWallOuter","GCodeShowWallInner","GCodeShowFill",
            "GCodeShowSkin","GCodeShowSupport","GCodeShowSkirt",
            "GCodeShowPrimeTower",
        }
        if prop in gcode_props:
            fp = getattr( vp, "Object", None )
            if fp:
                self.update_gcode( fp )

    def getIcon(self) -> str:
        from Common import getIconPath
        return getIconPath( "Volume.svg" )

    def update_gcode( self, fp ) -> None:
        """Sync G-code renderer with current FP properties."""
        self._ensure_attrs()
        from Common import Log, LogLevel

        # Not ready yet — try to self-attach
        if self._root is None:
            vp = self._vp or getattr( fp, "ViewObject", None )
            if vp is not None:
                self.attach( vp )
            if self._root is None:
                return
        # Ensure mtime attr exists (objects created before this fix)
        if not hasattr( self, "_loaded_gcode_mtime" ):
            self._loaded_gcode_mtime = 0
        if self._gcode_renderer is None:
            try:
                from gcode_viewer.renderer import GCodeRenderer
                self._gcode_renderer = GCodeRenderer()
            except Exception as e:
                Log( LogLevel.warning,
                    f"[BuildVolume] Renderer init failed: {e}\n" )
                return
        if self._gcode_root is None:
            try:
                self._gcode_root = coin.SoSeparator()
                self._root.addChild( self._gcode_root )
            except Exception as e:
                Log( LogLevel.warning,
                    f"[BuildVolume] gcode_root init failed: {e}\n" )
                return

        show = getattr( fp, "ShowGCode", False )
        if not show:
            self._gcode_root.removeAllChildren()
            return

        gcode_path = getattr( fp, "GCodeOutputFile", "" )
        if not gcode_path:
            return

        from pathlib import Path as _Path
        if not _Path( gcode_path ).exists():
            return

        # Parse if file changed or modified on disk
        try:
            mtime = _Path( gcode_path ).stat().st_mtime
        except Exception:
            mtime = 0

        # Read offset and scale from BuildVolume properties
        # All lengths in mm — no scaling needed
        #off_x  = float( getattr( fp, "PrinterOffsetX",  0.0 ) )
        #off_y  = float( getattr( fp, "PrinterOffsetY",  0.0 ) )

        if gcode_path != self._loaded_gcode_path or mtime != self._loaded_gcode_mtime:
            try:
                from gcode_viewer.parser import parse
                from Common import Log, LogLevel
                name = _Path(gcode_path).name
                Log( LogLevel.info,
                    f"[BuildVolume] Parsing G-code: {name}\n" )
                gcode = parse( _Path( gcode_path ) )
                self._gcode_renderer.set_gcode( gcode )
                self._loaded_gcode_path  = gcode_path
                self._loaded_gcode_mtime = mtime
                n_lay = gcode.layer_count()
                Log( LogLevel.info,
                    f"[BuildVolume] {n_lay} layers loaded\n" )
            except Exception as e:
                from Common import Log, LogLevel
                Log( LogLevel.warning,
                    f"[BuildVolume] G-code parse failed: {e}\n" )
                return

        # Apply coordinate offset to renderer
        # G-code is in printer space; add offset to get back to Cura/world space
        self._gcode_renderer.set_offset( 0, 0 )

        # Sync renderer root — set_gcode() creates a new root each time
        self._gcode_root.removeAllChildren()
        renderer_root = self._gcode_renderer.get_root()
        if renderer_root is not None:
            self._gcode_root.addChild( renderer_root )
        else:
            from Common import Log, LogLevel
            Log( LogLevel.warning, "[BuildVolume] renderer root is None\n" )
            return

        # Colour mode
        mode_map = {"Feature":"feature","Speed":"speed","Extruder":"extruder"}
        mode = mode_map.get( getattr(fp,"GCodeColourMode","Feature"), "feature" )
        self._gcode_renderer.set_colour_mode( mode )

        # Travel
        self._gcode_renderer.set_show_travel(
            getattr( fp, "GCodeShowTravel", False ) )

        # Per-feature visibility
        feat_map = {
            "WallOuter":"WALL-OUTER", "WallInner":"WALL-INNER",
            "Fill":"FILL", "Skin":"SKIN", "Support":"SUPPORT",
            "Skirt":"SKIRT", "PrimeTower":"PRIME-TOWER",
        }
        for suffix, feat_name in feat_map.items():
            vis = getattr( fp, f"GCodeShow{suffix}", True )
            self._gcode_renderer.set_feature_visible( feat_name, vis )

        # Layer range — always call to force lazy geometry build
        n   = self._gcode_renderer._gcode.layer_count()               if self._gcode_renderer._gcode else 0
        cur = max( 0, min( getattr(fp,"GCodeLayer",0), n-1 ) )
        if n == 0:
            return
        if getattr( fp, "GCodeShowUpTo", True ):
            self._gcode_renderer.show_up_to_layer( cur )
        else:
            self._gcode_renderer.show_only_layer( cur )

        if self._root:
                self._root.touch()

    def claimChildren( self ):
        """Show assigned bodies as children in the model tree."""
        fp = getattr( self._vp, "Object", None )
        if fp is None:
            return []
        try:
            return list( getattr( fp, "AssignedBodies", None ) or [] )
        except Exception:
            return []

    def doubleClicked( self, vp ):
        """Open the Build Volume editor on double-click."""
        try:
            import FreeCADGui
            from ui.panels import BuildVolumePanel
            fp       = vp.Object
            from registry_object import get_registry
            registry = get_registry( fp.Document )
            panel    = BuildVolumePanel( fp, registry )
            FreeCADGui.Control.showDialog( panel )
        except Exception as e:
            import traceback
            from FreeCAD import Console
            Console.PrintError(
                f"[BuildVolume] doubleClicked failed: { e }\n"
                + traceback.format_exc()
            )
        return True

    def setEdit( self, vp, mode=0 ):
        return self.doubleClicked( vp )

    def unsetEdit( self, vp, mode=0 ):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def __getstate__( self ):
        return "BuildVolumeViewProvider"

    def __setstate__( self, state ):
        self._root               = None
        self._vp                 = None
        self._envelope_node      = None
        self._grid_node          = None
        self._bed_node           = None
        self._axis_node          = None
        self._gcode_root         = None
        self._gcode_renderer     = None
        self._loaded_gcode_path  = None
        self._loaded_gcode_mtime = 0
        self._offset_transform   = None
        self._attached           = False

    def _ensure_attrs( self ) -> None:
        """Guard against missing attrs when restored from old documents."""
        for attr, default in [
            ( "_root",               None  ),
            ( "_vp",                 None  ),
            ( "_envelope_node",      None  ),
            ( "_grid_node",          None  ),
            ( "_bed_node",           None  ),
            ( "_axis_node",          None  ),
            ( "_gcode_root",         None  ),
            ( "_gcode_renderer",     None  ),
            ( "_loaded_gcode_path",  None  ),
            ( "_loaded_gcode_mtime", 0     ),
            ( "_offset_transform",   None  ),
            ( "_attached",           False ),
            ( "_modes_registered",    False ),
        ]:
            if not hasattr( self, attr ):
                setattr( self, attr, default )
