#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# storage.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   JSON import/export backend for settings layers.
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

import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .schema import SCHEMA, SettingDef
from .stack import (
    BaseLayer,
    MachineLayer,
    UserLayer,
    ObjectLayer,
    SettingsStack,
    SettingsRegistry,
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class StorageBackend(Protocol):
    """Minimal interface every backend must implement."""

    def save_registry(self, registry: SettingsRegistry) -> None: ...
    def load_registry(self) -> SettingsRegistry: ...

    def save_stack_wiring(self, stack_id: str, stack: SettingsStack) -> None: ...
    def load_stack_wiring(self, stack_id: str,
                          registry: SettingsRegistry) -> SettingsStack: ...


# ---------------------------------------------------------------------------
# JSON backend
# ---------------------------------------------------------------------------

class JsonBackend:
    """
    Persists everything under a single root directory:

        <root>/
            registry.json          — all MachineLayer + UserLayer content
            stacks/<stack_id>.json — SettingsStack wiring + ObjectLayer
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "stacks").mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Registry

    def save_registry(self, registry: SettingsRegistry) -> None:
        path = self.root / "registry.json"
        data = registry.to_plain_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_registry(self) -> SettingsRegistry:
        path = self.root / "registry.json"
        if not path.exists():
            return SettingsRegistry()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SettingsRegistry.from_plain_dict(data)

    # ------------------------------------------------------------------
    # Stack wiring + ObjectLayer

    def save_stack_wiring(self, stack_id: str, stack: SettingsStack) -> None:
        path = self.root / "stacks" / f"{stack_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stack.to_plain_dict(), f, indent=2, ensure_ascii=False)

    def load_stack_wiring(
        self, stack_id: str, registry: SettingsRegistry
    ) -> SettingsStack:
        path = self.root / "stacks" / f"{stack_id}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No saved stack found for id '{stack_id}' at {path}"
            )
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SettingsStack.from_plain_dict(data, registry)

    # ------------------------------------------------------------------
    # Convenience: export a single layer as a standalone JSON
    # (useful for sharing machine/material configs)

    def export_layer(self, layer: BaseLayer, path: Path | str) -> None:
        with open(Path(path), "w", encoding="utf-8") as f:
            json.dump(layer.to_plain_dict(), f, indent=2, ensure_ascii=False)

    def import_layer(self, path: Path | str) -> BaseLayer:
        with open(Path(path), "r", encoding="utf-8") as f:
            data = json.load(f)
        type_name = data.get("type", "UserLayer")
        if type_name == "MachineLayer":
            return MachineLayer.from_plain_dict(data)
        return UserLayer.from_plain_dict(data)

    # ------------------------------------------------------------------
    # Convenience: export a fully-resolved effective dict
    # (for debugging or feeding into external tools)

    def export_effective(
        self,
        stack: SettingsStack,
        path: Path | str,
        body_id: str | None = None,
    ) -> None:
        effective = stack.effective_exportable(body_id=body_id)
        with open(Path(path), "w", encoding="utf-8") as f:
            json.dump(effective, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# FreeCAD backend
# ---------------------------------------------------------------------------

_FC_PARAM_ROOT = "User parameter:BaseApp/Preferences/Mod/CuraRebuild"
_MACHINE_NS    = f"{_FC_PARAM_ROOT}/Registry/Machines"
_USER_NS       = f"{_FC_PARAM_ROOT}/Registry/Users"
_STACK_NS      = f"{_FC_PARAM_ROOT}/Stacks"


def _fc_param():
    """Import FreeCAD lazily so this module stays importable without FreeCAD."""
    import FreeCAD
    return FreeCAD.ParamGet


class FreeCADBackend:
    """
    Persists registry and stacks in FreeCAD's XML parameter store.

    Namespace layout:
        .../Registry/Machines/<layer_id>/
            __name__    (string)
            <key>       (string or float depending on dtype)

        .../Registry/Users/<layer_id>/
            __name__    (string)
            <key>

        .../Stacks/<stack_id>/
            __machine_id__    (string)
            __user_ids__      (string — comma-separated ordered list)
            ObjectLayer/<body_id>/<key>
    """

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _grp(path: str):
        import FreeCAD
        return FreeCAD.ParamGet(path)

    @staticmethod
    def _write_layer_to_grp(layer: BaseLayer, grp) -> None:
        grp.SetString("__name__", layer.name)
        for key, value in layer.items():
            sdef = SCHEMA.get(key)
            if sdef is None:
                continue
            if sdef.dtype == str:
                grp.SetString(key, str(value))
            elif sdef.dtype == bool:
                grp.SetBool(key, bool(value))
            elif sdef.dtype == int:
                grp.SetInt(key, int(value))
            else:  # float
                grp.SetFloat(key, float(value))

    @staticmethod
    def _read_layer_from_grp(layer: BaseLayer, grp) -> None:
        layer.name = grp.GetString("__name__", layer.name)
        for key, sdef in SCHEMA.items():
            # Check presence: FreeCAD uses sentinel-value trick
            if sdef.dtype == str:
                sentinel = "\x00__absent__\x00"
                val = grp.GetString(key, sentinel)
                if val != sentinel:
                    try:
                        layer.set(key, val)
                    except Exception:
                        pass
            elif sdef.dtype == bool:
                # No native "absent" check for bool; use a string flag
                flag = grp.GetString(f"__isset__{key}", "")
                if flag == "1":
                    val = grp.GetBool(key, sdef.default)
                    try:
                        layer.set(key, val)
                    except Exception:
                        pass
            elif sdef.dtype == int:
                sentinel = -(2**31)
                val = grp.GetInt(key, sentinel)
                if val != sentinel:
                    try:
                        layer.set(key, val)
                    except Exception:
                        pass
            else:  # float
                sentinel = -1e300
                val = grp.GetFloat(key, sentinel)
                if val != sentinel:
                    try:
                        layer.set(key, val)
                    except Exception:
                        pass

    @staticmethod
    def _write_bool_layer_to_grp(layer: BaseLayer, grp) -> None:
        """Extra pass to properly store bool presence flags."""
        for key, value in layer.items():
            sdef = SCHEMA.get(key)
            if sdef and sdef.dtype == bool:
                grp.SetBool(key, bool(value))
                grp.SetString(f"__isset__{key}", "1")

    # ------------------------------------------------------------------
    # Registry

    def save_registry(self, registry: SettingsRegistry) -> None:
        param_grp = self._grp

        for layer in registry.all_machine_layers():
            grp = param_grp(f"{_MACHINE_NS}/{layer.id}")
            self._write_layer_to_grp(layer, grp)
            self._write_bool_layer_to_grp(layer, grp)

        for layer in registry.all_user_layers():
            grp = param_grp(f"{_USER_NS}/{layer.id}")
            self._write_layer_to_grp(layer, grp)
            self._write_bool_layer_to_grp(layer, grp)

    def load_registry(self) -> SettingsRegistry:
        import FreeCAD
        registry = SettingsRegistry()
        param_grp = self._grp

        machines_grp = param_grp(_MACHINE_NS)
        # Iterate sub-groups — FreeCAD doesn't expose a list-children API
        # directly, so we persist a manifest of ids as a comma-separated string.
        machine_ids = param_grp(_FC_PARAM_ROOT).GetString(
            "__machine_ids__", ""
        )
        for lid in [i.strip() for i in machine_ids.split(",") if i.strip()]:
            layer = MachineLayer(name=lid, layer_id=lid)
            grp = param_grp(f"{_MACHINE_NS}/{lid}")
            self._read_layer_from_grp(layer, grp)
            registry.add_machine_layer(layer)

        user_ids = param_grp(_FC_PARAM_ROOT).GetString("__user_ids__", "")
        for lid in [i.strip() for i in user_ids.split(",") if i.strip()]:
            layer = UserLayer(name=lid, layer_id=lid)
            grp = param_grp(f"{_USER_NS}/{lid}")
            self._read_layer_from_grp(layer, grp)
            registry.add_user_layer(layer)

        return registry

    def save_registry_manifest(self, registry: SettingsRegistry) -> None:
        """Write the id manifests so load_registry can enumerate sub-groups."""
        root_grp = self._grp(_FC_PARAM_ROOT)
        machine_ids = ",".join(l.id for l in registry.all_machine_layers())
        user_ids    = ",".join(l.id for l in registry.all_user_layers())
        root_grp.SetString("__machine_ids__", machine_ids)
        root_grp.SetString("__user_ids__",    user_ids)

    def save_registry_full(self, registry: SettingsRegistry) -> None:
        """save_registry + manifest in one call."""
        self.save_registry(registry)
        self.save_registry_manifest(registry)

    # ------------------------------------------------------------------
    # Stack wiring

    def save_stack_wiring(self, stack_id: str, stack: SettingsStack) -> None:
        param_grp = self._grp
        grp = param_grp(f"{_STACK_NS}/{stack_id}")
        grp.SetString("__machine_id__", stack.machine_layer.id)
        grp.SetString(
            "__user_ids__",
            ",".join(l.id for l in stack.user_layers)
        )
        # ObjectLayer
        for body_id in stack.object_layer.all_body_ids():
            body_grp = param_grp(
                f"{_STACK_NS}/{stack_id}/ObjectLayer/{body_id}"
            )
            body_layer = stack.object_layer.body(body_id)
            self._write_layer_to_grp(body_layer, body_grp)
            self._write_bool_layer_to_grp(body_layer, body_grp)

        # Write body_id manifest
        grp.SetString(
            "__body_ids__",
            ",".join(stack.object_layer.all_body_ids())
        )

    def load_stack_wiring(
        self, stack_id: str, registry: SettingsRegistry
    ) -> SettingsStack:
        param_grp = self._grp
        grp = param_grp(f"{_STACK_NS}/{stack_id}")

        machine_id = grp.GetString("__machine_id__", "")
        if not machine_id:
            raise ValueError(
                f"Stack '{stack_id}' has no machine layer id in param store."
            )
        machine = registry.get_machine_layer(machine_id)

        user_id_str = grp.GetString("__user_ids__", "")
        user_layers = [
            registry.get_user_layer(lid)
            for lid in [i.strip() for i in user_id_str.split(",") if i.strip()]
        ]

        object_layer = ObjectLayer()
        body_id_str = grp.GetString("__body_ids__", "")
        for body_id in [i.strip() for i in body_id_str.split(",") if i.strip()]:
            body_layer = object_layer.body(body_id)
            body_grp = param_grp(
                f"{_STACK_NS}/{stack_id}/ObjectLayer/{body_id}"
            )
            self._read_layer_from_grp(body_layer, body_grp)

        return SettingsStack(machine, user_layers, object_layer)


# ---------------------------------------------------------------------------
# Compound backend
# ---------------------------------------------------------------------------

class CompoundBackend:
    """
    Uses FreeCADBackend as the live runtime store and JsonBackend as the
    import/export surface.  This is the backend the workbench uses.
    """

    def __init__(self, json_root: Path | str):
        self.json = JsonBackend(json_root)
        self.fc   = FreeCADBackend()

    # Delegate runtime operations to FreeCAD
    def save_registry(self, registry: SettingsRegistry) -> None:
        self.fc.save_registry_full(registry)

    def load_registry(self) -> SettingsRegistry:
        return self.fc.load_registry()

    def save_stack_wiring(self, stack_id: str, stack: SettingsStack) -> None:
        self.fc.save_stack_wiring(stack_id, stack)

    def load_stack_wiring(self, stack_id: str,
                          registry: SettingsRegistry) -> SettingsStack:
        return self.fc.load_stack_wiring(stack_id, registry)

    # JSON import/export
    def export_registry(self, registry: SettingsRegistry) -> None:
        self.json.save_registry(registry)

    def import_registry(self) -> SettingsRegistry:
        return self.json.load_registry()

    def export_layer(self, layer: BaseLayer, path: Path | str) -> None:
        self.json.export_layer(layer, path)

    def import_layer(self, path: Path | str) -> BaseLayer:
        return self.json.import_layer(path)

    def export_effective(
        self,
        stack: SettingsStack,
        path: Path | str,
        body_id: str | None = None,
    ) -> None:
        self.json.export_effective(stack, path, body_id)
