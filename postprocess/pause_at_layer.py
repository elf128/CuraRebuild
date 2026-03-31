#
# CuraRebuild post-processor: Pause at Layer
#
# Inserts a pause command at one or more specified layers.
#
#   Copyright (c) 2026 — LGPL v2+

from __future__ import annotations
import re
from postprocess.base import PostProcessor


class PauseAtLayer( PostProcessor ):
    LABEL       = "Pause at Layer"
    DESCRIPTION = (
        "Insert a pause command at specified layers. "
        "Useful for inserting magnets, nuts, colour changes, etc."
    )
    SETTINGS    = {
        "layers": {
            "type":    "str",
            "default": "10",
            "label":   "Layer numbers (comma-separated)",
            "hint":    "e.g. 10,25,50",
        },
        "command": {
            "type":    "str",
            "default": "M0",
            "label":   "Pause command",
            "hint":    "M0 = unconditional pause, M1 = conditional pause",
            "options": ["M0", "M1", "M25"],
        },
        "message": {
            "type":    "str",
            "default": "Paused at layer {layer}",
            "label":   "LCD message (M117, empty to skip)",
        },
        "retract_mm": {
            "type":    "float",
            "default": 1.0,
            "min":     0.0,
            "label":   "Retract before pause (mm, 0 = skip)",
        },
    }

    _LAYER_RE = re.compile( r'^;LAYER:(\d+)', re.MULTILINE )

    def process( self, gcode: str, config: dict, context: dict ) -> str:
        # Parse target layers
        try:
            target_layers = {
                int( s.strip() )
                for s in str( config.get( "layers", "10" ) ).split( "," )
                if s.strip().isdigit()
            }
        except Exception:
            target_layers = set()

        command    = config.get( "command", "M0" ).strip()
        message    = config.get( "message", "" ).strip()
        retract_mm = float( config.get( "retract_mm", 1.0 ) )

        lines  = gcode.splitlines( keepends=True )
        result = []
        for line in lines:
            result.append( line )
            m = self._LAYER_RE.match( line )
            if m and int( m.group(1) ) in target_layers:
                layer = int( m.group(1) )
                pause_cmds = []
                if message:
                    pause_cmds.append(
                        f"M117 {message.format( layer=layer )}\n" )
                if retract_mm > 0:
                    pause_cmds.append( f"G1 E-{retract_mm:.2f} F1500\n" )
                pause_cmds.append( f"{command} ; Pause at layer {layer}\n" )
                if retract_mm > 0:
                    pause_cmds.append( f"G1 E{retract_mm:.2f} F1500\n" )
                result.extend( pause_cmds )
        return "".join( result )
