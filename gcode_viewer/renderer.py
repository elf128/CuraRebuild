#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# renderer.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   Builds a Coin3D scene graph from a parsed GCodeFile.
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

if TYPE_CHECKING:
    from gcode_viewer.parser import GCodeFile, Layer, Move, Feature

try:
    from pivy import coin
    _COIN_OK = True
except ImportError:
    _COIN_OK = False


# Cylinder sides (6 = hexagonal prism, good balance of speed vs appearance)
_SIDES = 6

# Travel line width in scene units
_TRAVEL_WIDTH = 0.15


def _speed_colour( speed: float, min_s: float, max_s: float
                  ) -> tuple[float,float,float]:
    """Map speed to blue→cyan→green→yellow→red gradient."""
    if max_s <= min_s:
        return (0.0, 1.0, 0.0)
    t = max( 0.0, min( 1.0, (speed - min_s) / (max_s - min_s) ) )
    # 4-stop gradient: blue(0) → cyan(0.33) → green(0.5) → yellow(0.67) → red(1)
    if t < 0.25:
        r, g, b = 0.0, t*4, 1.0
    elif t < 0.5:
        r, g, b = 0.0, 1.0, 1.0 - (t-0.25)*4
    elif t < 0.75:
        r, g, b = (t-0.5)*4, 1.0, 0.0
    else:
        r, g, b = 1.0, 1.0 - (t-0.75)*4, 0.0
    return (r, g, b)


_EXTRUDER_COLOURS = [
    (0.2, 0.6, 1.0),   # blue
    (1.0, 0.5, 0.1),   # orange
    (0.3, 0.9, 0.3),   # green
    (0.9, 0.3, 0.9),   # magenta
]


def _extruder_colour( idx: int ) -> tuple[float,float,float]:
    return _EXTRUDER_COLOURS[ idx % len(_EXTRUDER_COLOURS) ]


def _cylinder_verts(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    radius: float,
    sides: int = _SIDES,
) -> tuple[list, list]:
    """
    Build vertices and triangle indices for a cylinder between two points.
    Returns (vertices, indices) where vertices is a flat list of (x,y,z)
    and indices is a list of triangle vertex index triples.
    """
    dx, dy, dz = x1-x0, y1-y0, z1-z0
    length = math.sqrt( dx*dx + dy*dy + dz*dz )
    if length < 1e-6:
        return [], []

    # Normalise axis
    ax, ay, az = dx/length, dy/length, dz/length

    # Find a perpendicular vector
    if abs(ax) < 0.9:
        px, py, pz = 1.0, 0.0, 0.0
    else:
        px, py, pz = 0.0, 1.0, 0.0

    # Cross product: axis × perp → u
    ux = ay*pz - az*py
    uy = az*px - ax*pz
    uz = ax*py - ay*px
    ul = math.sqrt( ux*ux + uy*uy + uz*uz )
    ux, uy, uz = ux/ul, uy/ul, uz/ul

    # Cross product: axis × u → v
    vx = ay*uz - az*uy
    vy = az*ux - ax*uz
    vz = ax*uy - ay*ux

    # Build ring of vertices at both ends.
    # Rotate by π/sides so flat faces align with the layer plane (Z axis).
    phase = math.pi / sides
    verts = []
    for end_x, end_y, end_z in ( (x0,y0,z0), (x1,y1,z1) ):
        for i in range( sides ):
            angle = 2 * math.pi * i / sides + phase
            c, s = math.cos(angle) * radius, math.sin(angle) * radius
            verts.append( (
                end_x + c*ux + s*vx,
                end_y + c*uy + s*vy,
                end_z + c*uz + s*vz,
            ) )

    # Triangles — side quads split into 2 triangles each
    tris = []
    for i in range( sides ):
        i0 = i
        i1 = (i+1) % sides
        i2 = i + sides
        i3 = i1 + sides
        tris.append( (i0, i2, i1) )
        tris.append( (i1, i2, i3) )

    # End caps (fan from centre)
    # Front cap
    fc = len(verts)
    verts.append( (x0, y0, z0) )
    for i in range( sides ):
        tris.append( (fc, i, (i+1)%sides) )

    # Back cap
    bc = len(verts)
    verts.append( (x1, y1, z1) )
    for i in range( sides ):
        tris.append( (bc, sides + (i+1)%sides, sides + i) )

    return verts, tris


def _make_geometry_node(
    moves: list,
    colour: tuple[float,float,float],
    min_s: float, max_s: float,
    colour_mode: str,     # "feature" | "speed" | "extruder"
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> "coin.SoSeparator | None":
    """Build a Coin3D separator with all geometry for a list of moves."""
    if not _COIN_OK or not moves:
        return None

    sep = coin.SoSeparator()

    # Collect all vertices and indices
    all_verts: list[tuple] = []
    all_tris:  list[tuple] = []

    for move in moves:
        if move.width < 0.01:
            continue   # travel handled separately

        r = move.width / 2.0

        if colour_mode == "speed":
            col = _speed_colour( move.speed, min_s, max_s )
        elif colour_mode == "extruder":
            col = _extruder_colour( move.extruder )
        else:
            col = colour   # feature colour passed in

        v, t = _cylinder_verts(
            move.x0 + offset_x, move.y0 + offset_y, move.z0,
            move.x1 + offset_x, move.y1 + offset_y, move.z1,
            radius=r,
        )
        if not v:
            continue

        base = len( all_verts )
        all_verts.extend( v )
        all_tris.extend( (a+base, b+base, c+base) for a,b,c in t )

    if not all_verts:
        return None

    # Per-move colour requires per-vertex colour — for simplicity, use
    # uniform colour per group (colour_mode==feature or extruder)
    # For speed mode, colour is per-move so we need per-vertex colours
    mat = coin.SoMaterial()
    r, g, b = colour
    mat.diffuseColor.setValue( coin.SbColor(r, g, b) )
    mat.ambientColor.setValue( coin.SbColor(r*0.3, g*0.3, b*0.3) )
    mat.specularColor.setValue( coin.SbColor(0.3, 0.3, 0.3) )
    mat.shininess.setValue( 0.3 )
    sep.addChild( mat )

    coords = coin.SoCoordinate3()
    coords.point.setValues( 0, len(all_verts),
                            [(x,y,z) for x,y,z in all_verts] )
    sep.addChild( coords )

    faces = coin.SoIndexedFaceSet()
    idx = []
    for a, b, c in all_tris:
        idx.extend( [a, b, c, -1] )
    faces.coordIndex.setValues( 0, len(idx), idx )
    sep.addChild( faces )

    return sep


def _make_travel_node(
    moves: list,
    colour: tuple[float,float,float],
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> "coin.SoSeparator | None":
    """Build thin lines for travel moves."""
    if not _COIN_OK or not moves:
        return None

    travel_moves = [ m for m in moves
                     if m.width < 0.01 and
                     ( (m.x1-m.x0)**2 + (m.y1-m.y0)**2 ) > 0.01 ]
    if not travel_moves:
        return None

    sep = coin.SoSeparator()

    mat = coin.SoMaterial()
    r, g, b = colour
    mat.diffuseColor.setValue( coin.SbColor(r, g, b) )
    mat.transparency.setValue( 0.5 )
    sep.addChild( mat )

    ds = coin.SoDrawStyle()
    ds.lineWidth = 0.5
    sep.addChild( ds )

    pts = []
    counts = []
    for m in travel_moves:
        pts.append( (m.x0 + offset_x, m.y0 + offset_y, m.z0) )
        pts.append( (m.x1 + offset_x, m.y1 + offset_y, m.z1) )
        counts.append( 2 )

    coords = coin.SoCoordinate3()
    coords.point.setValues( 0, len(pts), pts )
    sep.addChild( coords )

    lines = coin.SoLineSet()
    lines.numVertices.setValues( 0, len(counts), counts )
    sep.addChild( lines )

    return lines_sep if (lines_sep := sep) else None


class GCodeRenderer:
    """
    Manages the Coin3D scene for G-code visualisation.
    Lazy-builds layer geometry on first display.
    """

    def __init__( self ):
        self._root:        "coin.SoSeparator | None" = None
        self._layer_nodes: list["coin.SoSeparator"]  = []
        self._gcode:       "GCodeFile | None"        = None
        self._built_up_to: int                       = -1
        self._colour_mode: str                       = "feature"
        self._show_travel: bool                      = True
        self._feature_vis: dict[str,bool]            = {}
        self._offset_x:    float                     = 0.0
        self._offset_y:    float                     = 0.0

    def set_offset( self, x: float, y: float ) -> None:
        """
        Set the XY offset applied to all G-code coordinates for display.
        G-code is in printer space; adding the printer origin offset converts
        to Cura/world space.
        If offset changed, clear built geometry so it rebuilds with new coords.
        """
        if x != self._offset_x or y != self._offset_y:
            self._offset_x = x
            self._offset_y = y
            # Clear all built geometry — will rebuild lazily with new offset
            for switch, sep in self._layer_nodes:
                sep.removeAllChildren()

    def set_gcode( self, gcode: "GCodeFile" ) -> None:
        self._gcode       = gcode
        self._layer_nodes = []
        self._built_up_to = -1
        self._rebuild_root()

    def _rebuild_root( self ) -> None:
        if not _COIN_OK:
            return
        self._root = coin.SoSeparator()
        self._layer_nodes = []
        if self._gcode:
            for _ in self._gcode.layers:
                # SoSwitch lets us toggle layer visibility via whichChild
                switch = coin.SoSwitch()
                switch.whichChild = -3   # SO_SWITCH_NONE = hidden
                # Inner separator holds the actual geometry
                sep = coin.SoSeparator()
                switch.addChild( sep )
                self._root.addChild( switch )
                self._layer_nodes.append( ( switch, sep ) )

    def get_root( self ) -> "coin.SoSeparator | None":
        return self._root

    def set_colour_mode( self, mode: str ) -> None:
        """mode: 'feature' | 'speed' | 'extruder'"""
        self._colour_mode = mode
        # Clear built geometry so it gets rebuilt with new colours
        self._built_up_to = -1
        for switch, sep in self._layer_nodes:
            sep.removeAllChildren()
        self._show_range( self._last_range if hasattr(self,'_last_range') else (0,0) )

    def set_show_travel( self, show: bool ) -> None:
        self._show_travel = show

    def set_feature_visible( self, feature_name: str, visible: bool ) -> None:
        self._feature_vis[feature_name] = visible

    def show_up_to_layer( self, layer_idx: int ) -> None:
        """Show all layers 0..layer_idx."""
        self._last_range = (0, layer_idx)
        self._show_range( (0, layer_idx) )

    def show_only_layer( self, layer_idx: int ) -> None:
        """Show only layer_idx."""
        self._last_range = (layer_idx, layer_idx)
        self._show_range( (layer_idx, layer_idx) )

    def _show_range( self, rng: tuple[int,int] ) -> None:
        if not self._gcode or not self._layer_nodes:
            return
        lo, hi = rng
        for i, ( switch, sep ) in enumerate( self._layer_nodes ):
            if lo <= i <= hi:
                if sep.getNumChildren() == 0:
                    self._build_layer( i )
                switch.whichChild = -2   # SO_SWITCH_ALL = show all children
            else:
                switch.whichChild = -3   # SO_SWITCH_NONE = hidden

    def _build_layer( self, layer_idx: int ) -> None:
        """Lazily build Coin3D geometry for one layer."""
        if not self._gcode or layer_idx >= len( self._gcode.layers ):
            return
        layer          = self._gcode.layers[ layer_idx ]
        switch, node   = self._layer_nodes[ layer_idx ]
        min_s          = self._gcode.min_speed
        max_s          = self._gcode.max_speed

        from gcode_viewer.parser import Feature, FEATURE_COLOURS

        if self._colour_mode == "speed":
            # All extrusion moves in one group, coloured per-move by speed
            # For simplicity in speed mode: group by speed quantile
            _N_BUCKETS = 8
            buckets: dict[int, list] = {}
            for m in layer.moves:
                if m.width < 0.01:
                    continue
                bucket = int( (m.speed - min_s) / max( max_s - min_s, 0.001 ) * (_N_BUCKETS-1) )
                bucket = max(0, min(_N_BUCKETS-1, bucket))
                buckets.setdefault(bucket, []).append(m)
            for bucket, moves in buckets.items():
                t = bucket / (_N_BUCKETS - 1)
                col = _speed_colour( min_s + t*(max_s-min_s), min_s, max_s )
                geom = _make_geometry_node( moves, col, min_s, max_s, "feature",
                                            self._offset_x, self._offset_y )
                if geom:
                    node.addChild( geom )

        elif self._colour_mode == "extruder":
            from itertools import groupby
            sorted_moves = sorted(
                [m for m in layer.moves if m.width > 0.01],
                key=lambda m: m.extruder
            )
            for ext_idx, grp in groupby( sorted_moves, key=lambda m: m.extruder ):
                col  = _extruder_colour( ext_idx )
                geom = _make_geometry_node( list(grp), col, min_s, max_s, "extruder",
                                            self._offset_x, self._offset_y )
                if geom:
                    node.addChild( geom )

        else:  # feature mode
            from itertools import groupby
            sorted_moves = sorted(
                [m for m in layer.moves if m.width > 0.01],
                key=lambda m: m.feature.value
            )
            for feature, grp in groupby( sorted_moves, key=lambda m: m.feature ):
                feat_name = feature.value
                if not self._feature_vis.get( feat_name, True ):
                    continue
                col  = FEATURE_COLOURS.get( feature, (0.7, 0.7, 0.7) )
                geom = _make_geometry_node( list(grp), col, min_s, max_s, "feature",
                                            self._offset_x, self._offset_y )
                if geom:
                    node.addChild( geom )

        # Travel moves
        if self._show_travel:
            travel_col = (0.2, 0.2, 0.8)
            travel_node = _make_travel_node(
                layer.moves, travel_col,
                offset_x=self._offset_x, offset_y=self._offset_y
            )
            if travel_node:
                node.addChild( travel_node )
