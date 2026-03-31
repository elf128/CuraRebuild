#
# CuraRebuild post-processor: Filament Change
#
# Inserts M600 filament change commands at specified layers.
#
#   Copyright (c) 2026 — LGPL v2+

from __future__ import annotations
import re
from postprocess.base import PostProcessor


class FilamentChange( PostProcessor ):
    LABEL       = "Filament Change"
    DESCRIPTION = (
        "Insert M600 filament change at specified layers. "
        "The printer will pause, unload, wait for new filament, reload and resume."
    )
    SETTINGS    = {
        "layers": {
            "type":    "str",
            "default": "10",
            "label":   "Layer numbers (comma-separated)",
            "hint":    "e.g. 10,25,50",
        },
        "retract_mm": {
            "type":    "float",
            "default": 45.0,
            "min":     0.0,
            "label":   "Retract length (mm)",
            "hint":    "Distance to retract filament before change (E parameter)",
        },
        "x_pos": {
            "type":    "float",
            "default": 0.0,
            "label":   "Park X position (mm)",
        },
        "y_pos": {
            "type":    "float",
            "default": 0.0,
            "label":   "Park Y position (mm)",
        },
        "message": {
            "type":    "str",
            "default": "Filament change layer {layer}",
            "label":   "LCD message before change",
        },
    }

    _LAYER_RE = re.compile( r'^;LAYER:(\d+)', re.MULTILINE )

    def process( self, gcode: str, config: dict, context: dict ) -> str:
        try:
            target_layers = {
                int( s.strip() )
                for s in str( config.get( "layers", "10" ) ).split( "," )
                if s.strip().isdigit()
            }
        except Exception:
            target_layers = set()

        retract_mm = float( config.get( "retract_mm", 45.0 ) )
        x_pos      = float( config.get( "x_pos", 0.0 ) )
        y_pos      = float( config.get( "y_pos", 0.0 ) )
        message    = config.get( "message", "" ).strip()

        lines  = gcode.splitlines( keepends=True )
        result = []
        for line in lines:
            result.append( line )
            m = self._LAYER_RE.match( line )
            if m and int( m.group(1) ) in target_layers:
                layer = int( m.group(1) )
                cmds = []
                if message:
                    cmds.append( f"M117 {message.format( layer=layer )}\n" )
                # Build M600 command with parameters
                m600 = f"M600"
                if x_pos != 0:
                    m600 += f" X{x_pos:.1f}"
                if y_pos != 0:
                    m600 += f" Y{y_pos:.1f}"
                if retract_mm > 0:
                    m600 += f" E-{retract_mm:.1f}"
                cmds.append( f"{m600} ; Filament change at layer {layer}\n" )
                result.extend( cmds )
        return "".join( result )
