#
# CuraRebuild post-processor: Display Progress
#
# Injects M117 messages at each layer to show progress on the printer LCD.
#
#   Copyright (c) 2026 — LGPL v2+

from __future__ import annotations
import re
from postprocess.base import PostProcessor


def _fmt_time( seconds: float ) -> str:
    """Format seconds as 'Hh Mm' or 'Mm Ss'."""
    s = int( seconds )
    h = s // 3600
    m = ( s % 3600 ) // 60
    s = s % 60
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class DisplayProgress( PostProcessor ):
    LABEL       = "Display Progress"
    DESCRIPTION = "Show print progress on the printer LCD using M117."
    SETTINGS    = {
        "format": {
            "type":    "str",
            "default": "{elapsed} / {total_time} ({pct}%)",
            "label":   "Message format",
            "hint":    (
                "Variables: {layer}, {total}, {pct}, "
                "{elapsed}, {remaining}, {total_time}"
            ),
        },
        "every_n": {
            "type":    "int",
            "default": 1,
            "min":     1,
            "label":   "Every N layers",
        },
    }

    _LAYER_RE = re.compile( r'^;LAYER:(\d+)', re.MULTILINE )

    def process( self, gcode: str, config: dict, context: dict ) -> str:
        fmt        = config.get( "format", self.SETTINGS["format"]["default"] )
        every_n    = max( 1, int( config.get( "every_n", 1 ) ) )
        total      = context.get( "layer_count", 0 )
        total_s    = context.get( "total_time_s", 0.0 )
        layer_time = context.get( "layer_time", {} )  # layer_idx → elapsed s

        lines  = gcode.splitlines( keepends=True )
        result = []
        for line in lines:
            result.append( line )
            m = self._LAYER_RE.match( line )
            if m:
                layer = int( m.group(1) )
                if layer % every_n == 0:
                    pct       = int( 100 * layer / total ) if total else 0
                    elapsed_s = layer_time.get( layer, 0.0 )
                    remain_s  = total_s - elapsed_s

                    msg = fmt.format(
                        layer      = layer,
                        total      = total,
                        pct        = pct,
                        elapsed    = _fmt_time( elapsed_s ),
                        remaining  = _fmt_time( remain_s ),
                        total_time = _fmt_time( total_s ),
                    )
                    result.append( f"M117 {msg}\n" )
        return "".join( result )
