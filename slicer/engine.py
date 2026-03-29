#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# engine.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   CuraEngine subprocess orchestration.
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

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import FreeCAD
import Mesh
from FreeCAD import Console

from settings.stack import SettingsStack
from settings.cura_export import write_all_defs, build_cura_args


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class SliceResult:
    def __init__(
        self,
        success: bool,
        gcode_path: Path | None,
        log_path: Path | None,
        error: str = "",
    ):
        self.success    = success
        self.gcode_path = gcode_path
        self.log_path   = log_path
        self.error      = error

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAILED: {self.error}"
        return f"SliceResult({status}, gcode={self.gcode_path})"


# ---------------------------------------------------------------------------
# Core slice function
# ---------------------------------------------------------------------------

def slice_build_volume(
    build_volume_fp,                         # FreeCAD DocumentObject (BuildVolume)
    stack:        SettingsStack,
    output_dir:   Path | str | None = None,
    progress_cb:  Callable[[str], None] | None = None,
    cura_bin:     str | None = None,         # override binary path
) -> SliceResult:
    """
    Run a full slice operation for the given BuildVolume document object.

    Parameters
    ----------
    build_volume_fp : FreeCAD.DocumentObject
        The BuildVolume FeaturePython object (has .Proxy of type BuildVolume).
    stack : SettingsStack
        The resolved settings stack for this build volume.
    output_dir : Path | None
        Where to write STL, def files, and G-code.
        Defaults to a temp directory if not provided.
    progress_cb : callable(str) | None
        Optional callback for progress messages.

    Returns
    -------
    SliceResult
    """
    def log(msg: str) -> None:
        Console.PrintMessage(f"[SlicerEngine] {msg}\n")
        if progress_cb:
            progress_cb(msg)

    # ------------------------------------------------------------------
    # 1. Resolve output directory
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="slicer_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    log(f"Output directory: {output_dir}")

    # ------------------------------------------------------------------
    # 2. Collect assigned bodies
    proxy = build_volume_fp.Proxy
    body_names = proxy.get_assigned_body_names(build_volume_fp)

    if not body_names:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=None,
            error="No bodies assigned to this BuildVolume.",
        )

    doc = FreeCAD.ActiveDocument
    bodies = []
    for name in body_names:
        obj = doc.getObject(name)
        if obj is None:
            log(f"Warning: assigned body '{name}' not found in document — skipping.")
            continue
        if not hasattr(obj, "Shape"):
            log(f"Warning: '{name}' has no Shape — skipping.")
            continue
        bodies.append(obj)

    if not bodies:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=None,
            error="No valid Shape objects found among assigned bodies.",
        )

    log(f"Found {len(bodies)} body/bodies: {[b.Name for b in bodies]}")

    # ------------------------------------------------------------------
    # 3. Transform shapes to printer space and export STL

    stl_paths: list[Path] = []

    for obj in bodies:
        log(f"Transforming '{obj.Name}' to printer space …")

        transformed_shape = proxy.transform_shape_to_printer(
            build_volume_fp, obj.Shape
        )

        stl_path = output_dir / f"{obj.Name}.stl"
        _export_shape_as_stl(transformed_shape, stl_path)
        stl_paths.append(stl_path)
        log(f"  → {stl_path}")

    # ------------------------------------------------------------------
    # 4. Write CuraEngine definition files

    log("Writing CuraEngine definition files …")
    body_ids = [obj.Name for obj in bodies]

    # Build fp_map: layer_id → FP object for ApplyTo resolution
    fp_map = {}
    try:
        from registry_object import get_registry_fp
        reg_fp = get_registry_fp( build_volume_fp.Document )
        if reg_fp and hasattr( reg_fp, "Proxy" ):
            for lid, fp_name in reg_fp.Proxy._layer_fps.items():
                child_fp = build_volume_fp.Document.getObject( fp_name )
                if child_fp:
                    fp_map[ lid ] = child_fp
    except Exception:
        pass

    def_paths = write_all_defs( stack, output_dir,
                                body_ids=body_ids, fp_map=fp_map )

    # Copy base definition files to temp dir so CuraEngine can resolve "inherits"
    import shutil as _shutil
    _data_dir = Path( __file__ ).parent.parent / "data"
    for _def_name in ( "fdmprinter.def.json", "fdmextruder.def.json" ):
        _def_src = _data_dir / _def_name
        if _def_src.exists():
            _shutil.copy2( str(_def_src), str(output_dir / _def_name) )
            log( f"  copied {_def_name} to temp dir" )
        else:
            log( f"  WARNING: {_def_name} not found in data/ — "
                 f"CuraEngine may fail to resolve definition inheritance" )

    log(f"  machine def : {def_paths['machine']}")
    for k, v in def_paths.items():
        if k.startswith("extruder_"):
            log(f"  {k} def  : {v}")

    # ------------------------------------------------------------------
    # 5. Resolve CuraEngine binary path
    # Priority: explicit arg > BuildVolume.CuraEnginePath > auto-detect
    if not cura_bin:
        cura_bin = getattr( build_volume_fp, "CuraEnginePath", "" ) or None
    if not cura_bin:
        cura_bin = _resolve_cura_bin()
    if not cura_bin:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=None,
            error=(
                "CuraEngine binary path is not configured. "
                "Set CuraEnginePath on the BuildVolume object."
            ),
        )

    if not Path(cura_bin).exists():
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=None,
            error=f"CuraEngine binary not found: {cura_bin}",
        )

    # ------------------------------------------------------------------
    # 6. Build argument list and invoke CuraEngine

    gcode_path = output_dir / "output.gcode"
    log_path   = output_dir / "cura.log"

    # Use extruder defs if available, else fall back to merged profile
    extruder_defs = sorted(
        [ v for k, v in def_paths.items() if k.startswith("extruder_") ],
        key=lambda p: p.name
    )
    profile_def = extruder_defs[0] if extruder_defs else def_paths["profile"]

    args = build_cura_args(
        cura_bin=cura_bin,
        machine_def=def_paths["machine"],
        profile_def=profile_def,
        stl_paths=stl_paths,
        gcode_output=gcode_path,
        extra_defs=extruder_defs[1:] if len(extruder_defs) > 1 else [],
    )

    log(f"Invoking CuraEngine: {' '.join(str(a) for a in args)}")

    # CuraEngine writes G-code to the -o file AND to stdout (some versions).
    # Stderr contains the actual diagnostic log.
    # We capture stderr → cura.log, stdout → stdout.gcode (fallback if -o fails).
    stdout_path = output_dir / "stdout.gcode"

    try:
        with open(log_path,    "w", encoding="utf-8") as log_file,              open(stdout_path, "wb"                  ) as stdout_file:

            log_file.write("=== CuraEngine invocation ===\n")
            log_file.write(" ".join(str(a) for a in args) + "\n\n")
            log_file.write("=== stderr ===\n")
            log_file.flush()

            result = subprocess.run(
                args,
                stdout=stdout_file,
                stderr=log_file,
                timeout=600,
                cwd=str(output_dir),   # CuraEngine resolves "inherits" relative to cwd
            )

            # Append return code to log
            log_file.write(f"\n=== exit code: {result.returncode} ===\n")

    except subprocess.TimeoutExpired:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=log_path,
            error="CuraEngine timed out after 10 minutes.",
        )
    except Exception as e:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=log_path,
            error=f"Failed to launch CuraEngine: {e}",
        )

    if result.returncode != 0:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=log_path,
            error=f"CuraEngine exited with code {result.returncode}. "
                  f"See log: {log_path}",
        )

    # Prefer the -o output file; fall back to stdout capture if it's non-empty
    if gcode_path.exists() and gcode_path.stat().st_size > 0:
        pass   # normal case
    elif stdout_path.exists() and stdout_path.stat().st_size > 0:
        log( "Note: G-code came from stdout (not -o file) — using stdout capture" )
        gcode_path = stdout_path
    else:
        return SliceResult(
            success=False,
            gcode_path=None,
            log_path=log_path,
            error="CuraEngine returned 0 but produced no G-code. "
                  f"Check log: {log_path}",
        )

    log(f"Slice complete → {gcode_path}")
    return SliceResult(success=True, gcode_path=gcode_path, log_path=log_path)


# ---------------------------------------------------------------------------
# G-code coordinate transform (printer → world)
# ---------------------------------------------------------------------------

def transform_gcode_lines(
    gcode_path: Path | str,
    build_volume_fp,
    output_path: Path | str | None = None,
) -> Path:
    """
    Read a G-code file and rewrite all X/Y/Z coordinates from printer space
    into world space (document units).

    This produces a new G-code file suitable for the in-FreeCAD visualiser.
    The original file is not modified.

    Parameters
    ----------
    gcode_path : Path
        The G-code file produced by CuraEngine (printer coordinates).
    build_volume_fp : FreeCAD.DocumentObject
        The BuildVolume whose transform will be applied.
    output_path : Path | None
        Where to write the transformed G-code.
        Defaults to <gcode_path>.world.gcode.

    Returns
    -------
    Path to the transformed G-code file.
    """
    import re

    gcode_path = Path(gcode_path)
    if output_path is None:
        output_path = gcode_path.with_suffix(".world.gcode")
    output_path = Path(output_path)

    proxy = build_volume_fp.Proxy

    # Regex to find X, Y, Z coordinates in a G-code line
    coord_re = re.compile(r'([XYZ])(-?\d+\.?\d*)')

    with open(gcode_path, "r", encoding="utf-8", errors="replace") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:

        for line in fin:
            stripped = line.strip()

            # Only transform move commands (G0, G1, G2, G3)
            if stripped.startswith(("G0", "G1", "G2", "G3")):
                coords = {}
                for m in coord_re.finditer(stripped):
                    coords[m.group(1)] = float(m.group(2))

                if coords:
                    x = coords.get("X", 0.0)
                    y = coords.get("Y", 0.0)
                    z = coords.get("Z", 0.0)

                    wx, wy, wz = proxy.transform_gcode_point(
                        build_volume_fp, x, y, z
                    )

                    # Replace coordinates in the original line
                    def replace_coord(m):
                        axis = m.group(1)
                        if axis == "X":
                            return f"X{wx:.4f}"
                        elif axis == "Y":
                            return f"Y{wy:.4f}"
                        elif axis == "Z":
                            return f"Z{wz:.4f}"
                        return m.group(0)

                    line = coord_re.sub(replace_coord, line)

            fout.write(line)

    return output_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _export_shape_as_stl(shape, path: Path) -> None:
    """Export a Part.Shape to an ASCII STL file via FreeCAD's Mesh module."""
    import Part
    mesh = FreeCAD.ActiveDocument.addObject("Mesh::Feature", "__tmp_export__")
    mesh.Mesh = Mesh.Mesh(shape.tessellate(0.1))
    Mesh.export([mesh], str(path))
    FreeCAD.ActiveDocument.removeObject(mesh.Name)


def _resolve_cura_bin() -> str | None:
    """
    Try common system paths for CuraEngine.
    Called when CuraEnginePath is not set on the BuildVolume.
    """
    # Common fallback paths
    candidates = [
        "/usr/bin/CuraEngine",
        "/usr/local/bin/CuraEngine",
        "/usr/share/cura/CuraEngine",
        # Windows
        r"C:\Program Files\Ultimaker Cura\CuraEngine.exe",
        r"C:\Program Files\UltiMaker Cura\CuraEngine.exe",
        # macOS
        "/Applications/Ultimaker Cura.app/Contents/MacOS/CuraEngine",
        "/Applications/UltiMaker Cura.app/Contents/MacOS/CuraEngine",
    ]

    for p in candidates:
        if Path(p).exists():
            return p

    return None
