#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# postprocess/base.py — Post-processor base class and pipeline runner
#
#   Copyright (c) 2026
#   License: LGPL v2+

from __future__ import annotations
import importlib
import importlib.util
import json
import pathlib
from typing import Any


class PostProcessor:
    """
    Base class for all post-processors.
    Subclass and implement process() + define LABEL, DESCRIPTION, SETTINGS.
    """
    LABEL:       str  = "Unnamed Post-Processor"
    DESCRIPTION: str  = ""
    # SETTINGS dict: key → {type, default, label, [min, max, options]}
    SETTINGS:    dict = {}

    def process( self, gcode: str, config: dict, context: dict ) -> str:
        """
        Transform G-code. Return modified G-code string.

        config  — user-configured values for this instance (key → value)
        context — slice context: {layer_count, layer_height, ...}
        """
        raise NotImplementedError


def _default_config( processor_cls ) -> dict:
    """Return a config dict populated with defaults from SETTINGS."""
    return {
        k: v.get( "default" )
        for k, v in processor_cls.SETTINGS.items()
    }


def discover_scripts( postprocess_dir: pathlib.Path ) -> dict[str, type]:
    """
    Scan postprocess_dir for .py files (excluding __init__ and base).
    Returns dict of script_name → PostProcessor subclass.
    """
    scripts: dict[str, type] = {}
    if not postprocess_dir.exists():
        return scripts

    for path in sorted( postprocess_dir.glob( "*.py" ) ):
        if path.stem in ( "__init__", "base" ):
            continue
        try:
            spec   = importlib.util.spec_from_file_location( path.stem, path )
            module = importlib.util.module_from_spec( spec )
            spec.loader.exec_module( module )
            for name in dir( module ):
                obj = getattr( module, name )
                if ( isinstance( obj, type )
                     and issubclass( obj, PostProcessor )
                     and obj is not PostProcessor ):
                    scripts[ path.stem ] = obj
                    break
        except Exception as e:
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[PostProcess] Could not load '{path.name}': {e}\n" )
    return scripts


def run_pipeline(
    gcode:        str,
    pipeline:     list[dict],
    postprocess_dir: pathlib.Path,
    context:      dict | None = None,
) -> str:
    """
    Run a list of post-processor configs against G-code in order.

    pipeline entries: {"script": str, "enabled": bool, "config": dict}
    Returns final G-code string.
    """
    scripts = discover_scripts( postprocess_dir )
    context = context or {}

    for entry in pipeline:
        if not entry.get( "enabled", True ):
            continue
        script_name = entry.get( "script", "" )
        cls = scripts.get( script_name )
        if cls is None:
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[PostProcess] Script '{script_name}' not found — skipping\n" )
            continue
        try:
            cfg   = { **_default_config(cls), **entry.get( "config", {} ) }
            proc  = cls()
            gcode = proc.process( gcode, cfg, context )
            from Common import Log, LogLevel
            Log( LogLevel.info,
                f"[PostProcess] Applied '{cls.LABEL}'\n" )
        except Exception as e:
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[PostProcess] '{script_name}' failed: {e}\n" )

    return gcode


def postprocess_dir() -> pathlib.Path:
    """Return the postprocess directory inside the CuraRebuild mod."""
    return pathlib.Path( __file__ ).parent
