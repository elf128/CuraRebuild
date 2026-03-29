#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# profile_import.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   Import pipeline for .curaprofile and sliced G-code.
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
import zipfile
from pathlib import Path
from typing import Any

from Common import Log, LogLevel


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _coerce( raw: str ) -> Any:
    """Best-effort coerce a string value to int, float, bool, or str."""
    if raw in ( "True", "true" ):
        return True
    if raw in ( "False", "false" ):
        return False
    try:
        return int( raw )
    except ValueError:
        pass
    try:
        return float( raw )
    except ValueError:
        pass
    return raw


def _parse_ini_values( text: str ) -> dict[str, Any]:
    """
    Parse the [values] section of a Cura .inst.cfg file.
    Returns key → coerced value dict.
    """
    values: dict[str, Any] = {}
    in_values = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith( ";" ):
            continue
        if line.startswith( "[" ):
            in_values = ( line.lower() == "[values]" )
            continue
        if in_values and "=" in line:
            key, _, raw = line.partition( "=" )
            key = key.strip()
            raw = raw.strip()
            if key:
                # URL-decode Cura's + → space, %23 → #
                key = key.replace( "+", " " ).replace( "%23", "#" )
                raw = raw.replace( "+", " " ).replace( "%23", "#" )
                values[ key ] = _coerce( raw )
    return values


def _parse_ini_general( text: str ) -> dict[str, str]:
    """Parse [general] section — returns name, version, type etc."""
    info: dict[str, str] = {}
    in_general = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith( ";" ):
            continue
        if line.startswith( "[" ):
            in_general = ( line.lower() == "[general]" )
            continue
        if in_general and "=" in line:
            key, _, val = line.partition( "=" )
            info[ key.strip() ] = val.strip()
    return info


# ---------------------------------------------------------------------------
# .curaprofile importer
# ---------------------------------------------------------------------------

class CuraProfileImport:
    """
    Reads a .curaprofile zip archive and merges all quality_changes /
    user container values into a single flat dict.

    A .curaprofile typically contains:
      - one or more container files with NO file extension (just container ID as name)
      - older exports may use .inst.cfg extensions
      - each has a [general] section with name/type and a [values] section
    """

    def __init__( self, path: Path | str ):
        self.path       = Path( path )
        self.name       = self.path.stem
        self._flat:     dict[str, Any] = {}
        self._containers: list[dict]   = []
        self._load()

    def _load( self ) -> None:
        if not self.path.exists():
            raise FileNotFoundError( f"Profile not found: { self.path }" )

        with zipfile.ZipFile( self.path, "r" ) as zf:
            all_names = zf.namelist()

            # .curaprofile files store entries with NO file extension —
            # just the container ID as the bare filename (e.g. "Custom FFF printer").
            # Older exports may have .inst.cfg or .cfg extensions.
            # We accept any entry that looks like an INI file regardless of name.
            candidate_names = [
                n for n in all_names
                if not n.endswith( "/" )           # skip directory entries
                and not n.startswith( "__MACOSX" ) # skip macOS metadata
                and not n.startswith( "." )        # skip hidden files
            ]

            if not candidate_names:
                raise ValueError(
                    f"Empty archive: { self.path.name }. "
                    f"Contents: { all_names }"
                )

            Log( LogLevel.info,
                f"[ProfileImport] { self.path.name }: "
                f"{ len( candidate_names ) } entries: { candidate_names }\n" )

            for cfg_name in candidate_names:
                text = zf.read( cfg_name ).decode( "utf-8", errors="replace" )
                # Only process entries that have a [general] or [values] section
                text_lower = text.lower()
                if "[general]" not in text_lower and "[values]" not in text_lower:
                    Log( LogLevel.debug,
                        f"[ProfileImport]   skip '{ cfg_name }' — not INI\n" )
                    continue
                general = _parse_ini_general( text )
                values  = _parse_ini_values( text )
                self._containers.append({
                    "name":   general.get( "name", cfg_name ),
                    "type":   general.get( "type", "" ),
                    "values": values,
                })
                Log( LogLevel.debug,
                    f"[ProfileImport]   '{ cfg_name }': "
                    f"type={ general.get('type','?') } "
                    f"{ len( values ) } values\n" )

            if not self._containers:
                raise ValueError(
                    f"No valid Cura INI containers found in { self.path.name }. "
                    f"Entries: { candidate_names }"
                )

        # Merge: definition_changes < quality < quality_changes < user
        _type_priority = {
            "definition_changes": 0,
            "quality":            1,
            "quality_changes":    2,
            "user":               3,
        }
        ordered = sorted(
            self._containers,
            key=lambda c: _type_priority.get( c["type"], 1 )
        )
        for container in ordered:
            self._flat.update( container["values"] )

        # Use name from highest-priority quality_changes container if available
        for c in reversed( ordered ):
            if c["type"] in ( "quality_changes", "user" ) and c["name"]:
                self.name = c["name"]
                break

        Log( LogLevel.info,
            f"[ProfileImport] '{ self.name }': "
            f"{ len( self._flat ) } total settings\n" )

    @property
    def flat_settings( self ) -> dict[str, Any]:
        return self._flat

    def to_user_layer( self ):
        """
        Convert to a UserLayer containing all recognised settings.
        Unknown keys are silently skipped.
        """
        from settings.schema import get_registry as _gr
        from settings.stack  import UserLayer

        schema     = _gr()
        user_layer = UserLayer( name=self.name )
        imported = skipped = 0

        for cura_key, value in self._flat.items():
            sdef = schema.cura_schema.get( cura_key )
            if sdef is None:
                skipped += 1
                continue
            try:
                user_layer.set( sdef.key, value )
                imported += 1
            except Exception as e:
                Log( LogLevel.debug,
                    f"[ProfileImport] Skip '{ cura_key }' = { value!r }: { e }\n" )
                skipped += 1

        Log( LogLevel.info,
            f"[ProfileImport] '{ self.name }': "
            f"{ imported } imported, { skipped } skipped\n" )
        return user_layer


# ---------------------------------------------------------------------------
# Gcode importer
# ---------------------------------------------------------------------------

# Cura embeds settings in two formats at the end of gcode:
#
# Format 1 (older): ;key = value
# Format 2 (newer): ;   key = value  (inside a ;Settings block)
#
# The block is delimited by:
#   ;SETTING_3 0 <base64-encoded zlib data>
# OR just a series of ;key = value lines after the print commands.

_SETTING_LINE = re.compile( r'^;+\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$' )
_SETTING3_HEADER = re.compile( r'^;SETTING_3\s+' )


class GcodeProfileImport:
    """
    Reads Cura-sliced gcode and extracts embedded settings comments.
    """

    def __init__( self, path: Path | str ):
        self.path      = Path( path )
        self.name      = self.path.stem
        self._flat:    dict[str, Any] = {}
        self._load()

    def _load( self ) -> None:
        if not self.path.exists():
            raise FileNotFoundError( f"Gcode not found: { self.path }" )

        raw_settings: dict[str, Any] = {}

        # Try SETTING_3 compressed block first (Cura 4+)
        setting3_ok = self._try_setting3( raw_settings )
        Log( LogLevel.info,
            f"[GcodeImport] SETTING_3: { 'found' if setting3_ok else 'not found' }\n" )

        if not setting3_ok:
            # Fall back to plain ;key = value comment scanning
            self._scan_comments( raw_settings )

        self._flat = raw_settings
        Log( LogLevel.info,
            f"[GcodeImport] '{ self.path.name }': "
            f"{ len( self._flat ) } settings found\n" )

    def _try_setting3( self, out: dict ) -> bool:
        """
        Read the SETTING_3 block written by Cura at the end of gcode.

        Cura has used two formats over the years:

        Format A (Cura 4.x+, common): Plain JSON split across lines
          ;SETTING_3 {"global_quality": "[general]\\n...[values]\\nkey = val\\n",
          ;SETTING_3  "extruder_quality": ["[general]\\n...\\n[values]\\n..."]}
          The JSON values are INI text with literal \n (escaped newlines).

        Format B (older Cura): base64-encoded zlib-compressed INI text
          ;SETTING_3 0 <base64_chunk_0>
          ;SETTING_3 1 <base64_chunk_1>

        Returns True if any settings were successfully parsed.
        """
        import base64, zlib, json as _json

        try:
            text = self.path.read_text( encoding="utf-8", errors="replace" )
        except Exception:
            return False

        # Collect all ;SETTING_3 lines, stripping the prefix
        prefix    = ";SETTING_3 "
        s3_lines  = [
            line[ len( prefix ): ]
            for line in text.splitlines()
            if line.startswith( prefix )
        ]

        if not s3_lines:
            Log( LogLevel.debug, "[GcodeImport] No SETTING_3 lines found\n" )
            return False

        Log( LogLevel.info,
            f"[GcodeImport] Found { len( s3_lines ) } SETTING_3 lines\n" )

        raw = "".join( s3_lines )

        # --- Try Format A: plain JSON ---
        try:
            data = _json.loads( raw )
            # data has keys: "global_quality" (str) and "extruder_quality" (list of str)
            # Each value is an INI block with literal \n as line separator
            values: dict = {}

            def _parse_ini_block( block: str ) -> dict:
                # Unescape \n → real newlines then parse [values] section
                unescaped = block.replace( "\\n", "\n" ).replace( "\n", "\n" )
                return _parse_ini_values( unescaped )

            # global_quality — merge first (lower priority)
            gq = data.get( "global_quality", "" )
            if isinstance( gq, str ):
                values.update( _parse_ini_block( gq ) )

            # extruder_quality[0] — higher priority, overrides global
            eq = data.get( "extruder_quality", [] )
            if isinstance( eq, list ) and eq:
                values.update( _parse_ini_block( eq[0] ) )

            if values:
                out.update( values )
                Log( LogLevel.info,
                    f"[GcodeImport] SETTING_3 (JSON format): "
                    f"{ len( values ) } values\n" )
                return True
        except ( _json.JSONDecodeError, KeyError, TypeError ):
            pass

        # --- Try Format B: base64 + zlib (older Cura) ---
        # Lines may be prefixed with a sequence number: "0 <b64>" or just "<b64>"
        b64_chunks: list[tuple[int, str]] = []
        for line in s3_lines:
            parts = line.split( None, 1 )
            if len( parts ) == 2:
                try:
                    seq = int( parts[0] )
                    b64_chunks.append( ( seq, parts[1] ) )
                except ValueError:
                    b64_chunks.append( ( len( b64_chunks ), line ) )
            else:
                b64_chunks.append( ( len( b64_chunks ), line ) )

        b64_chunks.sort( key=lambda x: x[0] )
        b64_data = "".join( c for _, c in b64_chunks )

        try:
            compressed = base64.b64decode( b64_data )
        except Exception as e:
            Log( LogLevel.warning,
                f"[GcodeImport] SETTING_3 base64 decode failed: { e }\n" )
            return False

        decoded = None
        for wbits in ( 15, -15, 31, 47 ):
            try:
                decoded = zlib.decompress( compressed, wbits ).decode( "utf-8" )
                break
            except Exception:
                continue

        if decoded is None:
            Log( LogLevel.warning,
                "[GcodeImport] SETTING_3 decode failed (all formats tried)\n" )
            return False

        values = _parse_ini_values( decoded )
        if values:
            out.update( values )
            Log( LogLevel.info,
                f"[GcodeImport] SETTING_3 (compressed format): "
                f"{ len( values ) } values\n" )
            return True

        return False

    def _scan_comments( self, out: dict ) -> None:
        """
        Scan for ;key = value comment lines.

        Cura places settings in two possible locations:
          1. At the very end of the file as a ;key = value block
          2. Embedded in the start/end gcode as printer-specific comments

        Strategy: scan the last 500 lines first (catches end-of-file block),
        then if nothing found, scan the whole file.
        """
        try:
            lines = self.path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except Exception:
            return

        def _scan_lines( line_list ):
            found = {}
            for line in line_list:
                m = _SETTING_LINE.match( line.strip() )
                if m:
                    key = m.group(1).strip()
                    val = _coerce( m.group(2).strip() )
                    found[ key ] = val
            return found

        # Try last 500 lines first (Cura settings block at end of file)
        tail   = lines[ -500: ] if len( lines ) > 500 else lines
        found  = _scan_lines( tail )

        # If nothing in tail, try full file scan
        if not found:
            found = _scan_lines( lines )

        out.update( found )
        Log( LogLevel.info,
            f"[GcodeImport] comment scan: { len( found ) } values "
            f"(scanned { len( tail ) } tail lines)\n" )

    @property
    def flat_settings( self ) -> dict[str, Any]:
        return self._flat

    def to_user_layer( self ):
        """Convert to a UserLayer containing all recognised settings."""
        from settings.schema import get_registry as _gr
        from settings.stack  import UserLayer

        schema     = _gr()
        user_layer = UserLayer( name=self.name )
        imported = skipped = 0

        for cura_key, value in self._flat.items():
            sdef = schema.cura_schema.get( cura_key )
            if sdef is None:
                Log( LogLevel.debug,
                    f"[GcodeImport] Unknown key: '{ cura_key }' = { value!r }\n" )
                skipped += 1
                continue
            try:
                user_layer.set( sdef.key, value )
                imported += 1
            except Exception as e:
                Log( LogLevel.debug,
                    f"[GcodeImport] Skip '{ cura_key }' = { value!r }: { e }\n" )
                skipped += 1

        Log( LogLevel.info,
            f"[GcodeImport] '{ self.name }': "
            f"{ imported } imported, { skipped } skipped\n"
            f"  flat keys: { list( self._flat.keys() ) }\n" )
        return user_layer
