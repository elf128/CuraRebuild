#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# stack.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   BaseLayer, MachineLayer, UserLayer, and SettingsStack.
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

import copy
import uuid
from typing import Any, Iterator

from settings.schema import SCHEMA, SettingDef, LayerRole, get_default, exportable_keys, get_registry as _get_schema_registry


def _active_schema() -> dict:
    """Return the live schema dict, falling back to hardcoded SCHEMA."""
    try:
        return _get_schema_registry().schema
    except Exception:
        return SCHEMA


# ---------------------------------------------------------------------------
# Individual layer types
# ---------------------------------------------------------------------------

class BaseLayer:
    """
    A SPARSE dict of setting overrides — only settings explicitly set by
    the user. Opening an editor or creating a new layer does NOT populate
    all 575 schema settings.

    Two internal buckets:
      _data        — validated typed values  (int / float / bool / str)
      _expressions — custom formula strings  (e.g. "machine_nozzle_size / 2")

    JSON format (structured by category label):
    {
      "id":   "...",
      "name": "My Layer",
      "type": "UserLayer",
      "settings": {
        "Quality": {
          "layer_height": 0.1
        },
        "Material": {
          "material_print_temperature": "material_bed_temperature * 2.5"
        }
      }
    }
    String values = custom expressions (stored in _expressions).
    """

    def __init__( self, name: str, layer_id: str | None = None ):
        self.name: str                    = name
        self.id: str                      = layer_id or str( uuid.uuid4() )
        self._data:        dict[str, Any] = {}
        self._expressions: dict[str, str] = {}
        self._linked_path: str | None     = None

    # ------------------------------------------------------------------
    # Core access

    def set( self, key: str, value: Any ) -> None:
        """
        Store a value for key.
        If value is a non-empty string that cannot be cast to the key's dtype,
        it is stored as a custom expression in _expressions.
        Always validates typed values against the schema.
        Flushes to linked file after writing.
        """
        schema = _active_schema()
        if key not in schema:
            raise KeyError( f"Unknown setting key: '{key}'" )
        sdef = schema[ key ]

        if isinstance( value, str ) and sdef.dtype != str:
            try:
                parsed = sdef.dtype( value )
                self._data[ key ] = parsed
                self._expressions.pop( key, None )
            except (ValueError, TypeError):
                # Store as custom expression
                self._expressions[ key ] = value
                self._data.pop( key, None )
        else:
            self._data[ key ] = sdef.safe_validate( value )
            self._expressions.pop( key, None )

        if self._linked_path:
            self.flush_to_file()

    def set_expression( self, key: str, expr: str ) -> None:
        """Explicitly store a custom formula for key."""
        schema = _active_schema()
        if key not in schema:
            raise KeyError( f"Unknown setting key: '{key}'" )
        self._expressions[ key ] = expr
        self._data.pop( key, None )
        if self._linked_path:
            self.flush_to_file()

    def get( self, key: str ) -> Any | None:
        """Return value/expression for key, or None if not set in this layer."""
        if key in self._data:
            return self._data[ key ]
        return self._expressions.get( key )

    def get_typed( self, key: str ) -> Any | None:
        """Return only typed (non-expression) value, or None."""
        return self._data.get( key )

    def get_expression( self, key: str ) -> str | None:
        """Return custom formula string for key, or None."""
        return self._expressions.get( key )

    def has( self, key: str ) -> bool:
        return key in self._data or key in self._expressions

    def has_expression( self, key: str ) -> bool:
        return key in self._expressions

    def delete( self, key: str ) -> None:
        self._data.pop( key, None )
        self._expressions.pop( key, None )
        if self._linked_path:
            self.flush_to_file()

    def clear( self ) -> None:
        self._data.clear()
        self._expressions.clear()

    def keys( self ) -> list[str]:
        return list( set( self._data.keys() ) | set( self._expressions.keys() ) )

    def items( self ) -> Iterator[tuple[str, Any]]:
        return iter( { **self._data, **self._expressions }.items() )

    def as_dict( self ) -> dict[str, Any]:
        """Flat copy including expressions as strings."""
        d = dict( self._data )
        d.update( self._expressions )
        return d

    # ------------------------------------------------------------------
    # Linked file support

    @property
    def linked_path( self ) -> str | None:
        return self._linked_path

    def link( self, path: str | None ) -> None:
        self._linked_path = str( path ) if path else None

    def is_linked( self ) -> bool:
        return bool( self._linked_path )

    def flush_to_file( self ) -> None:
        """Write structured layer JSON to the linked file."""
        if not self._linked_path:
            return
        from pathlib import Path as _Path
        import json as _json
        try:
            p = _Path( self._linked_path )
            p.parent.mkdir( parents=True, exist_ok=True )
            p.write_text(
                _json.dumps( self.to_plain_dict(), indent=2, ensure_ascii=False ),
                encoding="utf-8",
            )
        except Exception as e:
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[BaseLayer] flush_to_file failed: { e }\n" )

    def reload_from_file( self ) -> bool:
        """Reload from linked file. Returns True on success."""
        if not self._linked_path:
            return False
        from pathlib import Path as _Path
        import json as _json
        try:
            p = _Path( self._linked_path )
            if not p.exists():
                return False
            data = _json.loads( p.read_text( encoding="utf-8" ) )
            self._load_from_dict( data )
            return True
        except Exception as e:
            from Common import Log, LogLevel
            Log( LogLevel.warning,
                f"[BaseLayer] reload_from_file failed: { e }\n" )
            return False

    # ------------------------------------------------------------------
    # Serialization

    def to_plain_dict( self ) -> dict:
        """
        Structured JSON representation grouped by category label.
        String values = custom expressions.
        Does NOT include linked_path (use to_registry_dict for that).
        """
        schema = _active_schema()

        # Build category → {key: value} mapping
        by_cat: dict[str, dict] = {}
        all_keys = set( self._data.keys() ) | set( self._expressions.keys() )
        for key in sorted( all_keys ):
            sdef = schema.get( key )
            cat  = sdef.category if sdef else "General"
            val  = self._expressions[ key ] if key in self._expressions                    else self._data[ key ]
            by_cat.setdefault( cat, {} )[ key ] = val

        return {
            "id":       self.id,
            "name":     self.name,
            "type":     self.__class__.__name__,
            "settings": by_cat,
        }

    def to_registry_dict( self ) -> dict:
        """Like to_plain_dict() but includes linked_path."""
        d = self.to_plain_dict()
        if self._linked_path:
            d["linked_path"] = self._linked_path
        return d

    def _load_from_dict( self, d: dict ) -> None:
        """Load from a structured dict (clears existing data first)."""
        self._data.clear()
        self._expressions.clear()
        if "name" in d:
            self.name = d["name"]

        # Structured format: {"settings": {"Category": {"key": val}}}
        settings = d.get( "settings", {} )
        if isinstance( settings, dict ):
            for cat_vals in settings.values():
                if not isinstance( cat_vals, dict ):
                    continue
                for k, v in cat_vals.items():
                    try:
                        self.set( k, v )
                    except (KeyError, TypeError, ValueError):
                        pass

    @classmethod
    def from_plain_dict( cls, d: dict ) -> "BaseLayer":
        layer = cls( name=d.get("name", "Layer"), layer_id=d.get("id") )
        layer._linked_path = d.get( "linked_path" )
        layer._load_from_dict( d )
        return layer

    def __repr__( self ) -> str:
        return (
            f"{ self.__class__.__name__ }("
            f"name={ self.name!r }, "
            f"keys={ len( self._data ) + len( self._expressions ) })"
        )


class MachineLayer(BaseLayer):
    """
    Layer 0 — hardware definition.
    Lives in the SettingsRegistry; BuildVolumes reference it by id.
    """
    def __getstate__( self ): return "MachineLayer"
    def __setstate__( self, state ): pass


class UserLayer(BaseLayer):
    """
    Intermediate layer — user-named, contains whatever settings the user puts here.
    Lives in the SettingsRegistry; BuildVolumes reference it by id and position.
    """
    def __getstate__( self ): return "UserLayer"
    def __setstate__( self, state ): pass


class ObjectLayer:
    """
    Top-of-stack layer — per-body overrides, always local to one SettingsStack.
    Internally a dict[body_id → BaseLayer].
    """

    def __init__(self):
        self._bodies: dict[str, BaseLayer] = {}

    def body(self, body_id: str) -> BaseLayer:
        """Return (and lazily create) the override layer for a specific body."""
        if body_id not in self._bodies:
            self._bodies[body_id] = BaseLayer(name=f"object:{body_id}",
                                              layer_id=body_id)
        return self._bodies[body_id]

    def has_body(self, body_id: str) -> bool:
        return body_id in self._bodies

    def remove_body(self, body_id: str) -> None:
        self._bodies.pop(body_id, None)

    def all_body_ids(self) -> list[str]:
        return list(self._bodies.keys())

    def to_plain_dict(self) -> dict:
        return {
            "type": "ObjectLayer",
            "bodies": {bid: layer.to_plain_dict()
                       for bid, layer in self._bodies.items()},
        }

    @classmethod
    def from_plain_dict(cls, d: dict) -> "ObjectLayer":
        ol = cls()
        for bid, layer_dict in d.get("bodies", {}).items():
            ol._bodies[bid] = BaseLayer.from_plain_dict(layer_dict)
        return ol

    def __repr__(self) -> str:
        return f"ObjectLayer(bodies={list(self._bodies.keys())})"


# ---------------------------------------------------------------------------
# SettingsStack
# ---------------------------------------------------------------------------

class SettingsStack:
    """
    An ordered resolution stack owned by a single BuildVolume.

    Structure:
        machine_layer           — reference to a MachineLayer in the registry
        user_layers[0..N]       — ordered references to UserLayers in the registry
        object_layer            — local ObjectLayer (not shared)

    Resolution for a given key (and optional body_id):
        1. object_layer[body_id]  (if body_id given and body defines the key)
        2. user_layers[-1]        (highest user layer wins)
           ...
        3. user_layers[0]
        4. machine_layer
        5. schema default         (fallback, always defined)
    """

    def __init__(
        self,
        machine_layer: MachineLayer,
        user_layers: list[UserLayer] | None = None,
        object_layer: ObjectLayer | None = None,
    ):
        self._machine: MachineLayer = machine_layer
        self._user: list[UserLayer] = list(user_layers or [])
        self._object: ObjectLayer = object_layer or ObjectLayer()

    # ------------------------------------------------------------------
    # Layer management

    @property
    def machine_layer(self) -> MachineLayer:
        return self._machine

    @machine_layer.setter
    def machine_layer(self, layer: MachineLayer) -> None:
        self._machine = layer

    @property
    def user_layers(self) -> list[UserLayer]:
        return self._user

    @property
    def object_layer(self) -> ObjectLayer:
        return self._object

    def append_user_layer(self, layer: UserLayer) -> None:
        """Add a user layer at the top of the user stack (highest priority)."""
        if self._find_user_layer_index(layer.id) is not None:
            raise ValueError(f"Layer '{layer.id}' is already in this stack.")
        self._user.append(layer)

    def insert_user_layer(self, index: int, layer: UserLayer) -> None:
        """Insert a user layer at a specific position (0 = lowest priority)."""
        if self._find_user_layer_index(layer.id) is not None:
            raise ValueError(f"Layer '{layer.id}' is already in this stack.")
        self._user.insert(index, layer)

    def remove_user_layer(self, layer_id: str) -> None:
        idx = self._find_user_layer_index(layer_id)
        if idx is None:
            raise KeyError(f"Layer '{layer_id}' not found in stack.")
        self._user.pop(idx)

    def move_user_layer(self, layer_id: str, new_index: int) -> None:
        """Reorder a user layer to a new position (0 = lowest priority)."""
        idx = self._find_user_layer_index(layer_id)
        if idx is None:
            raise KeyError(f"Layer '{layer_id}' not found in stack.")
        layer = self._user.pop(idx)
        self._user.insert(new_index, layer)

    def _find_user_layer_index(self, layer_id: str) -> int | None:
        for i, l in enumerate(self._user):
            if l.id == layer_id:
                return i
        return None

    def get_user_layer(self, layer_id: str) -> UserLayer:
        idx = self._find_user_layer_index(layer_id)
        if idx is None:
            raise KeyError(f"Layer '{layer_id}' not found in stack.")
        return self._user[idx]

    # ------------------------------------------------------------------
    # Value resolution

    def get(self, key: str, body_id: str | None = None) -> Any:
        """
        Resolve the effective value for a setting key.

        Resolution order (first hit wins):
            1. ObjectLayer[body_id]  — if body_id provided
            2. user_layers highest → lowest
            3. machine_layer
            4. schema default
        """
        if key not in _active_schema():
            raise KeyError(f"Unknown setting key: '{key}'")

        # 1. Per-object override
        if body_id is not None and self._object.has_body(body_id):
            v = self._object.body(body_id).get(key)
            if v is not None:
                return v

        # 2. User layers (highest index = highest priority)
        for layer in reversed(self._user):
            v = layer.get(key)
            if v is not None:
                return v

        # 3. Machine layer
        v = self._machine.get(key)
        if v is not None:
            return v

        # 4. Schema default
        return get_default(key)

    def set(self, key: str, value: Any, layer_id: str) -> None:
        """
        Write a value into a specific layer identified by layer_id.
        layer_id must match the machine layer's id, one of the user layers' ids,
        or the special string "__object__:<body_id>".
        """
        if key not in _active_schema():
            raise KeyError(f"Unknown setting key: '{key}'")

        if layer_id == self._machine.id:
            self._machine.set(key, value)
            return

        idx = self._find_user_layer_index(layer_id)
        if idx is not None:
            self._user[idx].set(key, value)
            return

        if layer_id.startswith("__object__:"):
            body_id = layer_id[len("__object__:"):]
            self._object.body(body_id).set(key, value)
            return

        raise KeyError(f"Layer id '{layer_id}' not found in stack.")

    # ------------------------------------------------------------------
    # Bulk resolution

    def effective(self, body_id: str | None = None) -> dict[str, Any]:
        """
        Return a fully-resolved flat dict of all known settings for a given
        body (or the base print if body_id is None).
        This is the dict that cura_export.py will consume.

        For settings with a value_expr that no layer explicitly sets,
        the formula is evaluated against the resolved dict so derived
        settings like support_line_distance reflect changes to their
        source settings (e.g. support_infill_rate).
        """
        from settings.expr_eval import eval_value
        schema = _active_schema()

        # First pass: resolve all values from layers / schema defaults
        result = {}
        for key in schema:
            result[key] = self.get(key, body_id=body_id)

        # Second pass: evaluate value_expr ONLY for numeric settings that:
        # 1. No layer explicitly sets
        # 2. Have a purely numeric formula (not referencing extruderValue etc.)
        # 3. Return a proper numeric value (not a string)
        # This handles derived settings like support_line_distance that depend
        # on user-set values like support_infill_rate.
        _NUMERIC_TYPES = ( int, float )
        for key, sdef in schema.items():
            if not sdef.value_expr:
                continue
            if sdef.dtype not in _NUMERIC_TYPES:
                continue
            # Skip if any layer explicitly sets this key
            if any( l.has(key) for l in self._user ) or self._machine.has(key):
                continue
            # Skip formulas that reference extruder functions — these need
            # the full Cura resolver and produce unreliable results here
            expr = sdef.value_expr
            if any( fn in expr for fn in (
                "extruderValue", "extruderValues", "resolveOrValue",
                "valueFromContainer", "valueFromExtruderIndex",
                "defaultExtruderPosition", "anyExtruder",
            ) ):
                continue
            computed = eval_value( expr, result, sdef.dtype )
            if computed is None:
                continue
            # Only apply if computed value differs from schema default
            # (avoids no-op updates and catches evaluation failures)
            if computed != sdef.default:
                result[key] = computed

        return result

    def effective_exportable(self, body_id: str | None = None) -> dict[str, Any]:
        """Like effective() but only includes keys that CuraEngine accepts."""
        full = self.effective(body_id=body_id)
        schema = _active_schema()
        return {k: v for k, v in full.items() if schema.get(k) and schema[k].cura_key}

    def resolve_for_extruder(
        self,
        extruder_idx: int,
        fp_map: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Resolve effective settings for a specific extruder index.

        User layers are filtered by their ApplyTo value (read from fp_map,
        a dict of layer_id → FP object). Layers whose ApplyTo doesn't include
        extruder_idx are skipped for this extruder.

        Machine layer always contributes (global).
        Returns a fully resolved flat dict for this extruder.
        """
        # fp_map: layer_id → FP document object (optional, for ApplyTo lookup)
        fp_map = fp_map or {}

        def _applies( layer ) -> bool:
            fp = fp_map.get( layer.id )
            if fp is None:
                return True   # no FP = no ApplyTo filter = applies to all
            apply_to = getattr( fp, "ApplyTo", "all" ).strip().lower()
            if not apply_to or apply_to == "all":
                return True
            try:
                indices = { int( x.strip() ) for x in apply_to.split( "," ) if x.strip() }
                return extruder_idx in indices
            except ValueError:
                return True

        # Build a filtered stack for this extruder
        filtered_users = [ l for l in self._user if _applies( l ) ]
        filtered_stack = SettingsStack(
            self._machine,
            filtered_users,
            self._object,
        )
        return filtered_stack.effective()

    def extruder_count( self ) -> int:
        """Return machine_extruder_count from the machine layer (default 1)."""
        try:
            return int( self._machine.get( "machine_extruder_count" ) or 1 )
        except (TypeError, ValueError):
            return 1

    def diff_from_defaults(self) -> dict[str, Any]:
        """
        Return only the settings whose effective value differs from the schema
        default. Useful for producing minimal JSON exports.
        """
        result = {}
        schema = _active_schema()
        for key in schema:
            val = self.get(key)
            if val != get_default(key):
                result[key] = val
        return result

    # ------------------------------------------------------------------
    # Introspection

    def which_layer(self, key: str, body_id: str | None = None) -> str:
        """
        Return the name of the layer that is providing the effective value
        for this key. Returns "schema_default" if nothing overrides it.
        """
        if body_id is not None and self._object.has_body(body_id):
            if self._object.body(body_id).has(key):
                return f"object:{body_id}"

        for layer in reversed(self._user):
            if layer.has(key):
                return f"user:{layer.name}"

        if self._machine.has(key):
            return f"machine:{self._machine.name}"

        return "schema_default"

    def layer_summary(self) -> list[dict]:
        """
        Return a summary of all layers in resolution order (high → low)
        for display in a UI layer panel.
        """
        rows = []
        rows.append({
            "role": "object",
            "name": "Object Overrides",
            "id": "__object__",
            "body_count": len(self._object.all_body_ids()),
        })
        for layer in reversed(self._user):
            rows.append({
                "role": "user",
                "name": layer.name,
                "id": layer.id,
                "key_count": len(layer.keys()),
            })
        rows.append({
            "role": "machine",
            "name": self._machine.name,
            "id": self._machine.id,
            "key_count": len(self._machine.keys()),
        })
        return rows

    # ------------------------------------------------------------------
    # Serialisation (the stack structure, not layer content)
    # Layer content is serialised by the SettingsRegistry / storage backends.

    def to_plain_dict(self) -> dict:
        """
        Serialise just the stack's wiring: which machine + which user layers
        in which order. Layer content lives in the registry.
        """
        return {
            "machine_layer_id": self._machine.id,
            "user_layer_ids": [l.id for l in self._user],
            "object_layer": self._object.to_plain_dict(),
        }

    @classmethod
    def from_plain_dict(
        cls,
        d: dict,
        registry: "SettingsRegistry",
    ) -> "SettingsStack":
        """
        Reconstruct a SettingsStack from its serialised form, resolving
        layer references against the provided registry.
        """
        machine = registry.get_machine_layer(d["machine_layer_id"])
        user_layers = [
            registry.get_user_layer(lid)
            for lid in d.get("user_layer_ids", [])
        ]
        object_layer = ObjectLayer.from_plain_dict(d.get("object_layer", {}))
        return cls(machine, user_layers, object_layer)

    def __repr__(self) -> str:
        return (
            f"SettingsStack("
            f"machine={self._machine.name!r}, "
            f"user_layers={[l.name for l in self._user]}, "
            f"object_bodies={self._object.all_body_ids()}"
            f")"
        )


# ---------------------------------------------------------------------------
# SettingsRegistry
# ---------------------------------------------------------------------------

class SettingsRegistry:
    """
    Document-level container for all named layers.
    BuildVolumes hold references (by id) into this registry.

    Owns:
        machine_layers  — dict[id → MachineLayer]
        user_layers     — dict[id → UserLayer]

    Does NOT own ObjectLayers — those are local to each SettingsStack.
    """

    def __getstate__( self ): return "SettingsRegistry"
    def __setstate__( self, state ): pass

    def __init__(self):
        self._machines: dict[str, MachineLayer] = {}
        self._users: dict[str, UserLayer] = {}

    # ------------------------------------------------------------------
    # Machine layers

    def create_machine_layer(self, name: str) -> MachineLayer:
        layer = MachineLayer(name=name)
        self._machines[layer.id] = layer
        return layer

    def add_machine_layer(self, layer: MachineLayer) -> None:
        self._machines[layer.id] = layer

    def get_machine_layer(self, layer_id: str) -> MachineLayer:
        try:
            return self._machines[layer_id]
        except KeyError:
            raise KeyError(f"Machine layer '{layer_id}' not found in registry.")

    def remove_machine_layer(self, layer_id: str) -> None:
        self._machines.pop(layer_id, None)

    def all_machine_layers(self) -> list[MachineLayer]:
        return list(self._machines.values())

    # ------------------------------------------------------------------
    # User layers

    def create_user_layer(self, name: str) -> UserLayer:
        layer = UserLayer(name=name)
        self._users[layer.id] = layer
        return layer

    def add_user_layer(self, layer: UserLayer) -> None:
        self._users[layer.id] = layer

    def get_user_layer(self, layer_id: str) -> UserLayer:
        try:
            return self._users[layer_id]
        except KeyError:
            raise KeyError(f"User layer '{layer_id}' not found in registry.")

    def remove_user_layer(self, layer_id: str) -> None:
        self._users.pop(layer_id, None)

    def all_user_layers(self) -> list[UserLayer]:
        return list(self._users.values())

    # ------------------------------------------------------------------
    # Stack factory

    def make_stack(
        self,
        machine_id: str,
        user_layer_ids: list[str] | None = None,
    ) -> SettingsStack:
        """Create a new SettingsStack wired to existing registry layers."""
        machine = self.get_machine_layer(machine_id)
        user_layers = [self.get_user_layer(lid)
                       for lid in (user_layer_ids or [])]
        return SettingsStack(machine, user_layers)

    # ------------------------------------------------------------------
    # Serialisation

    def to_plain_dict(self) -> dict:
        # Use to_registry_dict() so linked_path is persisted in the registry
        # but NOT written into the linked files themselves
        return {
            "machine_layers": [l.to_registry_dict()
                                for l in self._machines.values()],
            "user_layers":    [l.to_registry_dict()
                                for l in self._users.values()],
        }

    @classmethod
    def from_plain_dict(cls, d: dict) -> "SettingsRegistry":
        registry = cls()
        for ld in d.get("machine_layers", []):
            registry.add_machine_layer(MachineLayer.from_plain_dict(ld))
        for ld in d.get("user_layers", []):
            registry.add_user_layer(UserLayer.from_plain_dict(ld))
        return registry

    def __repr__(self) -> str:
        return (
            f"SettingsRegistry("
            f"machines={[l.name for l in self._machines.values()]}, "
            f"users={[l.name for l in self._users.values()]})"
        )
