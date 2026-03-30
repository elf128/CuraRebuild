# CuraRebuild

A FreeCAD 0.21 workbench for FDM 3D printing — integrates CuraEngine as a first-class slicer with a fully dynamic, schema-driven settings system.

**Authors:** Vlad A. · Claude AI (Sonnet 4.6)  
**License:** LGPL v2+

---

## Overview

CuraRebuild replaces the abandoned cblt2l plugin. It provides:

- A **layered settings stack** — machine defaults, user profiles, and per-object overrides, resolved in priority order (bottom of list = highest priority)
- A **BuildVolume** object in the FreeCAD 3D viewport — a live wireframe representing your printer's bed and build envelope
- **One-click slicing** via CuraEngine 4.12+, with output written directly to a `.gcode` file
- **G-code visualisation** in the 3D viewport — solid cylinder toolpaths with per-feature colouring, speed gradient, and layer-by-layer slider
- **Import** from existing Cura machine instances, `.curaprofile` zips, and Cura-sliced G-code

---

## Requirements

- FreeCAD 0.21
- CuraEngine 4.12+ (binary or AppImage)
- Python 3.10+
- pivy (bundled with FreeCAD)

---

## Installation

```bash
# Clone into FreeCAD's Mod directory
git clone https://github.com/youruser/CuraRebuild \
    ~/.local/share/FreeCAD/Mod/CuraRebuild

# Copy base definition files from a Cura 4.12 AppImage or installation
cp /path/to/cura/resources/definitions/fdmprinter.def.json \
    ~/.local/share/FreeCAD/Mod/CuraRebuild/data/
cp /path/to/cura/resources/definitions/fdmextruder.def.json \
    ~/.local/share/FreeCAD/Mod/CuraRebuild/data/
```

Restart FreeCAD and activate the **CuraRebuild** workbench.

---

## Quick Start

1. **Create a Machine Layer** — `CuraRebuild → Create Machine Layer`. Import from an existing Cura installation or set dimensions manually.
2. **Create a Build Volume** — `CuraRebuild → Create Build Volume`. Assign your machine layer and user profile layers.
3. **Assign Bodies** — select your PartDesign bodies and assign them to the build volume.
4. **Set CuraEngine path** in the **CuraRebuild Settings** object (double-click in tree), and set **G-code output file** in the build volume editor.
5. **Slice** — `CuraRebuild → Slice Now`. G-code is written to the output file and the toolpath appears in the 3D viewport.

---

## Architecture

### Settings Layer System

Settings are resolved through a **sparse stack** — each layer only stores values that explicitly override the layer below it. The schema (575 settings) is loaded from `fdmprinter.def.json` at startup.

```
MachineLayer       ← machine dimensions, start/end G-code, hardware caps
  └── UserLayer[]  ← quality, material, speed profiles
  │     (top of list = lowest priority, bottom of list = highest priority)
  └── schema defaults  ← fallback for anything not explicitly set
```

**Key classes:**
- `BaseLayer` — sparse dict with `set / get / delete / link / flush_to_file`
- `SettingsStack` — resolves effective values; `resolve_for_extruder()` filters by `ApplyTo`
- `SettingsRegistry` — FreeCAD document object owning all layers, serialised to JSON

### BuildVolume

`App::FeaturePython` object with:
- **Coin3D wireframe** — box, bed grid, axis indicator, all shifted by `PrinterOffsetX/Y`
- **G-code overlay** — lazy-built cylinder geometry per layer, toggled by `ShowGCode`
- **`execute()`** — called by FreeCAD recompute; updates geometry and triggers display mode refresh

**Coordinate systems:**
- FreeCAD world space = mm
- `PrinterOffsetX/Y` = position of Cura's object-space origin in G-code space (typically `machine_width/2`, `machine_depth/2` for center-origin machines)
- STL export applies only `BuildVolume.Placement` (world → printer)
- G-code display adds `PrinterOffset` to shift toolpaths into world space

### G-Code Viewer

- **Parser** (`gcode_viewer/parser.py`) — reads Cura comments (`;LAYER:N`, `;TYPE:`, `T0/T1`), computes bead width from `line_width` header
- **Renderer** (`gcode_viewer/renderer.py`) — 6-sided prism cylinders via `SoIndexedFaceSet`, one `SoSwitch` per layer for O(1) layer visibility toggle
- **Colour modes** — Feature (fixed palette per type), Speed (blue→red gradient), Extruder

### Slicer

`slicer/engine.py` writes temporary `machine.def.json`, `extruder_N.def.json`, and `profile.def.json` files to a temp directory alongside `fdmprinter.def.json` and `fdmextruder.def.json`, then invokes CuraEngine as a subprocess.

---

## File Structure

```
CuraRebuild/
├── InitGui.py                  ← workbench bootstrap, JSON encoder patch
├── Commands.py                 ← all FreeCAD command classes + hot-reload
├── Common.py                   ← Log(), LogLevel, getIconPath()
├── registry_object.py          ← SettingsRegistry FeaturePython object
├── layer_fp_object.py          ← per-layer FeaturePython objects
│
├── data/
│   ├── fdmprinter.def.json     ← Cura schema (575 settings) — you provide
│   └── fdmextruder.def.json    ← Cura extruder schema — you provide
│
├── settings/
│   ├── schema.py               ← SettingDef dataclass, SchemaRegistry singleton
│   │                             (no hardcoded settings — loaded from fdmprinter.def.json)
│   ├── schema_loader.py        ← parse fdmprinter.def.json
│   ├── expr_eval.py            ← evaluate Cura enabled/value expressions
│   ├── stack.py                ← BaseLayer, MachineLayer, UserLayer, SettingsStack
│   ├── storage.py              ← JSON import/export
│   └── cura_export.py          ← serialize stack → CuraEngine def files
│
├── build_volume/
│   ├── build_volume.py         ← BuildVolume FeaturePython proxy
│   └── view_provider.py        ← Coin3D wireframe + G-code renderer
│
├── gcode_viewer/
│   ├── parser.py               ← G-code → Layer/Move data model
│   └── renderer.py             ← Coin3D cylinder geometry builder
│
├── slicer/
│   └── engine.py               ← CuraEngine subprocess orchestration
│
└── ui/
    ├── panels.py               ← all task panels
    ├── cura_import.py          ← import from Cura machine instances
    └── profile_import.py       ← import from .curaprofile / sliced G-code
```

---

## Known FreeCAD / Qt Constraints

These are hard-won lessons — do not change without understanding why:

- **`Label` must use `setPropertyStatus("ReadOnly")`** — blocks rename-on-double-click on FeaturePython objects
- **`__getstate__` must return a plain string** — returning a dict causes `PropertyPythonObject::toString()` failures
- **Use `functools.partial`, never lambdas** for Qt signal connections — lambdas cause `TypeError: missing 1 required positional argument: 'checked'`
- **`QFileDialog` parent must be `None`** when embedded in dialogs
- **Layers must stay sparse** — `apply()` on Save must never write all widget values back to the layer
- **`execute()` is the correct hook** for post-recompute VP updates — `attach()` fires before properties are set, `updateData()` is unreliable for `App::PropertyFloat`
- **`App::PropertyLength` does not trigger `onChanged`** in FreeCAD 0.21 — use `App::PropertyFloat` for geometry properties that need live `onChanged` callbacks
- **`addDisplayMode` snapshots at registration time** — call it from `attach()` only; use `execute()` to cycle the display mode after geometry is correct
- **Pivy/Coin3D objects are pickled by FreeCAD as `{"this": None}` dead dicts on document restore** — detect with `isinstance(obj, dict)` in `_ensure_attrs()` and reset to `None`; `__setstate__` must call `self.__dict__.clear()` first

---

## Development

Hot-reload is supported — switch away from the workbench and back to reload all modules without restarting FreeCAD. The reload list is in `Commands.py → Reload()`.

---

## License

GNU Lesser General Public License v2 or later. See `LICENCE` for details.
