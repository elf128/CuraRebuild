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

SETTINGS: list[SettingDef] = [

    # -----------------------------------------------------------------------
    # Machine
    # -----------------------------------------------------------------------

    SettingDef(
        key="machine_name",
        cura_key="machine_name",
        label="Machine Name",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=str,
        default="Generic FDM Printer",
        description="Human-readable name of this printer.",
    ),
    SettingDef(
        key="machine_width",
        cura_key="machine_width",
        label="Build Volume Width (X)",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=float,
        default=220.0,
        unit="mm",
        min_val=1.0,
        description="X dimension of the build volume in millimetres.",
    ),
    SettingDef(
        key="machine_depth",
        cura_key="machine_depth",
        label="Build Volume Depth (Y)",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=float,
        default=220.0,
        unit="mm",
        min_val=1.0,
        description="Y dimension of the build volume in millimetres.",
    ),
    SettingDef(
        key="machine_height",
        cura_key="machine_height",
        label="Build Volume Height (Z)",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=float,
        default=250.0,
        unit="mm",
        min_val=1.0,
        description="Z dimension of the build volume in millimetres.",
    ),
    SettingDef(
        key="machine_center_is_zero",
        cura_key="machine_center_is_zero",
        label="Origin at Center",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=bool,
        default=False,
        description="True if the printer's origin (0,0) is at the bed centre rather than a corner.",
    ),
    SettingDef(
        key="machine_heated_bed",
        cura_key="machine_heated_bed",
        label="Heated Bed",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=bool,
        default=True,
        description="Whether the printer has a heated bed.",
    ),
    SettingDef(
        key="machine_extruder_count",
        cura_key="machine_extruder_count",
        label="Extruder Count",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=int,
        default=1,
        min_val=1,
        max_val=8,
        description="Number of extruders on this machine.",
    ),
    SettingDef(
        key="machine_nozzle_size",
        cura_key="machine_nozzle_size",
        label="Nozzle Diameter",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=float,
        default=0.4,
        unit="mm",
        min_val=0.1,
        max_val=2.0,
        description="Diameter of the nozzle orifice.",
    ),
    SettingDef(
        key="machine_gcode_flavor",
        cura_key="machine_gcode_flavor",
        label="G-Code Flavor",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=str,
        default="RepRap (Marlin/Sprinter)",
        description="G-Code dialect.",
        options=[
            "RepRap (Marlin/Sprinter)",
            "RepRap (Volumetric)",
            "UltiGCode",
            "Griffin",
            "Makerbot",
            "BFB",
            "MACH3",
            "Repetier",
        ],
    ),
    SettingDef(
        key="machine_start_gcode",
        cura_key="machine_start_gcode",
        label="Start G-Code",
        category=Category.GCODE,
        home_layer=LayerRole.MACHINE,
        dtype=str,
        default=(
            "G28 ; home all axes\n"
            "G1 Z5 F5000 ; lift nozzle\n"
        ),
        description="G-Code commands inserted at the start of every print.",
    ),
    SettingDef(
        key="machine_end_gcode",
        cura_key="machine_end_gcode",
        label="End G-Code",
        category=Category.GCODE,
        home_layer=LayerRole.MACHINE,
        dtype=str,
        default=(
            "M104 S0 ; turn off extruder\n"
            "M140 S0 ; turn off bed\n"
            "M84     ; disable motors\n"
        ),
        description="G-Code commands inserted at the end of every print.",
    ),

    # -----------------------------------------------------------------------
    # Material
    # -----------------------------------------------------------------------

    SettingDef(
        key="material_diameter",
        cura_key="material_diameter",
        label="Filament Diameter",
        category=Category.MATERIAL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=1.75,
        unit="mm",
        min_val=0.5,
        max_val=3.5,
        description="Nominal diameter of the filament.",
    ),
    SettingDef(
        key="material_print_temperature",
        cura_key="material_print_temperature",
        label="Print Temperature",
        category=Category.MATERIAL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=200.0,
        unit="°C",
        min_val=0.0,
        max_val=400.0,
        description="Nozzle temperature during printing.",
    ),
    SettingDef(
        key="material_print_temperature_layer_0",
        cura_key="material_print_temperature_layer_0",
        label="Initial Layer Print Temperature",
        category=Category.MATERIAL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=200.0,
        unit="°C",
        min_val=0.0,
        max_val=400.0,
        description="Nozzle temperature for the first layer only.",
    ),
    SettingDef(
        key="material_bed_temperature",
        cura_key="material_bed_temperature",
        label="Bed Temperature",
        category=Category.MATERIAL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=60.0,
        unit="°C",
        min_val=0.0,
        max_val=150.0,
        description="Heated bed temperature during printing.",
    ),
    SettingDef(
        key="material_bed_temperature_layer_0",
        cura_key="material_bed_temperature_layer_0",
        label="Initial Layer Bed Temperature",
        category=Category.MATERIAL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=60.0,
        unit="°C",
        min_val=0.0,
        max_val=150.0,
        description="Heated bed temperature for the first layer only.",
    ),
    SettingDef(
        key="material_flow",
        cura_key="material_flow",
        label="Flow Rate",
        category=Category.MATERIAL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=100.0,
        unit="%",
        min_val=1.0,
        max_val=500.0,
        description="Extrusion multiplier as a percentage of the calculated volume.",
    ),

    # -----------------------------------------------------------------------
    # Quality — layer geometry
    # -----------------------------------------------------------------------

    SettingDef(
        key="layer_height",
        cura_key="layer_height",
        label="Layer Height",
        category=Category.QUALITY,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.2,
        unit="mm",
        min_val=0.01,
        max_val=10.0,
        description="Thickness of each layer.",
    ),
    SettingDef(
        key="layer_height_0",
        cura_key="layer_height_0",
        label="Initial Layer Height",
        category=Category.QUALITY,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.3,
        unit="mm",
        min_val=0.01,
        max_val=10.0,
        description="Thickness of the first layer. Thicker improves bed adhesion.",
    ),
    SettingDef(
        key="line_width",
        cura_key="line_width",
        label="Line Width",
        category=Category.QUALITY,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.4,
        unit="mm",
        min_val=0.01,
        max_val=10.0,
        description="Width of a single extruded line. Usually equal to nozzle diameter.",
    ),

    # -----------------------------------------------------------------------
    # Walls
    # -----------------------------------------------------------------------

    SettingDef(
        key="wall_line_count",
        cura_key="wall_line_count",
        label="Wall Line Count",
        category=Category.WALLS,
        home_layer=LayerRole.USER,
        dtype=int,
        default=3,
        min_val=0,
        description="Number of perimeter walls.",
    ),
    SettingDef(
        key="wall_thickness",
        cura_key="wall_thickness",
        label="Wall Thickness",
        category=Category.WALLS,
        home_layer=LayerRole.USER,
        dtype=float,
        default=1.2,
        unit="mm",
        min_val=0.0,
        description="Total thickness of all perimeter walls.",
    ),
    SettingDef(
        key="outer_inset_first",
        cura_key="outer_inset_first",
        label="Outer Wall First",
        category=Category.WALLS,
        home_layer=LayerRole.USER,
        dtype=bool,
        default=False,
        description="Print the outermost wall before inner walls.",
    ),

    # -----------------------------------------------------------------------
    # Top / Bottom
    # -----------------------------------------------------------------------

    SettingDef(
        key="top_layers",
        cura_key="top_layers",
        label="Top Layers",
        category=Category.TOP_BOTTOM,
        home_layer=LayerRole.USER,
        dtype=int,
        default=4,
        min_val=0,
        description="Number of solid layers on top of the model.",
    ),
    SettingDef(
        key="bottom_layers",
        cura_key="bottom_layers",
        label="Bottom Layers",
        category=Category.TOP_BOTTOM,
        home_layer=LayerRole.USER,
        dtype=int,
        default=4,
        min_val=0,
        description="Number of solid layers at the bottom of the model.",
    ),
    SettingDef(
        key="top_bottom_thickness",
        cura_key="top_bottom_thickness",
        label="Top/Bottom Thickness",
        category=Category.TOP_BOTTOM,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.8,
        unit="mm",
        min_val=0.0,
        description="Total thickness of solid top and bottom surfaces.",
    ),
    SettingDef(
        key="top_bottom_pattern",
        cura_key="top_bottom_pattern",
        label="Top/Bottom Pattern",
        category=Category.TOP_BOTTOM,
        home_layer=LayerRole.USER,
        dtype=str,
        default="lines",
        description="Fill pattern for top and bottom layers.",
        options=[ "lines", "concentric", "zigzag" ],
    ),

    # -----------------------------------------------------------------------
    # Infill
    # -----------------------------------------------------------------------

    SettingDef(
        key="infill_sparse_density",
        cura_key="infill_sparse_density",
        label="Infill Density",
        category=Category.INFILL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=20.0,
        unit="%",
        min_val=0.0,
        max_val=100.0,
        description="Percentage of the interior volume filled with material.",
    ),
    SettingDef(
        key="infill_pattern",
        cura_key="infill_pattern",
        label="Infill Pattern",
        category=Category.INFILL,
        home_layer=LayerRole.USER,
        dtype=str,
        default="grid",
        description="Geometry used for infill.",
        options=[
            "grid", "lines", "triangles", "tri_hexagon", "cubic",
            "gyroid", "honeycomb", "lightning", "concentric",
            "cross", "cross_3d", "tetrahedral", "quarter_cubic", "octet",
        ],
    ),
    SettingDef(
        key="infill_line_distance",
        cura_key="infill_line_distance",
        label="Infill Line Distance",
        category=Category.INFILL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=4.0,
        unit="mm",
        min_val=0.0,
        description="Distance between adjacent infill lines. "
                    "Derived from density if not set explicitly.",
    ),
    SettingDef(
        key="infill_overlap",
        cura_key="infill_overlap",
        label="Infill Overlap",
        category=Category.INFILL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=30.0,
        unit="%",
        min_val=0.0,
        max_val=100.0,
        description="How much infill overlaps with the innermost wall.",
    ),

    # -----------------------------------------------------------------------
    # Speed
    # -----------------------------------------------------------------------

    SettingDef(
        key="speed_print",
        cura_key="speed_print",
        label="Print Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=60.0,
        unit="mm/s",
        min_val=0.1,
        description="Default speed for all printing moves.",
    ),
    SettingDef(
        key="speed_infill",
        cura_key="speed_infill",
        label="Infill Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=80.0,
        unit="mm/s",
        min_val=0.1,
        description="Speed for infill moves.",
    ),
    SettingDef(
        key="speed_wall_0",
        cura_key="speed_wall_0",
        label="Outer Wall Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=30.0,
        unit="mm/s",
        min_val=0.1,
        description="Speed for the outermost perimeter wall.",
    ),
    SettingDef(
        key="speed_wall_x",
        cura_key="speed_wall_x",
        label="Inner Wall Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=60.0,
        unit="mm/s",
        min_val=0.1,
        description="Speed for inner perimeter walls.",
    ),
    SettingDef(
        key="speed_topbottom",
        cura_key="speed_topbottom",
        label="Top/Bottom Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=30.0,
        unit="mm/s",
        min_val=0.1,
        description="Speed for top and bottom solid fill.",
    ),
    SettingDef(
        key="speed_layer_0",
        cura_key="speed_layer_0",
        label="Initial Layer Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=20.0,
        unit="mm/s",
        min_val=0.1,
        description="Print speed for the first layer.",
    ),
    SettingDef(
        key="speed_travel",
        cura_key="speed_travel",
        label="Travel Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=150.0,
        unit="mm/s",
        min_val=0.1,
        description="Speed for non-printing travel moves.",
    ),
    SettingDef(
        key="speed_travel_layer_0",
        cura_key="speed_travel_layer_0",
        label="Initial Layer Travel Speed",
        category=Category.SPEED,
        home_layer=LayerRole.USER,
        dtype=float,
        default=100.0,
        unit="mm/s",
        min_val=0.1,
        description="Travel speed during the first layer.",
    ),

    # -----------------------------------------------------------------------
    # Travel
    # -----------------------------------------------------------------------

    SettingDef(
        key="retraction_enable",
        cura_key="retraction_enable",
        label="Enable Retraction",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=bool,
        default=True,
        description="Pull filament back during travel to reduce stringing.",
    ),
    SettingDef(
        key="retraction_amount",
        cura_key="retraction_amount",
        label="Retraction Distance",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=5.0,
        unit="mm",
        min_val=0.0,
        description="Length of filament retracted on travel moves.",
    ),
    SettingDef(
        key="retraction_speed",
        cura_key="retraction_speed",
        label="Retraction Speed",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=45.0,
        unit="mm/s",
        min_val=0.1,
        description="Speed at which filament is retracted and primed.",
    ),
    SettingDef(
        key="retraction_min_travel",
        cura_key="retraction_min_travel",
        label="Minimum Travel for Retraction",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=1.5,
        unit="mm",
        min_val=0.0,
        description="Minimum travel distance before retraction is triggered.",
    ),
    SettingDef(
        key="retraction_combing",
        cura_key="retraction_combing",
        label="Combing Mode",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=str,
        default="noskin",
        description="Whether to avoid crossing walls during travel.",
        options=[ "off", "noskin", "no_outer_surfaces", "all", "infill" ],
    ),
    SettingDef(
        key="retraction_hop_enabled",
        cura_key="retraction_hop_enabled",
        label="Z Hop on Retract",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=bool,
        default=False,
        description="Lift the nozzle on retraction to avoid hitting printed parts.",
    ),
    SettingDef(
        key="retraction_hop",
        cura_key="retraction_hop",
        label="Z Hop Height",
        category=Category.TRAVEL,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.2,
        unit="mm",
        min_val=0.0,
        description="Height of the Z lift during retraction hop.",
    ),

    # -----------------------------------------------------------------------
    # Cooling
    # -----------------------------------------------------------------------

    SettingDef(
        key="cool_fan_enabled",
        cura_key="cool_fan_enabled",
        label="Enable Cooling Fan",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=bool,
        default=True,
        description="Enable the part cooling fan.",
    ),
    SettingDef(
        key="cool_fan_speed",
        cura_key="cool_fan_speed",
        label="Fan Speed",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=float,
        default=100.0,
        unit="%",
        min_val=0.0,
        max_val=100.0,
        description="Target fan speed as a percentage of maximum.",
    ),
    SettingDef(
        key="cool_fan_speed_min",
        cura_key="cool_fan_speed_min",
        label="Minimum Fan Speed",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=float,
        default=100.0,
        unit="%",
        min_val=0.0,
        max_val=100.0,
        description="Minimum fan speed when slowing down for layer time.",
    ),
    SettingDef(
        key="cool_fan_speed_max",
        cura_key="cool_fan_speed_max",
        label="Maximum Fan Speed",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=float,
        default=100.0,
        unit="%",
        min_val=0.0,
        max_val=100.0,
        description="Maximum fan speed.",
    ),
    SettingDef(
        key="cool_fan_full_at_height",
        cura_key="cool_fan_full_at_height",
        label="Regular Fan Speed at Height",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.5,
        unit="mm",
        min_val=0.0,
        description="Height at which fan reaches full speed.",
    ),
    SettingDef(
        key="cool_min_layer_time",
        cura_key="cool_min_layer_time",
        label="Minimum Layer Time",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=float,
        default=10.0,
        unit="s",
        min_val=0.0,
        description="Minimum time to spend on each layer (slow down print if needed).",
    ),
    SettingDef(
        key="cool_min_speed",
        cura_key="cool_min_speed",
        label="Minimum Speed",
        category=Category.COOLING,
        home_layer=LayerRole.USER,
        dtype=float,
        default=10.0,
        unit="mm/s",
        min_val=0.1,
        description="Minimum print speed while enforcing minimum layer time.",
    ),

    # -----------------------------------------------------------------------
    # Support
    # -----------------------------------------------------------------------

    SettingDef(
        key="support_enable",
        cura_key="support_enable",
        label="Enable Support",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=bool,
        default=False,
        description="Generate support structures for overhanging geometry.",
    ),
    SettingDef(
        key="support_type",
        cura_key="support_type",
        label="Support Placement",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=str,
        default="buildplate",
        description="Where supports are placed.",
        options=[ "buildplate", "everywhere" ],
    ),
    SettingDef(
        key="support_angle",
        cura_key="support_angle",
        label="Support Overhang Angle",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=float,
        default=50.0,
        unit="°",
        min_val=0.0,
        max_val=90.0,
        description="Overhang angle above which support is generated.",
    ),
    SettingDef(
        key="support_pattern",
        cura_key="support_pattern",
        label="Support Pattern",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=str,
        default="zigzag",
        description="Geometry of support structures.",
        options=[ "lines", "grid", "triangles", "concentric", "zigzag", "cross", "gyroid" ],
    ),
    SettingDef(
        key="support_infill_rate",
        cura_key="support_infill_rate",
        label="Support Density",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=float,
        default=20.0,
        unit="%",
        min_val=0.0,
        max_val=100.0,
        description="Density of support fill.",
    ),
    SettingDef(
        key="support_z_distance",
        cura_key="support_z_distance",
        label="Support Z Distance",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.2,
        unit="mm",
        min_val=0.0,
        description="Vertical gap between support and model.",
    ),
    SettingDef(
        key="support_xy_distance",
        cura_key="support_xy_distance",
        label="Support X/Y Distance",
        category=Category.SUPPORT,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.8,
        unit="mm",
        min_val=0.0,
        description="Horizontal gap between support and model.",
    ),

    # -----------------------------------------------------------------------
    # Adhesion
    # -----------------------------------------------------------------------

    SettingDef(
        key="adhesion_type",
        cura_key="adhesion_type",
        label="Adhesion Type",
        category=Category.ADHESION,
        home_layer=LayerRole.USER,
        dtype=str,
        default="skirt",
        description="Bed adhesion method.",
        options=[ "none", "skirt", "brim", "raft" ],
    ),
    SettingDef(
        key="skirt_line_count",
        cura_key="skirt_line_count",
        label="Skirt Line Count",
        category=Category.ADHESION,
        home_layer=LayerRole.USER,
        dtype=int,
        default=3,
        min_val=1,
        description="Number of skirt lines around the print.",
    ),
    SettingDef(
        key="skirt_gap",
        cura_key="skirt_gap",
        label="Skirt Distance",
        category=Category.ADHESION,
        home_layer=LayerRole.USER,
        dtype=float,
        default=3.0,
        unit="mm",
        min_val=0.0,
        description="Distance between the skirt and the first wall.",
    ),
    SettingDef(
        key="brim_width",
        cura_key="brim_width",
        label="Brim Width",
        category=Category.ADHESION,
        home_layer=LayerRole.USER,
        dtype=float,
        default=8.0,
        unit="mm",
        min_val=0.0,
        description="Width of the brim around the base of the model.",
    ),
    SettingDef(
        key="raft_margin",
        cura_key="raft_margin",
        label="Raft Extra Margin",
        category=Category.ADHESION,
        home_layer=LayerRole.USER,
        dtype=float,
        default=5.0,
        unit="mm",
        min_val=0.0,
        description="How far the raft extends beyond the model footprint.",
    ),
    SettingDef(
        key="raft_airgap",
        cura_key="raft_airgap",
        label="Raft Air Gap",
        category=Category.ADHESION,
        home_layer=LayerRole.USER,
        dtype=float,
        default=0.3,
        unit="mm",
        min_val=0.0,
        description="Gap between the raft top surface and the first model layer.",
    ),

    # -----------------------------------------------------------------------
    # Per-object overrides (home_layer = OBJECT)
    # These are the settings most likely to be overridden at the object level.
    # They can of course also live in any user layer.
    # -----------------------------------------------------------------------

    SettingDef(
        key="mesh_position_x",
        cura_key="mesh_position_x",
        label="Mesh Position X",
        category=Category.EXPERIMENTAL,
        home_layer=LayerRole.OBJECT,
        dtype=float,
        default=0.0,
        unit="mm",
        description="X position offset for this mesh in printer coordinates.",
    ),
    SettingDef(
        key="mesh_position_y",
        cura_key="mesh_position_y",
        label="Mesh Position Y",
        category=Category.EXPERIMENTAL,
        home_layer=LayerRole.OBJECT,
        dtype=float,
        default=0.0,
        unit="mm",
        description="Y position offset for this mesh in printer coordinates.",
    ),
    SettingDef(
        key="mesh_position_z",
        cura_key="mesh_position_z",
        label="Mesh Position Z",
        category=Category.EXPERIMENTAL,
        home_layer=LayerRole.OBJECT,
        dtype=float,
        default=0.0,
        unit="mm",
        description="Z position offset for this mesh in printer coordinates.",
    ),
    SettingDef(
        key="infill_mesh",
        cura_key="infill_mesh",
        label="Infill Mesh",
        category=Category.INFILL,
        home_layer=LayerRole.OBJECT,
        dtype=bool,
        default=False,
        description="Treat this object as an infill modifier mesh.",
    ),
    SettingDef(
        key="cutting_mesh",
        cura_key="cutting_mesh",
        label="Cutting Mesh",
        category=Category.INFILL,
        home_layer=LayerRole.OBJECT,
        dtype=bool,
        default=False,
        description="Treat this object as a cutting modifier mesh.",
    ),
    SettingDef(
        key="anti_overhang_mesh",
        cura_key="anti_overhang_mesh",
        label="Anti Overhang Mesh",
        category=Category.SUPPORT,
        home_layer=LayerRole.OBJECT,
        dtype=bool,
        default=False,
        description="Treat this object as an anti-overhang modifier (block support).",
    ),
    SettingDef(
        key="support_mesh",
        cura_key="support_mesh",
        label="Support Mesh",
        category=Category.SUPPORT,
        home_layer=LayerRole.OBJECT,
        dtype=bool,
        default=False,
        description="Treat this object as a custom support mesh.",
    ),

    # -----------------------------------------------------------------------
    # FreeCAD-only (never exported to CuraEngine)
    # -----------------------------------------------------------------------

    SettingDef(
        key="_fc_unit_scale",
        cura_key="",
        label="Document Unit Scale",
        category=Category.MACHINE,
        home_layer=LayerRole.MACHINE,
        dtype=float,
        default=1.0,
        description="Multiply FreeCAD document units by this factor to get millimetres. "
                    "e.g. 0.001 if the document is in micrometres. "
                    "This key is never written to CuraEngine.",
    ),
]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

# Key → SettingDef  (primary lookup)
SCHEMA: dict[str, SettingDef] = {s.key: s for s in SETTINGS}

# cura_key → SettingDef  (for reverse lookup / import from Cura JSON)
CURA_SCHEMA: dict[str, SettingDef] = {
    s.cura_key: s for s in SETTINGS if s.cura_key
}

# Category → [SettingDef]  (for UI panel generation)
BY_CATEGORY: dict[str, list[SettingDef]] = {}
for _s in SETTINGS:
    BY_CATEGORY.setdefault(_s.category, []).append(_s)

# LayerRole → [SettingDef]  (for "home layer" hints)
BY_HOME_LAYER: dict[LayerRole, list[SettingDef]] = {}
for _s in SETTINGS:
    BY_HOME_LAYER.setdefault(_s.home_layer, []).append(_s)


def get(key: str) -> SettingDef:
    """Return the SettingDef for key from the live registry, fallback to SCHEMA."""
    try:
        return _registry.schema[key]
    except Exception:
        pass
    try:
        return SCHEMA[key]
    except KeyError:
        raise KeyError(f"Unknown setting key: '{key}'") from None


def get_default(key: str) -> Any:
    """Return the schema default for a key."""
    try:
        return _registry.schema[key].default
    except Exception:
        pass
    return SCHEMA.get(key, SettingDef(key=key, cura_key=key)).default


def all_keys() -> list[str]:
    try:
        return list( _registry.schema.keys() )
    except Exception:
        return list(SCHEMA.keys())


def exportable_keys() -> list[str]:
    """Keys that should be written to CuraEngine (excludes _fc_ keys)."""
    try:
        return [s.key for s in _registry.schema.values() if s.cura_key]
    except Exception:
        return [s.key for s in SETTINGS if s.cura_key]


# ---------------------------------------------------------------------------
# SchemaRegistry
#
# Manages the active schema — either the hardcoded SETTINGS list or a
# dynamically parsed fdmprinter.def.json.  One singleton per process.
# ---------------------------------------------------------------------------

class SchemaRegistry:
    """
    Holds the active set of SettingDef objects and provides lookup helpers.
    Call load_from_def_json() to replace the schema with a parsed def file.
    """

    def __init__( self ):
        self._schema:       dict[str, SettingDef] = {}
        self._cura_schema:  dict[str, SettingDef] = {}
        self._by_category:  dict[str, list[SettingDef]] = {}
        self._def_json_path: str = ""
        # Seed from hardcoded list
        self._load_from_list( SETTINGS )

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

        self._load_from_list( new_settings )
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
