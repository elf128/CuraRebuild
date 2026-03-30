#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# schema.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   SettingDef dataclass and SchemaRegistry singleton.
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
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Layer position constants
# ---------------------------------------------------------------------------

class LayerRole(IntEnum):
    """Semantic role hints. Not enforced — purely for tooling and UI grouping."""
    MACHINE = 0
    USER    = 1   # any user-defined layer sits here conceptually
    OBJECT  = 99  # always the top of the stack


# ---------------------------------------------------------------------------
# Setting categories — used for UI panel grouping only
# ---------------------------------------------------------------------------

class Category:
    MACHINE         = "Machine"
    MATERIAL        = "Material"
    QUALITY         = "Quality"
    WALLS           = "Walls"
    TOP_BOTTOM      = "Top/Bottom"
    INFILL          = "Infill"
    SPEED           = "Speed"
    TRAVEL          = "Travel"
    COOLING         = "Cooling"
    SUPPORT         = "Support"
    ADHESION        = "Adhesion"
    GCODE           = "G-Code"
    EXPERIMENTAL    = "Experimental"


# ---------------------------------------------------------------------------
# SettingDef
# ---------------------------------------------------------------------------

@dataclass
class SettingDef:
    key:         str
    cura_key:    str
    label:       str
    category:    str
    home_layer:  LayerRole
    dtype:       type
    default:     Any
    unit:        str        = ""
    min_val:     Any        = None
    max_val:     Any        = None
    description:  str        = ""
    options:      list       = None   # valid string values → QComboBox
    enabled_expr: str | None = None   # Cura 'enabled' expression
    value_expr:   str | None = None   # Cura 'value' expression (auto-calculated)

    def __post_init__( self ):
        if self.options is None:
            object.__setattr__( self, "options", None )

    def validate(self, value: Any) -> Any:
        """Cast and clamp a value to this setting's type and range.
        Raises TypeError / ValueError on bad input."""
        try:
            v = self.dtype(value)
        except (TypeError, ValueError) as e:
            raise TypeError(
                f"Setting '{self.key}' expects {self.dtype.__name__}, "
                f"got {type(value).__name__}: {value}"
            ) from e
        if self.min_val is not None and v < self.dtype(self.min_val):
            raise ValueError(
                f"Setting '{self.key}' value {v} is below minimum {self.min_val}"
            )
        if self.max_val is not None and v > self.dtype(self.max_val):
            raise ValueError(
                f"Setting '{self.key}' value {v} is above maximum {self.max_val}"
            )
        return v

    def safe_validate(self, value: Any) -> Any:
        """Like validate() but clamps instead of raising on range violations."""
        try:
            v = self.dtype(value)
        except (TypeError, ValueError):
            return self.default
        if self.min_val is not None:
            v = max(self.dtype(self.min_val), v)
        if self.max_val is not None:
            v = min(self.dtype(self.max_val), v)
        return v


# ---------------------------------------------------------------------------
# Full setting declarations
# ---------------------------------------------------------------------------
#
# Organised by category. The home_layer is a hint:
#   LayerRole.MACHINE  — typically set once per printer
#   LayerRole.USER     — typically tuned per job / material / quality
#   LayerRole.OBJECT   — typically overridden per body
#
# All keys that CuraEngine uses are matched exactly in cura_key.
# Keys prefixed with "_fc_" are FreeCAD-only and are never exported to Cura.

def get(key: str) -> SettingDef:
    """Return the SettingDef for key from the live registry."""
    try:
        return _registry.schema[key]
    except KeyError:
        raise KeyError(f"Unknown setting key: '{key}'") from None


def get_default(key: str) -> Any:
    """Return the schema default for a key."""
    sdef = _registry.schema.get(key)
    return sdef.default if sdef else None


def all_keys() -> list[str]:
    return list( _registry.schema.keys() )


def exportable_keys() -> list[str]:
    """Keys that should be written to CuraEngine (excludes _fc_ keys)."""
    return [s.key for s in _registry.schema.values() if s.cura_key]


# ---------------------------------------------------------------------------
# SchemaRegistry
#
# Manages the active schema — loaded from fdmprinter.def.json.
# One singleton per process.
# ---------------------------------------------------------------------------

class SchemaRegistry:
    """
    Holds the active set of SettingDef objects and provides lookup helpers.
    Call load_from_def_json() to replace the schema with a parsed def file.
    """

    # FreeCAD-only settings not in fdmprinter.def.json
    _FC_SETTINGS: list = []   # populated by _make_fc_settings()

    def __init__( self ):
        self._schema:       dict[str, SettingDef] = {}
        self._cura_schema:  dict[str, SettingDef] = {}
        self._by_category:  dict[str, list[SettingDef]] = {}
        self._def_json_path: str = ""

    # ------------------------------------------------------------------
    # Loading

    def _load_from_list( self, settings_list: list[SettingDef] ) -> None:
        self._schema      = { s.key:      s for s in settings_list }
        self._cura_schema = { s.cura_key: s for s in settings_list if s.cura_key }
        self._by_category = {}
        for s in settings_list:
            self._by_category.setdefault( s.category, [] ).append( s )

    def load_from_def_json( self, path ) -> int:
        """
        Parse a Cura fdmprinter.def.json and replace the active schema.
        Returns the number of settings loaded.
        Raises on file-not-found or parse error.
        """
        from pathlib import Path as _Path
        from settings.schema_loader import load_def_json

        parsed = load_def_json( _Path( path ) )
        if not parsed:
            raise ValueError( f"No settings found in { path }" )

        # Convert parsed dicts to SettingDef objects
        # Assign home_layer heuristically based on category
        _machine_cats = { "Machine", "G-Code", "machine", "machine_settings" }

        new_settings = []
        for key, d in parsed.items():
            cat = d.get( "category", "General" )
            if d.get( "home_layer" ) is None:
                role = LayerRole.MACHINE if cat in _machine_cats else LayerRole.USER
            else:
                role = d[ "home_layer" ]

            sdef = SettingDef(
                key          = key,
                cura_key     = d.get( "cura_key", key ),
                label        = d.get( "label",    key ),
                category     = cat,
                home_layer   = role,
                dtype        = d.get( "dtype",    str ),
                default      = d.get( "default",  "" ),
                unit         = d.get( "unit",     "" ),
                min_val      = d.get( "min_val" ),
                max_val      = d.get( "max_val" ),
                options      = d.get( "options" ),
                description  = d.get( "description", "" ),
                enabled_expr = d.get( "enabled_expr" ),
                value_expr   = d.get( "value_expr" ),
            )
            new_settings.append( sdef )

        # Append FreeCAD-only settings that don't exist in fdmprinter.def.json
        fc_only = [
            SettingDef(
                key         = "_fc_unit_scale",
                cura_key    = "",
                label       = "Document Unit Scale",
                category    = Category.MACHINE,
                home_layer  = LayerRole.MACHINE,
                dtype       = float,
                default     = 1.0,
                description = (
                    "Multiply FreeCAD document units by this factor to get mm. "
                    "e.g. 0.001 if the document is in micrometres. "
                    "Never written to CuraEngine."
                ),
            ),
        ]
        self._load_from_list( new_settings + fc_only )
        self._def_json_path = str( path )
        return len( new_settings )

    # ------------------------------------------------------------------
    # Accessors

    @property
    def schema( self ) -> dict[str, SettingDef]:
        return self._schema

    @property
    def cura_schema( self ) -> dict[str, SettingDef]:
        return self._cura_schema

    @property
    def by_category( self ) -> dict[str, list[SettingDef]]:
        return self._by_category

    @property
    def def_json_path( self ) -> str:
        return self._def_json_path

    def get( self, key: str ) -> SettingDef:
        try:
            return self._schema[ key ]
        except KeyError:
            raise KeyError( f"Unknown setting key: '{ key }'" ) from None

    def all_keys( self ) -> list[str]:
        return list( self._schema.keys() )

    def exportable_keys( self ) -> list[str]:
        return [ s.key for s in self._schema.values() if s.cura_key ]

    def get_default( self, key: str ) -> Any:
        return self.get( key ).default

    def get_dependencies( self, key: str ) -> list[str]:
        """
        Return all setting keys that the given key's expressions reference.
        Uses expr_eval.extract_dependencies().
        """
        from settings.expr_eval import extract_dependencies
        sdef = self._schema.get( key )
        if sdef is None:
            return []
        deps = set()
        deps.update( extract_dependencies( sdef.enabled_expr ) )
        deps.update( extract_dependencies( sdef.value_expr ) )
        return [ k for k in deps if k in self._schema ]

    def get_dependents( self, key: str ) -> list[str]:
        """
        Return all setting keys whose expressions reference the given key.
        (Reverse dependency lookup.)
        """
        result = []
        for k, sdef in self._schema.items():
            if k == key:
                continue
            from settings.expr_eval import extract_dependencies
            deps = extract_dependencies( sdef.enabled_expr )
            deps += extract_dependencies( sdef.value_expr )
            if key in deps:
                result.append( k )
        return result


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------

_registry = SchemaRegistry()

# Try to load bundled def.json at import time
def _try_load_bundled() -> None:
    from pathlib import Path
    bundled = Path( __file__ ).parent.parent / "data" / "fdmprinter.def.json"
    if bundled.exists():
        try:
            n = _registry.load_from_def_json( bundled )
            from Common import Log, LogLevel
            Log( LogLevel.info,
                f"[Schema] Loaded { n } settings from bundled fdmprinter.def.json\n" )
        except Exception as e:
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[Schema] Could not load bundled def.json: { e }\n" )

_try_load_bundled()


def get_registry() -> SchemaRegistry:
    """Return the module-level SchemaRegistry singleton."""
    return _registry