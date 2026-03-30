# CuraRebuild — Layer Settings Data Path

This document describes the complete lifecycle of a settings layer: how data
is structured in memory, how it is read from and written to disk, how the UI
accesses and modifies it, and every point where a write to storage occurs.

---

## 1. Concepts

### 1.1 What a Layer Is

A layer (`MachineLayer` or `UserLayer`) is a **sparse override set** — a
dict containing only the settings the user has explicitly chosen to place
there. A freshly created layer has zero entries. It does not automatically
contain all 575 schema settings.

There are two storage buckets inside every layer:

| Bucket | Type | Contents |
|---|---|---|
| `_data` | `dict[str, Any]` | Validated typed values (int / float / bool / str) |
| `_expressions` | `dict[str, str]` | Custom formula strings (e.g. `"machine_nozzle_size / 2"`) |

A setting is "in the layer" if it appears in either bucket.
`layer.has(key)` returns `True` for both.

### 1.2 Schema

The schema (`SchemaRegistry` singleton in `settings/schema.py`) is loaded
from `data/fdmprinter.def.json` at startup. It provides, for every setting:

- `dtype` — Python type (int / float / bool / str)
- `default` — the Cura schema default value
- `category` — category label string (e.g. `"Quality"`, `"Shell"`)
- `value_expr` — formula that drives the value (e.g. `"infill_line_width * 100 / infill_sparse_density"`)
- `enabled_expr` — condition for when the setting is active (e.g. `"adhesion_type != 'none'"`)
- `options` — list of valid strings for enum settings

Access via `_active_schema()` in `stack.py`, or `_get_schema_registry()` in
`panels.py`. Both return the live 575-setting registry loaded from
`fdmprinter.def.json`. The old hardcoded `SCHEMA` dict no longer exists.

### 1.3 The Registry

`SettingsRegistry` (in `settings/stack.py`) is the in-memory container that
owns all `MachineLayer` and `UserLayer` objects for a document. It lives
as the `.Proxy._registry` attribute of the `__CuraRebuildRegistry__`
FreeCAD document object.

---

## 2. In-Memory Data Model

```
SettingsRegistry
├── _machines: dict[id, MachineLayer]
└── _users:    dict[id, UserLayer]

BaseLayer
├── name: str
├── id:   str  (UUID)
├── _data:        dict[str, Any]    # typed values
├── _expressions: dict[str, str]    # formula strings
└── _linked_path: str | None        # abs path to linked JSON file
```

### 2.1 Reading a Value

```python
layer.get(key)          # → typed value, expression string, or None
layer.get_typed(key)    # → typed value only (None if expression)
layer.get_expression(key)  # → formula string or None
layer.has(key)          # → True if in either _data or _expressions
layer.has_expression(key)  # → True if in _expressions
```

### 2.2 Writing a Value

```python
layer.set(key, value)
```

Internally:

1. Look up `sdef = _active_schema()[key]` — raises `KeyError` if unknown.
2. If `value` is a `str` and `sdef.dtype != str`:
   - Try `sdef.dtype(value)` — if it succeeds, store as typed value in `_data`.
   - If it fails, store as custom expression in `_expressions`.
3. Otherwise: `sdef.safe_validate(value)` → store in `_data`.
4. Remove the key from the other bucket (a key is never in both simultaneously).
5. If `_linked_path` is set → `flush_to_file()` immediately.

```python
layer.set_expression(key, expr)  # force-store as expression
layer.delete(key)                # remove from both buckets; flush if linked
layer.clear()                    # remove all entries from both buckets
```

---

## 3. Persistent Storage — Where Data Lives on Disk

There are **two storage locations** for layer data, used simultaneously:

### 3.1 FreeCAD Document Object (Primary)

Every layer is represented as a `FeaturePython` object in the FreeCAD
document tree. The entire `SettingsRegistry` (all layers, all values) is
serialized as a single JSON string in the hidden property `RegistryJson`
on the `__CuraRebuildRegistry__` object.

**Path:** `FreeCAD document → __CuraRebuildRegistry__ FP object → RegistryJson property`

**Format:** JSON string produced by `SettingsRegistry.to_plain_dict()`, which
calls `layer.to_registry_dict()` for each layer:

```json
{
  "__layer_fps__": {
    "<layer_id>": "<fp_object_name>"
  },
  "machine_layers": [
    {
      "id": "b6325036-...",
      "name": "i3e",
      "type": "MachineLayer",
      "settings": {
        "Machine": {
          "machine_width": 220,
          "machine_depth": 220,
          "machine_height": 250,
          "machine_gcode_flavor": "RepRap (Marlin/Sprinter)"
        }
      },
      "linked_path": "/home/vlad/profiles/i3e.json"
    }
  ],
  "user_layers": [
    {
      "id": "cccd33d5-...",
      "name": "i3e profile",
      "type": "UserLayer",
      "settings": {
        "Quality": {
          "layer_height": 0.1
        },
        "Material": {
          "material_bed_temperature": 90.0
        }
      }
    }
  ]
}
```

Note: `linked_path` is **only in `to_registry_dict()`** — it is stored here
so the link survives document save/load. It is **not** in the linked JSON
file itself.

**When written:** `flush_registry(doc)` → `registry_object.RegistryObject.save_to_fp(fp)` →
sets `fp.RegistryJson`. This is called:
- After every `layer.set()` triggered by `LayerFpObject.onChanged()`
- After `show_as_dialog()` accepted (Save button)
- After copy/move operations in the `...` menu

### 3.2 Linked JSON File (Optional, External)

If a layer has `_linked_path` set, the layer's data is also mirrored to an
external JSON file on disk. Multiple FreeCAD documents can link to the same
file to share a settings profile.

**Path:** Any absolute path on the filesystem, stored in `layer._linked_path`
and mirrored in the `LinkedFile` FP property of the layer's child FP object.

**Format:** Structured JSON produced by `layer.to_plain_dict()` — identical
to the registry format except `linked_path` is omitted:

```json
{
  "id": "cccd33d5-...",
  "name": "i3e profile",
  "type": "UserLayer",
  "settings": {
    "Quality": {
      "layer_height": 0.1,
      "layer_height_0": "layer_height * 2"
    },
    "Material": {
      "material_bed_temperature": 90.0,
      "material_print_temperature": 235
    }
  }
}
```

String values = custom expressions (state 5). Numeric/bool values = normal overrides.

**When written:** Every call to `layer.set()` or `layer.delete()` when
`_linked_path` is set triggers `flush_to_file()` immediately.

**When read:** On editor open (`LayerEditorWidget._build_ui`), if `is_linked()`,
`reload_from_file()` is called first. Also on document restore
(`RegistryObject.onDocumentRestored`).

---

## 4. FreeCAD Object Properties

Each layer FP child object (`Layer_<8-char-id>`) exposes these properties:

| Property | Type | Purpose |
|---|---|---|
| `Label` | `App::PropertyString` | Display name (ReadOnly — set via editor) |
| `LayerType` | `App::PropertyString` | `"MachineLayer"` or `"UserLayer"` (ReadOnly) |
| `LayerId` | `App::PropertyString` | UUID (ReadOnly) |
| `LinkedFile` | `App::PropertyString` | Abs path to linked JSON (empty = internal) |
| *(setting keys)* | Various | One property per schema setting in relevant categories |

The setting properties in the Properties panel are kept in sync with
`_data` via `sync_to_fp()` / `sync_from_fp()`. They are a display mirror —
the authoritative data is always in the `BaseLayer` object's `_data` and
`_expressions` dicts, and ultimately in `RegistryJson`.

---

## 5. The Read Path

### 5.1 Document Open → Memory

```
FreeCAD opens .FCStd file
  └─ RegistryObject.onDocumentRestored(fp)
       ├─ load_from_fp(fp)
       │    └─ json.loads(fp.RegistryJson)
       │         └─ SettingsRegistry.from_plain_dict(data)
       │              ├─ MachineLayer.from_plain_dict(d)  ← calls layer._load_from_dict(d)
       │              └─ UserLayer.from_plain_dict(d)     ← calls layer._load_from_dict(d)
       │
       ├─ _restore_layer_fps(fp)          ← re-links layer objects to their FP children
       │
       └─ [for each linked layer]
            └─ layer.reload_from_file()   ← overwrites _data/_expressions from JSON file
                                             warns if file missing, keeps last known values
```

### 5.2 Editor Open → Display

```
User double-clicks layer in tree
  └─ LayerViewProvider.setEdit(vp)
       └─ LayerFpObject.doubleClicked(vp)
            ├─ [if linked] layer.reload_from_file()   ← fresh read from disk
            └─ MachineLayerPanel / UserLayerPanel shown
                 └─ LayerEditorWidget.__init__(layer, ...)
                      └─ _build_ui()
                           └─ _rebuild_tabs()
                                └─ for each sdef in schema:
                                     current = layer.get(key)   ← reads _data / _expressions
                                     if current is None:
                                         show schema default     ← from SchemaRegistry
                                     else:
                                         show layer value
                                     _compute_state(key) → colour
                                     _make_setting_widget(sdef, current) → widget
```

Note: `_rebuild_tabs()` **never writes** to the layer. It only reads.

---

## 6. The Write Path

### 6.1 User Edits a Widget

```
User changes a widget value
  └─ Qt signal (valueChanged / currentIndexChanged / textChanged / stateChanged)
       └─ LayerEditorWidget._on_widget_changed(key)
            ├─ read widget value
            ├─ if key not in layer AND value == schema_default → skip (no write)
            ├─ else:
            │    ├─ layer.set(key, validated)    ← writes to _data or _expressions
            │    ├─ self._dirty.add(key)          ← marks key as user-touched
            │    └─ [if linked] flush_to_file()  ← immediate write to JSON file
            └─ _compute_state(key) → _apply_row_style(label, widget, state)
```

### 6.2 User Clicks × (Clear Override)

```
User clicks × button on a row
  └─ LayerEditorWidget._on_clear(key)
       ├─ layer.delete(key)               ← removes from _data AND _expressions
       ├─ self._dirty.discard(key)         ← no longer considered user-touched
       ├─ [if linked] flush_to_file()     ← immediate write to JSON file
       ├─ reset widget to schema default  ← widget shows grey default value
       └─ _compute_state(key) → SCHEMA_DEFAULT → grey italic style
          [if filter == "only_set"] → _rebuild_tabs() → row disappears
```

### 6.3 User Clicks Save

```
User clicks Save in MachineLayerPanel / UserLayerPanel
  └─ show_as_dialog() accepted branch
       ├─ self._layer.name = name_edit.text()
       ├─ self._editor.apply()
       │    └─ for key in self._dirty:
       │         layer.set(key, widget_value)   ← only dirty keys written
       │         [if linked] flush_to_file()    ← immediate write per key
       │    self._dirty.clear()
       │    [if linked] flush_to_file()         ← also flush after all dirty keys written
       ├─ [if new layer] reg_fp.Proxy.add_layer(reg_fp, layer)
       │    └─ registry.add_machine_layer / add_user_layer
       │    └─ create_layer_fp(doc, layer, reg_fp)
       └─ flush_registry(doc)
            └─ RegistryObject.save_to_fp(fp)
                 └─ fp.RegistryJson = json.dumps(registry.to_plain_dict())
                      └─ each layer.to_registry_dict()
                           └─ structured {"settings": {"Category": {...}}}
                              + "linked_path" if linked
```

### 6.4 User Links to a File

```
User clicks 🔗 Link… button
  └─ LayerEditorWidget._on_link()
       ├─ layer.link(path)               ← sets _linked_path
       ├─ [if new file] flush_to_file()  ← write current data to file
       ├─ [if existing file]:
       │    Ask: Load FROM file or overwrite?
       │    └─ Yes: layer.reload_from_file() → _rebuild_tabs()
       │    └─ No:  flush_to_file()
       └─ _persist_link()
            ├─ child_fp.LinkedFile = path   ← FP property updated
            └─ flush_registry(doc)          ← linked_path saved in RegistryJson
```

### 6.5 User Unlinks

```
User clicks Unlink
  └─ LayerEditorWidget._on_unlink()
       ├─ layer.link(None)               ← _linked_path = None
       └─ _persist_link()
            ├─ child_fp.LinkedFile = ""
            └─ flush_registry(doc)
```

---

## 7. Colour States (Standalone Editor)

When a layer is opened from the **Settings Registry** (double-click in tree),
no stack context is available. The five display states are:

| State | Colour | Condition |
|---|---|---|
| `SCHEMA_DEFAULT` | Grey italic | Not in layer, no `value_expr` |
| `SET_DEFAULT` | Black | In layer, value == schema default |
| `SET_OVERRIDE` | Dark red bold | In layer, value != schema default |
| `CALCULATED` | Blue italic | Not in layer, has `value_expr` (read-only) |
| `EXPRESSION` | Blue bold + tint | Custom formula stored in `_expressions` |

When opened from **Build Volume** context (stack available), three additional
states apply:

| State | Colour | Condition |
|---|---|---|
| `DISABLED` | Grey + bg tint | `enabled_expr` evaluates to `False` (may be caused by a setting in another layer) |
| `NOT_SET` | Grey italic | Not set in this layer; another layer controls the effective value |
| `OVERRIDDEN` | Strikethrough | This layer sets the key, but a higher-priority layer also sets it |

Tooltip always shows the current state name, and for `NOT_SET` / `OVERRIDDEN`
shows which layer wins (`Winning layer: TPU`). For `DISABLED` it shows which
setting causes the disabled condition and from which layer (`Disabled because:
cool_fan_enabled = False (from TPU)`).

---

## 8. Import Sources

Layer data can enter the system from multiple sources, all of which ultimately
call `layer.set(key, value)`:

| Source | Handler | Result |
|---|---|---|
| Cura machine instances | `ui/cura_import.py` → `MachineInstance.to_layers()` | `MachineLayer` + `UserLayer` |
| `.curaprofile` zip | `ui/profile_import.py` → `CuraProfileImport.to_user_layer()` | `UserLayer` |
| Sliced `.gcode` | `ui/profile_import.py` → `GcodeProfileImport.to_user_layer()` | `UserLayer` |
| CuraRebuild JSON | `settings/storage.py` → `JsonBackend.import_layer()` | `MachineLayer` or `UserLayer` |
| Manual widget edit | `ui/panels.py` → `LayerEditorWidget._on_widget_changed()` | direct `layer.set()` |

All importers use the live `_active_schema().cura_schema` dict (575 settings)
for key lookup. Unknown keys are silently skipped.

---

## 9. Write Guard Summary

These guards prevent accidental layer pollution:

| Guard | Where | Prevents |
|---|---|---|
| `_init_in_progress = True` | `LayerFpObject.__init__` | `onChanged` writing schema defaults during FP property initialization |
| `not was_set and validated == schema_def` | `_on_widget_changed` | Writing a default value into a previously empty layer when user accidentally touches a widget |
| `apply()` only iterates `_dirty` | `LayerEditorWidget.apply()` | Save button writing all 575 visible widget values |
| `_dirty.discard(key)` on clear | `_on_clear` | Save button restoring a key the user just deleted |
| `_dirty.clear()` on rebuild | `_rebuild_tabs` | Stale dirty keys persisting across filter changes |
| `_syncing = True` in `sync_to_fp` | `LayerFpObject.sync_to_fp` | Recursive `onChanged` loop when mirroring layer→FP |

---

## 10. File Structure Reference

```
~/.local/share/FreeCAD/Mod/CuraRebuild/
├── settings/
│   ├── stack.py          BaseLayer, MachineLayer, UserLayer,
│   │                     SettingsStack, SettingsRegistry
│   ├── schema.py         SettingDef dataclass, SchemaRegistry singleton,
│   │                     _active_schema() / get_registry()
│   ├── schema_loader.py  parse fdmprinter.def.json → SettingDef list
│   ├── expr_eval.py      eval_enabled(), eval_value(), extract_dependencies()
│   └── storage.py        JsonBackend (import/export JSON files)
│
├── registry_object.py    RegistryObject FP proxy — owns SettingsRegistry,
│                         serializes to RegistryJson, manages layer FP children
├── layer_fp_object.py    LayerFpObject FP proxy — mirrors one BaseLayer
│                         to FP properties; onChanged syncs FP→layer
│
├── ui/
│   ├── panels.py         LayerEditorWidget, MachineLayerPanel, UserLayerPanel,
│   │                     BuildVolumePanel, RegistryPanel
│   ├── cura_import.py    Import from Cura machine instances on disk
│   └── profile_import.py Import from .curaprofile zip or sliced .gcode
│
└── data/
    └── fdmprinter.def.json   Bundled Cura schema (575 settings)
```
