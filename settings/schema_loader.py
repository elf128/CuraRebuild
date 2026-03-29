# settings/schema_loader.py
#
# Parse Cura's fdmprinter.def.json (and any inheriting definition files)
# into a flat dict of SettingDef objects.
#
# fdmprinter.def.json structure:
# {
#   "name": "FDM Printer",
#   "version": 2,
#   "metadata": { ... },
#   "settings": {
#     "<category_key>": {
#       "label": "...",
#       "type": "category",
#       "children": {
#         "<setting_key>": {
#           "label": "...",
#           "description": "...",
#           "type": "float|int|bool|str|enum|[list]",
#           "default_value": ...,
#           "unit": "...",
#           "minimum_value": ...,
#           "maximum_value": ...,
#           "options": { "value": "label", ... },   # for enum type
#           "enabled": "expression",
#           "value":   "expression",
#           "children": { ... }                      # nested settings
#         }
#       }
#     }
#   }
# }

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Common import Log, LogLevel


# ---------------------------------------------------------------------------
# Cura type → Python type mapping
# ---------------------------------------------------------------------------

_DTYPE_MAP = {
    "float":    float,
    "int":      int,
    "bool":     bool,
    "str":      str,
    "string":   str,
    "enum":     str,
    "extruder": int,
    "optional_extruder": int,
    "polygons": str,
    "polygon":  str,
    "[int]":    str,
    "[float]":  str,
    "category": None,   # categories are skipped
}


# ---------------------------------------------------------------------------
# SettingDef — extended version with expression fields
# ---------------------------------------------------------------------------
# We reuse the dataclass from schema.py but need to support the new fields.
# schema_loader returns plain dicts that schema.py converts to SettingDef.

def _parse_setting(
    key:      str,
    data:     dict,
    category: str,
) -> dict | None:
    """
    Parse one setting node from the def.json tree into a plain dict
    ready to be converted to a SettingDef.
    Returns None for category nodes or unknown types.
    """
    stype = data.get( "type", "str" )
    dtype = _DTYPE_MAP.get( stype )
    if dtype is None:
        return None   # category or unknown

    label       = str( data.get( "label",       key ) )
    description = str( data.get( "description", "" ) )
    unit        = str( data.get( "unit",        "" ) )
    default     = data.get( "default_value" )

    # Coerce default to dtype
    if default is not None:
        try:
            default = dtype( default )
        except (TypeError, ValueError):
            default = dtype()
    else:
        default = dtype()

    # Numeric bounds
    min_val = data.get( "minimum_value" )
    max_val = data.get( "maximum_value" )
    # Cura sometimes uses expressions for min/max — only keep plain numbers
    if min_val is not None:
        try:
            min_val = float( min_val )
        except (TypeError, ValueError):
            min_val = None
    if max_val is not None:
        try:
            max_val = float( max_val )
        except (TypeError, ValueError):
            max_val = None

    # Enum options → list of string values
    options = None
    if stype == "enum":
        raw_opts = data.get( "options", {} )
        if isinstance( raw_opts, dict ):
            options = list( raw_opts.keys() )

    # Expressions
    enabled_expr = data.get( "enabled" )
    value_expr   = data.get( "value" )

    # Normalize: Cura sometimes uses True/False (bool) for enabled
    if isinstance( enabled_expr, bool ):
        enabled_expr = str( enabled_expr ).lower()
    elif enabled_expr is not None:
        enabled_expr = str( enabled_expr )

    if value_expr is not None:
        value_expr = str( value_expr )

    return {
        "key":          key,
        "cura_key":     key,
        "label":        label,
        "category":     category,
        "home_layer":   None,   # assigned by schema.py heuristic
        "dtype":        dtype,
        "default":      default,
        "unit":         unit,
        "min_val":      min_val,
        "max_val":      max_val,
        "options":      options,
        "description":  description,
        "enabled_expr": enabled_expr,
        "value_expr":   value_expr,
    }


def _walk_settings(
    node:     dict,
    category: str,
    out:      dict,
    depth:    int = 0,
) -> None:
    """
    Recursively walk the settings tree.
    Updates `out` (key → parsed dict) in place.
    """
    for key, data in node.items():
        if not isinstance( data, dict ):
            continue

        stype = data.get( "type", "str" )

        if stype == "category":
            # Use the category label as the group name
            cat_label = str( data.get( "label", key ) )
            children  = data.get( "children", {} )
            if children:
                _walk_settings( children, cat_label, out, depth + 1 )
            continue

        parsed = _parse_setting( key, data, category )
        if parsed is not None:
            out[ key ] = parsed

        # Some settings have nested children (sub-settings)
        children = data.get( "children", {} )
        if children:
            _walk_settings( children, category, out, depth + 1 )


def load_def_json( path: Path | str ) -> dict[str, dict]:
    """
    Parse a Cura definition JSON file and return a flat dict of
    key → parsed-setting-dict for all settings found.

    Handles the 'inherits' chain: if the file inherits from another
    definition in the same directory, that parent is loaded first and
    the child's values override it.
    """
    path    = Path( path )
    visited = set()
    merged: dict[str, dict] = {}

    def _load( p: Path ) -> None:
        if p.name in visited:
            return
        visited.add( p.name )

        try:
            data = json.loads( p.read_text( encoding="utf-8" ) )
        except Exception as e:
            Log( LogLevel.error,
                f"[SchemaLoader] Could not read { p }: { e }\n" )
            return

        # Recurse into parent first
        parent_name = data.get( "inherits" )
        if parent_name:
            parent_path = p.parent / f"{ parent_name }.def.json"
            if parent_path.exists():
                _load( parent_path )

        # Walk settings tree
        _walk_settings( data.get( "settings", {} ), "General", merged )

        Log( LogLevel.debug,
            f"[SchemaLoader] Loaded { p.name }: "
            f"{ len( merged ) } settings total\n" )

    _load( path )
    Log( LogLevel.info,
        f"[SchemaLoader] Parsed { len( merged ) } settings "
        f"from { path.name }\n" )
    return merged


def default_def_json_path() -> Path:
    """Return the path to the bundled fdmprinter.def.json."""
    return Path( __file__ ).parent.parent / "data" / "fdmprinter.def.json"
