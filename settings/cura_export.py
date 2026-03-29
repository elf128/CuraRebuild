# settings/cura_export.py
#
# Serialises a SettingsStack into the CuraEngine definition file stack:
#
#   machine.def.json     — machine hardware definition
#   profile.def.json     — collapsed override profile (all user layers merged)
#   <body_id>.def.json   — per-mesh override definitions (one per assigned body)
#
# CuraEngine definition format (version 2):
# {
#   "name": "...",
#   "version": 2,
#   "metadata": {
#     "type": "machine" | "quality" | "quality_changes",
#     "setting_version": 22,
#     "author": "CuraRebuild"
#   },
#   "overrides": {
#     "<cura_key>": { "default_value": <value> },
#     ...
#   }
# }
#
# CuraEngine is invoked with:
#   CuraEngine slice
#     -j machine.def.json
#     -l model.stl
#     -o output.gcode
#     -s <cura_key>=<value>   (any remaining per-slice overrides)
#
# Our approach:
#   - machine.def.json  contains only MACHINE-home-layer settings
#   - profile.def.json  contains the collapsed user-layer stack (all user layers
#                       merged in priority order, machine layer excluded)
#   - At slice time, any residual settings not in either def are passed as -s flags

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from settings.schema import SCHEMA, LayerRole
from settings.stack import SettingsStack


# CuraEngine definition format version
_DEF_VERSION      = 2
_SETTING_VERSION  = 22
_AUTHOR           = "FreeCAD CuraRebuild"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _overrides_block(flat: dict[str, Any]) -> dict[str, dict]:
    """
    Convert a flat key→value dict into CuraEngine's overrides format.
    Skips FreeCAD-only keys (cura_key == "").
    """
    out = {}
    for key, value in flat.items():
        sdef = SCHEMA.get(key)
        if sdef is None or not sdef.cura_key:
            continue
        # Booleans: CuraEngine expects Python bool → JSON true/false
        if sdef.dtype == bool:
            out[sdef.cura_key] = {"default_value": bool(value)}
        elif sdef.dtype == int:
            out[sdef.cura_key] = {"default_value": int(value)}
        elif sdef.dtype == float:
            out[sdef.cura_key] = {"default_value": float(value)}
        else:
            out[sdef.cura_key] = {"default_value": str(value)}
    return out


def _machine_flat(stack: SettingsStack) -> dict[str, Any]:
    """
    Extract only the settings whose home_layer is MACHINE from the
    effective (fully resolved) stack.
    """
    effective = stack.effective()
    return {
        k: v for k, v in effective.items()
        if SCHEMA.get(k) and SCHEMA[k].home_layer == LayerRole.MACHINE
        and SCHEMA[k].cura_key
    }


def _profile_flat(stack: SettingsStack) -> dict[str, Any]:
    """
    Merge all user layers (low → high priority) into a single flat dict,
    excluding machine-home settings (those go in machine.def.json).
    The result is everything that overrides the machine defaults.
    """
    merged: dict[str, Any] = {}

    # Walk user layers low → high so higher layers overwrite
    for layer in stack.user_layers:
        for key, value in layer.items():
            sdef = SCHEMA.get(key)
            if sdef and sdef.cura_key:
                merged[key] = value

    return merged


def _object_flat(stack: SettingsStack, body_id: str) -> dict[str, Any]:
    """
    Return the per-body override settings for a specific body, translated to
    cura keys.
    """
    if not stack.object_layer.has_body(body_id):
        return {}
    body_layer = stack.object_layer.body(body_id)
    out = {}
    for key, value in body_layer.items():
        sdef = SCHEMA.get(key)
        if sdef and sdef.cura_key:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_machine_def(stack: SettingsStack, path: Path | str) -> Path:
    """
    Write machine.def.json for the given stack.
    Returns the path written.
    """
    path = Path(path)
    machine_name = stack.machine_layer.get("machine_name") or "Generic FDM Printer"
    flat = _machine_flat(stack)

    definition = {
        "name": machine_name,
        "version": _DEF_VERSION,
        "metadata": {
            "type": "machine",
            "setting_version": _SETTING_VERSION,
            "author": _AUTHOR,
        },
        # CuraEngine 4.x requires inheriting from fdmprinter
        "inherits": "fdmprinter",
        "overrides": _overrides_block(flat),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(definition, f, indent=2, ensure_ascii=False)

    return path


def write_profile_def(
    stack: SettingsStack,
    path: Path | str,
    machine_def_path: Path | str,
) -> Path:
    """
    Write profile.def.json — the collapsed user-layer override profile.
    Inherits from machine_def_path.
    Returns the path written.
    """
    path = Path(path)
    flat = _profile_flat(stack)

    definition = {
        "name": "CuraRebuild Profile",
        "version": _DEF_VERSION,
        "metadata": {
            "type": "quality_changes",
            "setting_version": _SETTING_VERSION,
            "author": _AUTHOR,
        },
        "inherits": str(Path(machine_def_path).stem),
        "overrides": _overrides_block(flat),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(definition, f, indent=2, ensure_ascii=False)

    return path


def write_object_def(
    stack: SettingsStack,
    body_id: str,
    path: Path | str,
    profile_def_path: Path | str,
) -> Path | None:
    """
    Write a per-mesh override definition for one body.
    Returns the path written, or None if the body has no overrides.
    """
    flat = _object_flat(stack, body_id)
    if not flat:
        return None

    path = Path(path)
    definition = {
        "name": f"Object overrides: {body_id}",
        "version": _DEF_VERSION,
        "metadata": {
            "type": "quality_changes",
            "setting_version": _SETTING_VERSION,
            "author": _AUTHOR,
        },
        "inherits": str(Path(profile_def_path).stem),
        "overrides": _overrides_block(flat),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(definition, f, indent=2, ensure_ascii=False)

    return path


def write_extruder_def(
    flat: dict,
    extruder_idx: int,
    path: Path | str,
    machine_def_path: Path | str,
) -> Path:
    """
    Write an extruder definition for CuraEngine 4.x.

    CuraEngine 4.x extruder defs use type "extruder_train" and must contain
    extruder_nr to identify which extruder they configure.
    They do NOT inherit from the machine def.
    """
    path = Path(path)

    # extruder_nr must be in the overrides to tell CuraEngine which extruder
    overrides = _overrides_block(flat)
    overrides["extruder_nr"] = {"default_value": extruder_idx}

    # Required settings for CuraEngine 4.x extruder train
    overrides.setdefault( "machine_extruder_cooling_fan_number",
                          {"default_value": extruder_idx} )
    overrides.setdefault( "extruder_prime_pos_x",  {"default_value": 0} )
    overrides.setdefault( "extruder_prime_pos_y",  {"default_value": 0} )
    overrides.setdefault( "extruder_prime_pos_abs", {"default_value": False} )
    overrides.setdefault( "machine_nozzle_offset_x", {"default_value": 0.0} )
    overrides.setdefault( "machine_nozzle_offset_y", {"default_value": 0.0} )

    definition = {
        "name": f"CuraRebuild Extruder {extruder_idx}",
        "version": _DEF_VERSION,
        "metadata": {
            "type": "extruder_train",
            "setting_version": _SETTING_VERSION,
            "author": _AUTHOR,
            "position": str(extruder_idx),
            "machine": str( Path(machine_def_path).stem ),
        },
        # Must inherit fdmextruder so CuraEngine finds all required extruder settings
        "inherits": "fdmextruder",
        "overrides": overrides,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(definition, f, indent=2, ensure_ascii=False)
    return path


def write_all_defs(
    stack: SettingsStack,
    output_dir: Path | str,
    body_ids: list[str] | None = None,
    fp_map: dict | None = None,
) -> dict[str, Path]:
    """
    Write machine.def.json, per-extruder profile defs, and optionally
    per-body def files into output_dir.

    fp_map: dict of layer_id → FP object for ApplyTo resolution.

    Returns a dict:
        {
            "machine":       Path,
            "extruder_0":    Path,   # one per extruder
            "extruder_1":    Path,
            ...
            "<body_id>":     Path,   # one per body with overrides
        }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    machine_path = output_dir / "machine.def.json"
    write_machine_def(stack, machine_path)

    result: dict[str, Path] = { "machine": machine_path }

    # Determine enabled extruders from machine layer
    n_extruders = max( 1, stack.extruder_count() )
    enabled_raw = stack.machine_layer.get( "_fc_enabled_extruders" )
    if enabled_raw is not None:
        try:
            enabled_set = { int(x.strip())
                            for x in str(enabled_raw).split(",")
                            if x.strip() }
        except ValueError:
            enabled_set = set( range( n_extruders ) )
    else:
        enabled_set = set( range( n_extruders ) )   # all enabled by default

    # Write one profile per extruder
    for idx in range( n_extruders ):
        if idx not in enabled_set:
            continue   # skip disabled extruders
        flat         = stack.resolve_for_extruder( idx, fp_map=fp_map )
        # Exclude machine-home settings — those are already in machine.def.json
        profile_flat = {
            k: v for k, v in flat.items()
            if SCHEMA.get(k) and SCHEMA[k].cura_key
            and SCHEMA[k].home_layer != LayerRole.MACHINE
        }
        ext_path = output_dir / f"extruder_{idx}.def.json"
        write_extruder_def( profile_flat, idx, ext_path, machine_path )
        result[ f"extruder_{idx}" ] = ext_path

    # Also write a merged profile.def.json for backward compat
    profile_path = output_dir / "profile.def.json"
    write_profile_def(stack, profile_path, machine_path)
    result["profile"] = profile_path

    for body_id in (body_ids or []):
        obj_path = output_dir / f"object_{_safe_id(body_id)}.def.json"
        written = write_object_def(stack, body_id, obj_path, profile_path)
        if written:
            result[body_id] = written

    return result


# ---------------------------------------------------------------------------
# CLI args builder (for CuraEngine < 5.x that uses -j / -s flags)
# ---------------------------------------------------------------------------

def build_cura_args(
    cura_bin: str,
    machine_def: Path,
    profile_def: Path,
    stl_paths: list[Path],
    gcode_output: Path,
    extra_settings: dict[str, Any] | None = None,
    extra_defs: list[Path] | None = None,
) -> list[str]:
    """
    Build the subprocess argument list for CuraEngine 4.x / 5.x.

    CuraEngine slice -j machine.def.json -j extruder_0.def.json [-j extruder_1...]
                     -l model.stl -o output.gcode
                     [-s key=value ...]
    """
    args = [
        cura_bin,
        "slice",
        "-j", str(machine_def),
        "-j", str(profile_def),
    ]

    for extra in (extra_defs or []):
        args += ["-j", str(extra)]

    for stl in stl_paths:
        args += ["-l", str(stl)]

    args += ["-o", str(gcode_output)]

    # Any remaining settings that aren't in the def files
    for key, value in (extra_settings or {}).items():
        sdef = SCHEMA.get(key)
        cura_key = sdef.cura_key if sdef else key
        if not cura_key:
            continue
        if isinstance(value, bool):
            args += ["-s", f"{cura_key}={'true' if value else 'false'}"]
        else:
            args += ["-s", f"{cura_key}={value}"]

    return args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_id(s: str) -> str:
    """Make a string safe for use as a filename component."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)
