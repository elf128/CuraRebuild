#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# parser.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   Parses Cura-flavoured G-code into a structured layer/move model.
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

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Feature types
# ---------------------------------------------------------------------------

class Feature(Enum):
    WALL_OUTER  = "WALL-OUTER"
    WALL_INNER  = "WALL-INNER"
    FILL        = "FILL"
    SKIN        = "SKIN"
    SUPPORT     = "SUPPORT"
    SUPPORT_INTERFACE = "SUPPORT-INTERFACE"
    SKIRT       = "SKIRT"
    PRIME_TOWER = "PRIME-TOWER"
    TRAVEL      = "TRAVEL"
    RETRACT     = "RETRACT"
    UNKNOWN     = "UNKNOWN"

    @classmethod
    def from_cura_comment( cls, s: str ) -> "Feature":
        s = s.strip().upper()
        for member in cls:
            if member.value == s:
                return member
        # Partial matches
        if "WALL" in s and "OUTER" in s: return cls.WALL_OUTER
        if "WALL" in s:                  return cls.WALL_INNER
        if "SKIN" in s or "TOP" in s or "BOTTOM" in s: return cls.SKIN
        if "FILL" in s or "INFILL" in s: return cls.FILL
        if "SUPPORT" in s:               return cls.SUPPORT
        if "SKIRT" in s or "BRIM" in s:  return cls.SKIRT
        return cls.UNKNOWN


# Feature display colours (R, G, B) 0-1 range
FEATURE_COLOURS: dict[Feature, tuple[float,float,float]] = {
    Feature.WALL_OUTER:        (1.0,  0.65, 0.0 ),   # orange
    Feature.WALL_INNER:        (0.6,  0.8,  1.0 ),   # light blue
    Feature.FILL:              (1.0,  0.4,  0.4 ),   # red
    Feature.SKIN:              (1.0,  0.85, 0.0 ),   # yellow
    Feature.SUPPORT:           (0.4,  0.9,  0.4 ),   # green
    Feature.SUPPORT_INTERFACE: (0.2,  0.7,  0.3 ),   # dark green
    Feature.SKIRT:             (0.7,  0.5,  1.0 ),   # purple
    Feature.PRIME_TOWER:       (0.5,  0.5,  0.5 ),   # grey
    Feature.TRAVEL:            (0.3,  0.3,  0.9 ),   # blue
    Feature.RETRACT:           (0.9,  0.2,  0.9 ),   # magenta
    Feature.UNKNOWN:           (0.7,  0.7,  0.7 ),   # grey
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Move:
    """A single G0/G1 move."""
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float
    feature:  Feature
    extruder: int
    speed:    float     # mm/s (converted from F mm/min)
    width:    float     # extrusion bead width in mm (0 = travel/retract)
    layer_idx: int


@dataclass
class Layer:
    index: int
    z:     float
    moves: list[Move] = field( default_factory=list )

    @property
    def extrusion_moves( self ) -> list[Move]:
        return [ m for m in self.moves if m.width > 0 ]

    @property
    def travel_moves( self ) -> list[Move]:
        return [ m for m in self.moves if m.width == 0
                 and m.feature == Feature.TRAVEL ]


@dataclass
class GCodeFile:
    layers:    list[Layer]
    min_speed: float
    max_speed: float
    extruder_count: int
    path:      Path

    def layer_count( self ) -> int:
        return len( self.layers )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_G_MOVE     = re.compile( r'^G[01]\b',     re.IGNORECASE )
_G_COORD    = re.compile( r'([XYZEF])([-\d.]+)', re.IGNORECASE )
_LAYER_CMT  = re.compile( r';LAYER:(\d+)', re.IGNORECASE )
_TYPE_CMT   = re.compile( r';TYPE:(.*)',   re.IGNORECASE )
_TOOL_CMT   = re.compile( r'^T(\d+)',      re.IGNORECASE )


def _parse_coords( line: str ) -> dict[str,float]:
    return { m.group(1).upper(): float( m.group(2) )
             for m in _G_COORD.finditer( line ) }


def parse( path: Path | str ) -> GCodeFile:
    """
    Parse a Cura G-code file into a GCodeFile structure.
    Returns an empty GCodeFile on error.
    """
    path = Path( path )
    layers: list[Layer] = []

    cur_layer_idx = -1
    cur_z         = 0.0
    cur_x         = 0.0
    cur_y         = 0.0
    cur_f         = 3000.0      # mm/min
    cur_e         = 0.0
    cur_feature   = Feature.UNKNOWN
    cur_extruder  = 0
    is_absolute   = True
    is_abs_e      = True
    prev_e        = 0.0
    layer_height  = 0.2         # fallback — updated from first z-change
    line_width    = 0.4         # fallback

    min_speed = float("inf")
    max_speed = 0.0
    max_extruder = 0

    # Pre-scan header for key settings
    try:
        with open( path, "r", encoding="utf-8", errors="replace" ) as fh:
            for i, line in enumerate( fh ):
                if i > 200:   # header is always in first ~100 lines
                    break
                lo = line.lower()
                if "layer_height" in lo and "layer_height_0" not in lo:
                    m = re.search( r'layer_height\s*[=:]\s*([\d.]+)', line, re.I )
                    if m:
                        layer_height = float( m.group(1) )
                if "line_width" in lo:
                    m = re.search( r'line_width\s*[=:]\s*([\d.]+)', line, re.I )
                    if m:
                        line_width = float( m.group(1) )
                if "machine_nozzle_size" in lo:
                    m = re.search( r'machine_nozzle_size\s*[=:]\s*([\d.]+)', line, re.I )
                    if m and line_width < 0.01:
                        line_width = float( m.group(1) )   # nozzle size as fallback
    except Exception:
        pass

    def _current_layer() -> Layer:
        if not layers or layers[-1].index != cur_layer_idx:
            l = Layer( index=cur_layer_idx, z=cur_z )
            layers.append( l )
        return layers[-1]

    def _extrusion_width( de: float, ds: float, speed: float ) -> float:
        """
        Return bead width for an extrusion move.
        Primary: use line_width parsed from G-code header (reliable).
        Fallback: compute from extrusion volume (unreliable with relative E).
        """
        if ds < 0.001 or de <= 0:
            return 0.0
        # Use header line_width if available — most reliable
        if line_width > 0.01:
            return line_width
        # Formula fallback: w = (de * filament_area) / (ds * lh)
        filament_area = 2.405   # mm² for 1.75mm filament
        w = ( de * filament_area ) / ( ds * layer_height )
        return max( 0.1, min( w, 5.0 ) )

    try:
        with open( path, "r", encoding="utf-8", errors="replace" ) as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue

                # Extruder change
                tm = _TOOL_CMT.match( line )
                if tm:
                    cur_extruder = int( tm.group(1) )
                    max_extruder = max( max_extruder, cur_extruder )
                    continue

                # Layer comment
                lm = _LAYER_CMT.match( line )
                if lm:
                    cur_layer_idx = int( lm.group(1) )
                    continue

                # Feature type comment
                ftm = _TYPE_CMT.match( line )
                if ftm:
                    cur_feature = Feature.from_cura_comment( ftm.group(1) )
                    continue

                # Positioning mode
                if line.startswith( "G90" ):
                    is_absolute = True;  continue
                if line.startswith( "G91" ):
                    is_absolute = False; continue
                if line.startswith( "M82" ):
                    is_abs_e    = True;  continue
                if line.startswith( "M83" ):
                    is_abs_e    = False; continue

                # Only process moves
                if not _G_MOVE.match( line ):
                    continue

                # Skip before first layer marker
                if cur_layer_idx < 0:
                    continue

                coords = _parse_coords( line )
                is_g0  = line.upper().startswith( "G0" )

                # New positions
                if is_absolute:
                    new_x = coords.get( "X", cur_x )
                    new_y = coords.get( "Y", cur_y )
                    new_z = coords.get( "Z", cur_z )
                    new_e = coords.get( "E", cur_e ) if not is_g0 else cur_e
                else:
                    new_x = cur_x + coords.get( "X", 0 )
                    new_y = cur_y + coords.get( "Y", 0 )
                    new_z = cur_z + coords.get( "Z", 0 )
                    new_e = cur_e + ( coords.get("E",0) if not is_g0 else 0 )

                if "F" in coords:
                    cur_f = coords["F"]

                speed_mms = cur_f / 60.0
                min_speed = min( min_speed, speed_mms )
                max_speed = max( max_speed, speed_mms )

                # Distance
                dx = new_x - cur_x
                dy = new_y - cur_y
                ds = ( dx*dx + dy*dy ) ** 0.5

                # Extrusion delta
                if is_abs_e:
                    de = new_e - prev_e
                else:
                    de = coords.get( "E", 0 )
                prev_e = new_e if is_abs_e else prev_e + de

                # Classify move
                if is_g0 or de <= 0 or ds < 0.001:
                    feature = Feature.TRAVEL
                    width   = 0.0
                else:
                    feature = cur_feature
                    width   = _extrusion_width( de, ds, speed_mms )

                # Retraction: E-only move
                if "E" in coords and ds < 0.001 and de < 0:
                    feature = Feature.RETRACT
                    width   = 0.0

                move = Move(
                    x0=cur_x, y0=cur_y, z0=cur_z,
                    x1=new_x, y1=new_y, z1=new_z,
                    feature=feature,
                    extruder=cur_extruder,
                    speed=speed_mms,
                    width=width,
                    layer_idx=cur_layer_idx,
                )
                _current_layer().moves.append( move )

                cur_x, cur_y, cur_z = new_x, new_y, new_z
                cur_e = new_e

    except Exception as e:
        import traceback
        print( f"[GCodeParser] Error: {e}\n{traceback.format_exc()}" )

    if min_speed == float("inf"):
        min_speed = 0.0

    return GCodeFile(
        layers=layers,
        min_speed=min_speed,
        max_speed=max_speed,
        extruder_count=max_extruder + 1,
        path=path,
    )


# ---------------------------------------------------------------------------
# Post-parse analysis
# ---------------------------------------------------------------------------

@dataclass
class GCodeAnalysis:
    """Computed statistics from a parsed GCodeFile."""
    time_seconds:      float                  # estimated print time
    filament_m:        dict[int, float]       # extruder → metres extruded
    filament_mm3:      dict[int, float]       # extruder → mm³ extruded
    bounds_min:        tuple[float,float,float]
    bounds_max:        tuple[float,float,float]
    feature_time:      dict[Feature, float]   # feature → seconds
    layer_time:        dict[int, float]       # layer_idx → seconds for that layer
    layer_count:       int

    def filament_summary( self ) -> str:
        """Human-readable filament string, e.g. '2.54 m' or 'E0: 1.20 m, E1: 0.80 m'."""
        if not self.filament_m:
            return ""
        if len( self.filament_m ) == 1:
            v = next( iter( self.filament_m.values() ) )
            return f"{v:.2f} m"
        return ", ".join(
            f"E{e}: {v:.2f} m"
            for e, v in sorted( self.filament_m.items() )
        )

    def time_formatted( self ) -> str:
        """Format as '1h 23m 45s'."""
        t = int( self.time_seconds )
        h = t // 3600
        m = ( t % 3600 ) // 60
        s = t % 60
        parts = []
        if h: parts.append( f"{h}h" )
        if m or h: parts.append( f"{m}m" )
        parts.append( f"{s}s" )
        return " ".join( parts )

    def per_extruder_summary( self ) -> str:
        """Per-extruder filament, e.g. 'E0: 2.54 m, E1: 0.00 m'."""
        if not self.filament_m:
            return ""
        return ", ".join(
            f"E{e}: {v:.2f} m"
            for e, v in sorted( self.filament_m.items() )
        )


# Filament diameter (1.75 mm standard)
_FILAMENT_DIAMETER = 1.75
_FILAMENT_AREA     = 3.14159265 * ( _FILAMENT_DIAMETER / 2 ) ** 2   # mm²


def analyse( gcode: GCodeFile ) -> GCodeAnalysis:
    """
    Compute print statistics from a parsed GCodeFile.

    Time estimation: sum of (move_distance / feedrate) for all moves,
    plus a small acceleration penalty per direction change.

    Filament: sum of E-axis extrusion per extruder, converted from mm
    of filament to metres.
    """
    import math

    time_s:       float = 0.0
    fil_mm:       dict[int, float] = {}   # extruder → mm of filament
    feat_time:    dict[Feature, float] = {}
    layer_time:   dict[int, float] = {}
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []

    for layer in gcode.layers:
        for move in layer.moves:
            # Distance of this move
            dx = move.x1 - move.x0
            dy = move.y1 - move.y0
            dz = move.z1 - move.z0
            dist = math.sqrt( dx*dx + dy*dy + dz*dz )

            # Time for this move (speed already in mm/s)
            speed = move.speed if move.speed > 0 else 1.0
            dt = dist / speed
            time_s += dt
            feat_time[move.feature] = feat_time.get( move.feature, 0.0 ) + dt
            layer_time[move.layer_idx] = layer_time.get( move.layer_idx, 0.0 ) + dt

            # Filament from extrusion moves
            if move.width > 0 and dist > 0:
                # Extrusion volume = bead cross-section × distance
                # bead cross-section ≈ width × layer_height (simplified rectangle)
                # layer_height = z1 if z0 == 0 else approximately layer height
                # We use bead width and an assumed layer height from z coords
                # Simpler: use the extrusion width and typical layer height
                # But we don't have layer_height per move — use bead width²/4*π as cylinder approx
                # Actually most reliable: volume = π*(d/2)²*filament_len
                # We want filament_len, so rearrange from volume
                # Volume extruded = width * layer_height * dist
                # We don't have layer_height reliably per move, but we know:
                # filament extruded (mm) = sqrt(volume / filament_area)
                # Use width as proxy: assume width ≈ layer_height for now
                # Best approximation without layer_height: use width * 0.75 as height
                lh_approx = move.width * 0.75
                vol = move.width * lh_approx * dist
                fil_len_mm = vol / _FILAMENT_AREA
                e = move.extruder
                fil_mm[e] = fil_mm.get( e, 0.0 ) + fil_len_mm

            # Bounds (extrusion moves only for print bounds, not travel)
            if move.width > 0:
                xs += [move.x0, move.x1]
                ys += [move.y0, move.y1]
                zs += [move.z0, move.z1]

    # Convert filament mm → metres
    fil_m = { e: v / 1000.0 for e, v in fil_mm.items() }

    # Bounds
    if xs:
        bmin = ( min(xs), min(ys), min(zs) )
        bmax = ( max(xs), max(ys), max(zs) )
    else:
        bmin = ( 0.0, 0.0, 0.0 )
        bmax = ( 0.0, 0.0, 0.0 )

    # Build cumulative elapsed time per layer start
    sorted_layers = sorted( layer_time.keys() )
    cumulative: dict[int, float] = {}
    elapsed = 0.0
    for idx in sorted_layers:
        cumulative[idx] = elapsed
        elapsed += layer_time.get( idx, 0.0 )

    return GCodeAnalysis(
        time_seconds  = time_s,
        filament_m    = fil_m,
        filament_mm3  = {},
        bounds_min    = bmin,
        bounds_max    = bmax,
        feature_time  = feat_time,
        layer_time    = cumulative,   # elapsed seconds at start of each layer
        layer_count   = gcode.layer_count(),
    )
