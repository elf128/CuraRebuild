#
# CuraRebuild post-processor: Settings Dump
#
# Appends all effective slice settings as ;key=value comments at the
# end of the G-code. Allows reimporting settings from a sliced file.
#
#   Copyright (c) 2026 — LGPL v2+

from __future__ import annotations
from postprocess.base import PostProcessor


class SettingsDump( PostProcessor ):
    LABEL       = "Settings Dump"
    DESCRIPTION = (
        "Append all effective slice settings as ;key=value comments "
        "at the end of the G-code. Allows reimporting settings later."
    )
    SETTINGS    = {
        "header": {
            "type":    "str",
            "default": "CuraRebuild Settings",
            "label":   "Section header label",
        },
        "include_schema_defaults": {
            "type":    "bool",
            "default": False,
            "label":   "Include schema defaults (very verbose)",
        },
    }

    def process( self, gcode: str, config: dict, context: dict ) -> str:
        header   = config.get( "header", "CuraRebuild Settings" )
        settings = context.get( "effective_settings", {} )

        if not settings:
            return gcode

        lines = [
            f"\n;--- {header} ---",
        ]
        for k, v in sorted( settings.items() ):
            lines.append( f";{k}={v}" )
        lines.append( f";--- End {header} ---\n" )

        return gcode + "\n".join( lines )
