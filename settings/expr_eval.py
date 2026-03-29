#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# expr_eval.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   Evaluates Cura enabled/value expressions.
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
import re
from typing import Any

from Common import Log, LogLevel


# ---------------------------------------------------------------------------
# Stub helpers that Cura expressions may call
# ---------------------------------------------------------------------------

def _make_builtins( effective: dict[str, Any] ) -> dict:
    """Build the eval namespace for a given effective settings dict."""

    def resolveOrValue( key: str ) -> Any:
        return effective.get( key, 0 )

    def extruderValue( extruder_nr: int, key: str ) -> Any:
        return effective.get( key, 0 )

    def extruderValues( key: str ) -> list:
        return [ effective.get( key, 0 ) ]

    def defaultExtruderPosition() -> int:
        return 0

    def anyExtruder( extruder_nr: int, key: str, value: Any ) -> bool:
        return effective.get( key ) == value

    def valueFromContainer( index: int, key: str ) -> Any:
        return effective.get( key, 0 )

    def valueFromExtruderIndex( index: int, key: str ) -> Any:
        return effective.get( key, 0 )

    return {
        # Cura helpers
        "resolveOrValue":           resolveOrValue,
        "extruderValue":            extruderValue,
        "extruderValues":           extruderValues,
        "defaultExtruderPosition":  defaultExtruderPosition,
        "anyExtruder":              anyExtruder,
        "valueFromContainer":       valueFromContainer,
        "valueFromExtruderIndex":   valueFromExtruderIndex,
        # Math builtins Cura expressions use
        "math":  math,
        "round": round,
        "min":   min,
        "max":   max,
        "abs":   abs,
        "int":   int,
        "float": float,
        "bool":  bool,
        "str":   str,
        "len":   len,
        "True":  True,
        "False": False,
        "None":  None,
    }


# ---------------------------------------------------------------------------
# Expression cache — avoid re-compiling the same expression repeatedly
# ---------------------------------------------------------------------------

_compile_cache: dict[str, Any] = {}

def _compile( expr: str ):
    if expr not in _compile_cache:
        try:
            _compile_cache[ expr ] = compile( expr, "<cura_expr>", "eval" )
        except SyntaxError:
            _compile_cache[ expr ] = None
    return _compile_cache[ expr ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def eval_enabled(
    expr:      str | None,
    effective: dict[str, Any],
) -> bool:
    """
    Evaluate an `enabled` expression.
    Returns True if the setting should be shown/enabled, False if it should
    be greyed out. Returns True if expr is None (no condition = always enabled).
    """
    if expr is None:
        return True
    if expr.lower() in ( "true", "1" ):
        return True
    if expr.lower() in ( "false", "0" ):
        return False

    code = _compile( expr )
    if code is None:
        return True   # bad expression — show by default

    ns = dict( effective )
    ns.update( _make_builtins( effective ) )

    try:
        result = eval( code, { "__builtins__": {} }, ns )  # noqa: S307
        return bool( result )
    except NameError:
        return True   # unknown key → assume enabled (safe default, no log spam)
    except Exception as e:
        Log( LogLevel.debug,
            f"[ExprEval] enabled expr failed: { expr!r }: { e }\n" )
        return True


def eval_value(
    expr:      str | None,
    effective: dict[str, Any],
    dtype:     type = float,
) -> Any | None:
    """
    Evaluate a `value` expression.
    Returns the computed value cast to dtype, or None if expr is None
    or evaluation fails.
    """
    if expr is None:
        return None

    # Plain literal — return immediately
    try:
        return dtype( expr )
    except (TypeError, ValueError):
        pass

    code = _compile( expr )
    if code is None:
        return None

    ns = dict( effective )
    ns.update( _make_builtins( effective ) )

    try:
        result = eval( code, { "__builtins__": {} }, ns )  # noqa: S307
        if result is None:
            return None
        return dtype( result )
    except NameError:
        return None   # unknown key → can't compute, no log spam
    except Exception as e:
        Log( LogLevel.debug,
            f"[ExprEval] value expr failed: { expr!r }: { e }\n" )
        return None


def extract_dependencies( expr: str | None ) -> list[str]:
    """
    Return a list of setting keys that appear to be referenced in an
    expression. Used to build the dependency graph for Copy/Move with Deps.

    We use a simple heuristic: find all bare identifiers that match known
    setting key patterns (lowercase with underscores).
    """
    if not expr:
        return []
    # Match identifiers that look like setting keys (not function calls)
    # Exclude known builtins and function names
    _builtins = {
        "True", "False", "None", "math", "round", "min", "max", "abs",
        "int", "float", "bool", "str", "len", "resolveOrValue",
        "extruderValue", "extruderValues", "defaultExtruderPosition",
        "anyExtruder", "valueFromContainer", "valueFromExtruderIndex",
    }
    tokens = re.findall( r'\b([a-z][a-z0-9_]*)\b', expr )
    return [ t for t in tokens if t not in _builtins ]
