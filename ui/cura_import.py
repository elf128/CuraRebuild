#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# cura_import.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   Import pipeline for Cura machine instances.
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

import configparser
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from settings.schema import CURA_SCHEMA, get_registry as _get_schema_registry
from settings.stack  import MachineLayer
from Common          import Log, LogLevel


# ---------------------------------------------------------------------------
# URL encoding helpers (Cura encodes filenames)
# ---------------------------------------------------------------------------

def _system_cura_dirs() -> list[Path]:
    """Directories where Cura stores its bundled resources (quality profiles etc)."""
    candidates = []
    for base in (
        "/usr/share/cura/resources",
        "/usr/share/UltiMaker-Cura/resources",
        "/usr/local/share/cura/resources",
        "/opt/cura/resources",
        "/Applications/UltiMaker Cura.app/Contents/Resources/resources",
        "/Applications/Ultimaker Cura.app/Contents/Resources/resources",
        r"C:\Program Files\UltiMaker Cura\resources",
        r"C:\Program Files\Ultimaker Cura\resources",
    ):
        p = Path( base )
        if p.is_dir():
            candidates.append( p )
    return candidates


def _candidate_filenames( container_id: str ) -> list[str]:
    """
    Return all filename variants to try for a container id.
    Cura uses inconsistent encoding across different subdirectories:
      - machine_instances / definition_changes: space→+,  #→%23
      - quality_changes / user:                 space→_,  #→%23
    We try all combinations to be safe.
    """
    encoded_plus  = container_id.replace( " ", "+" ).replace( "#", "%23" )
    encoded_under = container_id.replace( " ", "_" ).replace( "#", "%23" )
    # Deduplicate while preserving order
    seen = set()
    names = []
    for n in ( encoded_plus, encoded_under, container_id ):
        if n not in seen:
            seen.add( n )
            names.append( n )
    return names


def _find_container_file( version_dir: Path, container_id: str ) -> Path | None:
    """
    Search all container subdirectories for a file matching container_id.
    Searches user config dir first, then system Cura resource dirs.
    Tries all known filename encoding variants.
    """
    subdirs = (
        "user",
        "quality_changes",
        "quality",
        "intent",
        "material",
        "variant",
        "definition_changes",
    )
    filenames = _candidate_filenames( container_id )

    # 1. User config directory — try every encoding × every subdir × every ext
    for subdir in subdirs:
        for name in filenames:
            for ext in ( ".inst.cfg", ".cfg" ):
                p = version_dir / subdir / f"{ name }{ ext }"
                if p.exists():
                    return p

    # 2. System Cura resource directories (built-in profiles: draft, fast, etc.)
    for sys_dir in _system_cura_dirs():
        for subdir in subdirs:
            for name in filenames:
                for ext in ( ".inst.cfg", ".cfg" ):
                    p = sys_dir / subdir / f"{ name }{ ext }"
                    if p.exists():
                        return p

    return None


# ---------------------------------------------------------------------------
# CFG reading — handles all sections including [containers]
# ---------------------------------------------------------------------------

def _read_cfg( path: Path ) -> dict:
    """
    Parse a Cura .inst.cfg / .global.cfg file.
    Returns dict with keys: general, metadata, containers, values.
    containers is an ordered list of container id strings (index 0 = highest priority).
    """
    cp = configparser.RawConfigParser()
    cp.optionxform = str    # preserve key case

    try:
        cp.read( str( path ), encoding="utf-8" )
    except Exception as e:
        Log( LogLevel.warning, f"[CuraImport] Could not read { path.name }: { e }\n" )
        return {}

    result = {
        "general":    {},
        "metadata":   {},
        "containers": [],
        "values":     {},
    }

    for section in cp.sections():
        sl = section.lower()
        if sl == "general":
            result[ "general" ] = dict( cp.items( section ) )
        elif sl == "metadata":
            result[ "metadata" ] = dict( cp.items( section ) )
        elif sl == "containers":
            # Numbered: 0 = id_string, 1 = id_string, ...
            items = dict( cp.items( section ) )
            ordered = []
            for i in range( len( items ) ):
                val = items.get( str( i ) )
                if val is not None:
                    ordered.append( val.strip() )
            result[ "containers" ] = ordered
        elif sl == "values":
            result[ "values" ] = dict( cp.items( section ) )

    return result


# ---------------------------------------------------------------------------
# Definition JSON — flatten full inheritance chain
# ---------------------------------------------------------------------------

def _read_definition( def_name: str, definitions_dir: Path ) -> dict[str, Any]:
    """Load a .def.json and flatten its full inheritance chain."""
    merged: dict[str, Any] = {}
    visited: set[str] = set()

    def _load( name: str ) -> None:
        if name in visited:
            return
        visited.add( name )

        path = definitions_dir / f"{ name }.def.json"
        if not path.exists():
            return

        try:
            data = json.loads( path.read_text( encoding="utf-8" ) )
        except Exception as e:
            Log( LogLevel.warning, f"[CuraImport] Could not parse { path.name }: { e }\n" )
            return

        parent = data.get( "inherits" )
        if parent:
            _load( parent )

        # Flatten overrides block
        for key, val in data.get( "overrides", {} ).items():
            if isinstance( val, dict ):
                v = val.get( "default_value", val.get( "value" ) )
                if v is not None:
                    merged[ key ] = v
            else:
                merged[ key ] = val

        # Walk nested settings tree
        def _walk( node: dict ) -> None:
            for key, val in node.items():
                if isinstance( val, dict ):
                    if "default_value" in val:
                        merged.setdefault( key, val[ "default_value" ] )
                    _walk( val.get( "children", {} ) )

        _walk( data.get( "settings", {} ) )

    _load( def_name )
    return merged


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------

def _coerce( val: str ) -> Any:
    """Coerce a CFG string value to the appropriate Python type."""
    v = val.strip()
    if v.lower() == "true":  return True
    if v.lower() == "false": return False
    try: return int( v )
    except ValueError: pass
    try: return float( v )
    except ValueError: pass
    return v


# ---------------------------------------------------------------------------
# MachineInstance
# ---------------------------------------------------------------------------

class MachineInstance:
    """
    One saved Cura printer, with lazy full-stack resolution.
    display_name includes the Cura version so duplicates are distinguishable.
    """

    def __init__(
        self,
        name:          str,
        version_dir:   Path,
        instance_path: Path,
        containers:    list[str],
        def_name:      str,
    ):
        self.name          = name
        self.version_dir   = version_dir
        self.instance_path = instance_path
        self.containers    = containers     # ordered [0=highest .. N=lowest]
        self.def_name      = def_name
        self.display_name  = f"{ name }  ({ version_dir.name })"

        self._flat:  dict[str, Any] = {}
        self._built: bool = False

    def _ensure_built( self ) -> None:
        if self._built:
            return
        self._flat  = self._resolve()
        self._built = True

    def _resolve( self ) -> dict[str, Any]:
        """
        Build flat settings dict by merging the container stack.
        Lower index = higher priority → we merge low→high then reverse wins.
        We walk from the last container (lowest priority) to index 0 (highest).
        """
        flat: dict[str, Any] = {}
        definitions_dir = self.version_dir / "definitions"

        # Virtual definitions Cura handles internally — map to real base def
        _virtual_def_map = {
            "custom":          "fdmprinter",
            "custom_extruder": "fdmextruder",
        }
        effective_def = _virtual_def_map.get( self.def_name, self.def_name )

        # Start with the base definition JSON (lowest priority)
        # Also search system Cura dirs if not found in version_dir/definitions
        if effective_def:
            flat.update( _read_definition( effective_def, definitions_dir ) )
            if not flat:
                # Try system dirs
                for sys_dir in _system_cura_dirs():
                    sys_defs = sys_dir / "definitions"
                    if sys_defs.is_dir():
                        flat.update( _read_definition( effective_def, sys_defs ) )
                        if flat:
                            break
            Log( LogLevel.debug,
                f"[CuraImport] Base def '{ effective_def }': { len( flat ) } keys\n" )

        # Walk containers from lowest priority (last) to highest (index 0)
        Log( LogLevel.info,
            f"[CuraImport] Resolving { len( self.containers ) } containers: "
            f"{ self.containers }\n" )

        for container_id in reversed( self.containers ):
            if container_id.startswith( "empty_" ):
                Log( LogLevel.debug, f"[CuraImport] Skip empty: { container_id }\n" )
                continue

            # Check if it's a definition name (last container usually is)
            def_path = definitions_dir / f"{ container_id }.def.json"
            if def_path.exists():
                flat.update( _read_definition( container_id, definitions_dir ) )
                Log( LogLevel.debug,
                    f"[CuraImport] Container def '{ container_id }': merged\n" )
                continue

            # Otherwise find it as a .inst.cfg file
            cfg_path = _find_container_file( self.version_dir, container_id )
            if cfg_path is None:
                Log( LogLevel.info,
                    f"[CuraImport] Container not found: '{ container_id }'\n" )
                continue

            data = _read_cfg( cfg_path )
            values = data.get( "values", {} )
            Log( LogLevel.info,
                f"[CuraImport] Container '{ container_id }' "
                f"@ { cfg_path.name }: { len( values ) } values\n" )
            if values:
                for key, raw in values.items():
                    flat[ key ] = _coerce( raw )

        Log( LogLevel.info,
            f"[CuraImport] Resolved { len( flat ) } total settings\n" )
        return flat

    @property
    def flat_settings( self ) -> dict[str, Any]:
        self._ensure_built()
        return self._flat

    def to_layer( self ) -> MachineLayer:
        """
        Create a MachineLayer populated with machine-home settings only.
        For a full split use to_layers().
        """
        machine_layer, _ = self.to_layers()
        return machine_layer

    def to_layers( self ) -> tuple:
        """
        Split the resolved settings into two layers:
          - MachineLayer : settings whose schema home_layer is MACHINE
          - UserLayer    : everything else (temps, speeds, quality, etc.)

        Returns ( MachineLayer, UserLayer ).
        The UserLayer is named "<name> profile" and may be None if no
        non-machine settings were found.
        """
        from settings.schema import LayerRole
        from settings.stack  import UserLayer

        machine_layer = MachineLayer( name=self.name )
        user_layer    = UserLayer( name=f"{ self.name } profile" )

        m_imported = u_imported = skipped = 0

        # Use live registry (loaded from fdmprinter.def.json) if available,
        # fall back to hardcoded CURA_SCHEMA
        try:
            active_cura_schema = _get_schema_registry().cura_schema
        except Exception:
            active_cura_schema = CURA_SCHEMA

        for cura_key, value in self.flat_settings.items():
            sdef = active_cura_schema.get( cura_key )
            if sdef is None:
                skipped += 1
                continue
            try:
                if sdef.home_layer == LayerRole.MACHINE:
                    machine_layer.set( sdef.key, value )
                    m_imported += 1
                else:
                    user_layer.set( sdef.key, value )
                    u_imported += 1
            except Exception as e:
                Log( LogLevel.debug,
                    f"[CuraImport] Skip '{ cura_key }' = { value!r }: { e }\n" )
                skipped += 1

        Log( LogLevel.info,
            f"[CuraImport] '{ self.name }': "
            f"{ m_imported } machine, { u_imported } profile, "
            f"{ skipped } skipped\n" )

        return machine_layer, ( user_layer if u_imported > 0 else None )

    def __repr__( self ) -> str:
        return f"MachineInstance( name={ self.name!r }, version={ self.version_dir.name } )"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _cura_config_dirs() -> list[Path]:
    """All Cura per-version config directories, newest first."""
    candidates = []
    home = Path.home()

    roots = [
        home / ".local" / "share" / "cura",
        home / "Library" / "Application Support" / "cura",
        Path( os.environ.get( "APPDATA", "" ) ) / "cura",
    ]

    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted( root.iterdir(), reverse=True ):
            if entry.is_dir() and entry.name[ 0 ].isdigit():
                candidates.append( entry )

    return candidates


def scan_cura_machines() -> list[MachineInstance]:
    """
    Scan all Cura version directories and return one MachineInstance
    per saved printer. display_name includes the version number.
    """
    results = []

    for version_dir in _cura_config_dirs():
        instances_dir = version_dir / "machine_instances"
        if not instances_dir.is_dir():
            continue

        # Files are named with URL encoding and end in .global.cfg
        for cfg_path in sorted( instances_dir.glob( "*.cfg" ) ):
            data     = _read_cfg( cfg_path )
            general  = data.get( "general",    {} )
            containers = data.get( "containers", [] )

            name     = general.get( "name", unquote( cfg_path.stem.replace( "+", " " ) ) )
            def_name = ""

            # The last non-empty container is usually the definition name.
            # Also recognise virtual definitions (custom, custom_extruder)
            # that don't have a .def.json file but are known to Cura.
            _virtual_defs = { "custom", "custom_extruder", "fdmprinter", "fdmextruder" }
            for cid in reversed( containers ):
                if cid.startswith( "empty_" ):
                    continue
                def_path = version_dir / "definitions" / f"{ cid }.def.json"
                if def_path.exists() or cid in _virtual_defs:
                    def_name = cid
                    break

            instance = MachineInstance(
                name          = name,
                version_dir   = version_dir,
                instance_path = cfg_path,
                containers    = containers,
                def_name      = def_name,
            )
            results.append( instance )
            Log( LogLevel.debug,
                f"[CuraImport] Found: '{ instance.display_name }' "
                f"def='{ def_name }' containers={ len( containers ) }\n" )

    Log( LogLevel.info,
        f"[CuraImport] Found { len( results ) } Cura machine instance(s).\n" )
    return results


def scan_definition_files( version_dir: Path ) -> list[tuple[str, Path]]:
    """
    Fallback: return (name, path) for machine .def.json files
    when no machine_instances exist.
    """
    results = []
    defs_dir = version_dir / "definitions"
    if not defs_dir.is_dir():
        return results

    for path in sorted( defs_dir.glob( "*.def.json" ) ):
        try:
            data = json.loads( path.read_text( encoding="utf-8" ) )
            meta = data.get( "metadata", {} )
            if meta.get( "type", "" ) not in ( "machine", "" ):
                continue
            if not meta.get( "type" ) and "machine_width" not in str( data ):
                continue
            results.append( ( data.get( "name", path.stem ), path ) )
        except Exception:
            pass

    return results


def load_definition_as_instance(
    name: str, path: Path, version_dir: Path
) -> MachineInstance:
    """Wrap a raw .def.json as a MachineInstance (no CFG stack)."""
    inst = MachineInstance(
        name          = name,
        version_dir   = version_dir,
        instance_path = path,
        containers    = [],
        def_name      = path.stem,
    )
    return inst


def load_json_file( path: Path ) -> MachineInstance | None:
    """Load any JSON or CFG file as a MachineInstance."""
    try:
        if path.suffix in ( ".cfg", ) or ".cfg" in path.name:
            # Treat as a machine instance CFG
            data      = _read_cfg( path )
            general   = data.get( "general", {} )
            containers = data.get( "containers", [] )
            name      = general.get( "name", path.stem )
            version_dir = path.parent.parent
            def_name  = ""
            for cid in reversed( containers ):
                if not cid.startswith( "empty_" ):
                    def_path = version_dir / "definitions" / f"{ cid }.def.json"
                    if def_path.exists():
                        def_name = cid
                        break
            return MachineInstance(
                name=name, version_dir=version_dir,
                instance_path=path, containers=containers, def_name=def_name,
            )
        else:
            data = json.loads( path.read_text( encoding="utf-8" ) )
            name = data.get( "name", path.stem )
            flat: dict[str, Any] = {}
            if "overrides" in data or "settings" in data:
                flat = _read_definition( path.stem, path.parent )
            else:
                flat = { k: v for k, v in data.items()
                         if isinstance( v, ( int, float, str, bool ) ) }
            inst = MachineInstance(
                name=name, version_dir=path.parent,
                instance_path=path, containers=[], def_name=path.stem,
            )
            inst._flat  = flat
            inst._built = True
            return inst
    except Exception as e:
        Log( LogLevel.warning, f"[CuraImport] Could not load { path }: { e }\n" )
        return None
