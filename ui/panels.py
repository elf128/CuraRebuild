#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# panels.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   All FreeCAD task panels for CuraRebuild.
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
import pathlib
from functools import partial

from typing import TYPE_CHECKING

import FreeCAD
import FreeCADGui
from FreeCAD import Console

from PySide2 import QtCore, QtGui, QtWidgets
from PySide2.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
    QCheckBox, QRadioButton, QComboBox, QGroupBox, QTabWidget,
    QPushButton, QListWidget, QListWidgetItem,
    QScrollArea, QSizePolicy, QDialogButtonBox,
    QTextEdit, QMessageBox, QInputDialog,
)

from settings.schema import (
    SCHEMA, BY_CATEGORY, CURA_SCHEMA, SettingDef, Category,
    get_registry as _get_schema_registry,
)
from settings.stack import (
    MachineLayer, UserLayer, SettingsStack, SettingsRegistry
)
from settings.expr_eval import eval_enabled, eval_value, extract_dependencies
from registry_object import flush_registry

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Setting state — drives colour differentiation in the layer editor
# ---------------------------------------------------------------------------

class SettingState:
    # Standalone layer editor (5 states — no stack context needed)
    SCHEMA_DEFAULT: str = "schema_default"  # not in layer, no expr   → GREY
    SET_DEFAULT:    str = "set_default"     # in layer == schema def   → BLACK
    SET_OVERRIDE:   str = "set_override"    # in layer != schema def   → DARK RED
    CALCULATED:     str = "calculated"      # not in layer, has expr   → BLUE ITALIC
    EXPRESSION:     str = "expression"      # custom expr stored        → BLUE BOLD
    # Build volume editor extras (used when stack context available)
    DISABLED:       str = "disabled"        # enabled_expr → False      → GREY BG
    OVERRIDDEN:     str = "overridden"      # higher layer wins         → STRIKETHROUGH

# Colours — (foreground, background, bold, strikethrough, italic)
_STATE_STYLE = {
    SettingState.SCHEMA_DEFAULT: ( "#999999", "",        False, False, True  ),
    SettingState.SET_DEFAULT:    ( "#222222", "",        False, False, False ),
    SettingState.SET_OVERRIDE:   ( "#8b0000", "",        True,  False, False ),
    SettingState.CALCULATED:     ( "#2255aa", "",        False, False, True  ),
    SettingState.EXPRESSION:     ( "#2255aa", "#eef4ff", True,  False, False ),
    SettingState.DISABLED:       ( "#aaaaaa", "#f5f5f5", False, False, True  ),
    SettingState.OVERRIDDEN:     ( "#888888", "",        False, True,  False ),
}

def _apply_row_style(
    label:  QLabel,
    widget: QWidget,
    state:  str,
) -> None:
    """Apply visual style to a settings row based on its resolution state."""
    fg, bg, bold, strike, italic = _STATE_STYLE.get(
        state, _STATE_STYLE[ SettingState.SCHEMA_DEFAULT ]
    )

    # Label
    label_parts = []
    if fg:
        label_parts.append( f"color: { fg };" )
    if bg:
        label_parts.append(
            f"background-color: { bg }; padding: 1px 3px; border-radius: 2px;"
        )
    font = label.font()
    font.setBold( bold )
    font.setItalic( italic )
    font.setStrikeOut( strike )
    label.setFont( font )
    label.setStyleSheet( " ".join( label_parts ) if label_parts else "" )

    # Widget
    disabled = state == SettingState.DISABLED
    widget.setEnabled( not disabled )
    if state in ( SettingState.SCHEMA_DEFAULT, SettingState.DISABLED,
                  SettingState.OVERRIDDEN, SettingState.CALCULATED ):
        widget.setStyleSheet( "color: #888888;" )
    elif bg:
        widget.setStyleSheet( f"background-color: { bg };" )
    else:
        widget.setStyleSheet( "" )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_scroll(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    return scroll


def _reset_widget( widget: QWidget, sdef: SettingDef ) -> None:
    """Reset a widget to the schema default value."""
    default = sdef.default
    if isinstance( widget, QCheckBox ):
        widget.setChecked( bool( default ) )
    elif isinstance( widget, QComboBox ):
        idx = widget.findText( str( default ) )
        if idx >= 0:
            widget.setCurrentIndex( idx )
    elif isinstance( widget, QTextEdit ):
        widget.setPlainText( str( default ) )
    elif isinstance( widget, ( QSpinBox, QDoubleSpinBox ) ):
        widget.setValue( sdef.dtype( default ) )
    elif isinstance( widget, QLineEdit ):
        widget.setText( str( default ) )


def _build_stack_for_layer( layer, registry ) -> object:
    """
    Build a SettingsStack containing all registry layers so the editor
    can compute per-setting resolution states. Ensures the current layer
    being edited is included in the stack.
    Returns None if stack cannot be built.
    """
    try:
        from settings.stack import SettingsStack, MachineLayer as ML, UserLayer as UL
        machines = list( registry.all_machine_layers() )
        users    = list( registry.all_user_layers() )

        # Make sure the layer being edited is represented in the stack
        if isinstance( layer, ML ):
            if not any( m.id == layer.id for m in machines ):
                machines.insert( 0, layer )
            machine = layer  # editing the machine — use it as base
        else:
            if not any( u.id == layer.id for u in users ):
                users.append( layer )
            machine = machines[0] if machines else ML( name="__placeholder__" )

        stack = SettingsStack( machine, users )
        return stack
    except Exception:
        return None


def _make_setting_widget( sdef: SettingDef, current_value ) -> QWidget:
    """Return an appropriate input widget for a SettingDef."""

    # Enum — QComboBox regardless of dtype
    if sdef.options:
        w = QComboBox()
        for opt in sdef.options:
            w.addItem( str( opt ) )
        # Select current value; add it if not in the list (e.g. imported unknown value)
        cur_str = str( current_value )
        idx = w.findText( cur_str )
        if idx >= 0:
            w.setCurrentIndex( idx )
        else:
            w.addItem( cur_str )
            w.setCurrentIndex( w.count() - 1 )
        return w

    if sdef.dtype == bool:
        w = QCheckBox()
        w.setChecked( bool( current_value ) )
        return w

    if sdef.dtype == str:
        if sdef.key in ( "machine_start_gcode", "machine_end_gcode" ):
            w = QTextEdit()
            w.setPlainText( str( current_value ) )
            w.setMinimumHeight( 80 )
            return w
        w = QLineEdit()
        w.setText( str( current_value ) )
        return w

    if sdef.dtype == int:
        w = QSpinBox()
        w.setMinimum( int( sdef.min_val ) if sdef.min_val is not None else 0 )
        w.setMaximum( int( sdef.max_val ) if sdef.max_val is not None else 9999 )
        w.setValue( int( current_value ) )
        if sdef.unit:
            w.setSuffix( f" { sdef.unit }" )
        return w

    # float
    w = QDoubleSpinBox()
    w.setDecimals( 4 )
    w.setMinimum( float( sdef.min_val ) if sdef.min_val is not None else -1e6 )
    w.setMaximum( float( sdef.max_val ) if sdef.max_val is not None else  1e6 )
    w.setValue( float( current_value ) )
    w.setSingleStep( 0.1 )
    if sdef.unit:
        w.setSuffix( f" { sdef.unit }" )
    return w


def _read_widget_value( sdef: SettingDef, widget: QWidget ):
    """Read the current value back out of an input widget."""
    if isinstance( widget, QComboBox ):
        return widget.currentText()
    if sdef.dtype == bool:
        return widget.isChecked()
    if sdef.dtype == str:
        if isinstance( widget, QTextEdit ):
            return widget.toPlainText()
        return widget.text()
    if sdef.dtype == int:
        return widget.value()
    return widget.value()  # float / QDoubleSpinBox


def _confirm(parent, title: str, text: str) -> bool:
    reply = QMessageBox.question(
        parent, title, text,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return reply == QMessageBox.Yes


# ---------------------------------------------------------------------------
# LayerEditorWidget
#
# A reusable widget that displays all settings from a BaseLayer (or a subset
# of categories) with live edit capability. Used inside multiple panels.
# ---------------------------------------------------------------------------

class LayerEditorWidget(QWidget):
    """
    Displays settings grouped by category in a tab widget.
    Each tab is a scrollable form of label + input widget pairs.

    Parameters
    ----------
    layer : MachineLayer | UserLayer
        The layer being edited.
    categories : list[str] | None
        Which categories to show. None = all.
    show_all_settings : bool
        If True, show all schema settings; if False, only those set in layer.
    stack : SettingsStack | None
        If provided, enables colour differentiation based on full resolution.
    """

    def __init__(
        self,
        layer,
        categories: list[str] | None = None,
        show_all_settings: bool = True,
        stack=None,
        parent=None,
    ):
        super().__init__( parent )
        self._layer        = layer
        self._stack        = stack          # None = standalone, set = build volume
        self._categories   = categories
        self._show_all     = show_all_settings
        self._widgets:     dict[str, QWidget] = {}
        self._labels:      dict[str, QLabel]  = {}
        self._row_widgets: dict[str, QWidget] = {}
        self._effective:   dict = {}
        self._dirty:       set  = set()     # keys user has explicitly changed
        self._build_ui( categories, show_all_settings )

    # ------------------------------------------------------------------
    # Effective settings cache

    def _get_effective( self ) -> dict:
        """Return cached effective settings, rebuilding from stack if needed."""
        if not self._effective:
            if self._stack:
                try:
                    self._effective = self._stack.effective()
                except Exception:
                    pass
            if not self._effective:
                # No stack yet — seed from the layer's own values plus schema
                # defaults so that value_expr and enabled_expr can evaluate
                schema = _get_schema_registry()
                eff = { k: s.default for k, s in schema.schema.items() }
                eff.update( self._layer.as_dict() )
                self._effective = eff
        return self._effective

    def _invalidate_effective( self ) -> None:
        self._effective = {}

    # ------------------------------------------------------------------
    # State computation

    def _compute_state( self, key: str ) -> str:
        """
        Determine display state for a setting key.
        Standalone mode (no stack): 5 states.
        Build volume mode (stack set): also DISABLED and OVERRIDDEN.
        """
        schema = _get_schema_registry()
        sdef   = schema.schema.get( key )
        if sdef is None:
            return SettingState.SCHEMA_DEFAULT

        # Build volume mode — check disabled first
        if self._stack is not None and sdef.enabled_expr:
            if not eval_enabled( sdef.enabled_expr, self._get_effective() ):
                return SettingState.DISABLED

        # Custom expression stored in layer
        if self._layer.has_expression( key ):
            return SettingState.EXPRESSION

        layer_val = self._layer.get( key )

        # Not set in this layer
        if layer_val is None:
            if sdef.value_expr:
                return SettingState.CALCULATED
            return SettingState.SCHEMA_DEFAULT

        # Set in layer — compare to schema default
        from settings.schema import get_default
        schema_def = get_default( key )

        # Build volume mode: check if a higher layer overrides us
        if self._stack is not None:
            winning = self._stack.which_layer( key )
            if winning != "schema_default" and self._layer.name not in winning:
                return SettingState.OVERRIDDEN

        if layer_val == schema_def:
            return SettingState.SET_DEFAULT
        return SettingState.SET_OVERRIDE

    def _build_ui( self, categories, show_all_settings: bool ) -> None:
        layout = QVBoxLayout( self )
        layout.setContentsMargins( 0, 0, 0, 0 )

        # Reload from linked file before building UI
        if hasattr( self._layer, "is_linked" ) and self._layer.is_linked():
            ok = self._layer.reload_from_file()
            if not ok:
                from Common import Log, LogLevel
                Log( LogLevel.warning,
                    f"[LayerEditor] Could not reload from "
                    f"'{ self._layer.linked_path }' — using last known values\n" )
                # Show warning inline (non-blocking)
                from PySide2.QtWidgets import QLabel as _QLbl
                warn = _QLbl(
                    f"⚠ Linked file not found: { self._layer.linked_path }"
                )
                warn.setStyleSheet( "color: #c00; padding: 2px;" )
                layout.addWidget( warn )

        # --- Top toolbar: filter + def.json selector + import/export ---
        toolbar = QHBoxLayout()

        # Filter combo
        self._filter_combo = QComboBox()
        self._filter_combo.addItem( "Show all",               userData="all"      )
        self._filter_combo.addItem( "Hide disabled",          userData="no_dis"   )
        self._filter_combo.addItem( "Hide overridden",        userData="no_ovr"   )
        self._filter_combo.addItem( "Only set in this layer", userData="only_set" )
        self._filter_combo.currentIndexChanged.connect( lambda _: self._on_filter_changed() )
        toolbar.addWidget( QLabel( "Filter:" ) )
        toolbar.addWidget( self._filter_combo, stretch=1 )

        # Import / Export layer buttons
        self._import_fmt = QComboBox()
        self._import_fmt.addItem( "JSON",          userData="json"    )
        self._import_fmt.addItem( ".curaprofile",  userData="profile" )
        self._import_fmt.addItem( "G-code",        userData="gcode"   )
        self._import_fmt.setFixedWidth( 110 )
        toolbar.addWidget( self._import_fmt )
        btn_import = QPushButton( "Import…" )
        btn_export = QPushButton( "Export…" )
        btn_import.setToolTip( "Import layer settings" )
        btn_export.setToolTip( "Export this layer's settings to a JSON file" )
        btn_import.clicked.connect( self._on_import_layer )
        btn_export.clicked.connect( self._on_export_layer )
        toolbar.addWidget( btn_import )
        toolbar.addWidget( btn_export )

        # def.json selector
        btn_def = QPushButton( "⚙" )
        btn_def.setFixedWidth( 28 )
        btn_def.setToolTip( "Select fdmprinter.def.json source file" )
        btn_def.clicked.connect( self._on_select_def_json )
        toolbar.addWidget( btn_def )

        layout.addLayout( toolbar )

        # --- Link bar ---
        link_bar = QHBoxLayout()
        self._link_label = QLabel( "Linked file:" )
        self._link_label.setStyleSheet( "color: #666; font-size: 11px;" )
        self._link_path_label = QLabel( "— internal storage —" )
        self._link_path_label.setStyleSheet(
            "color: #888; font-size: 11px; font-style: italic;"
        )
        self._link_path_label.setWordWrap( False )
        self._link_path_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        btn_link   = QPushButton( "🔗 Link…" )
        btn_unlink = QPushButton( "Unlink" )
        btn_reload = QPushButton( "↺" )
        btn_link.setFixedHeight( 22 )
        btn_unlink.setFixedHeight( 22 )
        btn_reload.setFixedWidth( 28 )
        btn_reload.setFixedHeight( 22 )
        btn_reload.setToolTip( "Reload from linked file" )
        btn_link.clicked.connect( self._on_link )
        btn_unlink.clicked.connect( self._on_unlink )
        btn_reload.clicked.connect( self._on_reload_link )
        link_bar.addWidget( self._link_label )
        link_bar.addWidget( self._link_path_label, stretch=1 )
        link_bar.addWidget( btn_link )
        link_bar.addWidget( btn_unlink )
        link_bar.addWidget( btn_reload )
        layout.addLayout( link_bar )

        self._refresh_link_bar()

        # --- ApplyTo row (extruder targeting) — hidden for MachineLayer ---
        from settings.stack import MachineLayer as _ML
        self._show_apply_to = not isinstance( self._layer, _ML )

        self._apply_all_radio = QRadioButton( "All" )
        self._apply_sel_radio = QRadioButton( "Selected:" )
        self._apply_all_radio.setChecked( True )
        self._extruder_checks: list[QCheckBox] = []
        self._apply_extruder_widget = QWidget()
        self._extruder_layout = QHBoxLayout( self._apply_extruder_widget )
        self._extruder_layout.setContentsMargins( 0, 0, 0, 0 )
        self._apply_extruder_widget.setVisible( False )

        if self._show_apply_to:
            apply_bar = QHBoxLayout()
            apply_bar.addWidget( QLabel( "Apply to extruders:" ) )
            apply_bar.addWidget( self._apply_all_radio )
            apply_bar.addWidget( self._apply_sel_radio )
            apply_bar.addWidget( self._apply_extruder_widget )
            apply_bar.addStretch()
            self._apply_all_radio.toggled.connect( self._on_apply_radio_changed )
            layout.addLayout( apply_bar )
            self._load_apply_to()

        # --- Tab widget with settings ---
        self._tabs = QTabWidget()
        layout.addWidget( self._tabs )

        self._rebuild_tabs( categories, show_all_settings, filter_mode="all" )

    def _rebuild_tabs(
        self,
        categories,
        show_all_settings: bool,
        filter_mode: str = "all",
    ) -> None:
        """Build or rebuild the tab widget based on current filter mode."""
        # Disconnect all signals from old widgets before clearing them
        # to prevent spurious signal fires during garbage collection
        for widget in self._widgets.values():
            try:
                widget.blockSignals( True )
            except Exception:
                pass
        self._tabs.clear()
        self._widgets.clear()
        self._labels.clear()
        self._row_widgets.clear()
        self._dirty.clear()
        self._invalidate_effective()

        schema       = _get_schema_registry()
        cats_to_show = categories or sorted( schema.by_category.keys() )

        for cat in sorted( cats_to_show ):
            defs = schema.by_category.get( cat, [] )
            if not defs:
                continue

            # Apply filter
            visible_defs = []
            for sdef in defs:
                state = self._compute_state( sdef.key )
                if filter_mode == "no_dis" and state == SettingState.DISABLED:
                    continue
                if filter_mode == "no_ovr" and state == SettingState.OVERRIDDEN:
                    continue
                if filter_mode == "only_set":
                    # Only show settings explicitly set in this layer
                    if state in ( SettingState.SCHEMA_DEFAULT, SettingState.CALCULATED ):
                        continue
                    if not self._layer.has( sdef.key ):
                        continue
                if not show_all_settings and not self._layer.has( sdef.key ):
                    continue
                visible_defs.append( sdef )

            if not visible_defs:
                continue

            container = QWidget()
            form      = QFormLayout( container )
            form.setFieldGrowthPolicy( QFormLayout.ExpandingFieldsGrow )

            for sdef in visible_defs:
                current = self._layer.get( sdef.key )
                if current is None:
                    # For CALCULATED state show the computed value
                    if sdef.value_expr:
                        computed = eval_value(
                            sdef.value_expr,
                            self._get_effective(),
                            sdef.dtype,
                        )
                        current = computed if computed is not None else sdef.default
                    else:
                        current = sdef.default

                widget = _make_setting_widget( sdef, current )

                # Build rich tooltip: description + expressions
                tip_parts = []
                if sdef.description:
                    tip_parts.append( sdef.description )
                if sdef.value_expr:
                    tip_parts.append( f"\nCalculated: { sdef.value_expr }" )
                if sdef.enabled_expr:
                    tip_parts.append( f"\nEnabled when: { sdef.enabled_expr }" )
                widget.setToolTip( "\n".join( tip_parts ) )

                # Label
                label_text = sdef.label
                if sdef.unit and not isinstance( widget, ( QSpinBox, QDoubleSpinBox ) ):
                    label_text += f" ({ sdef.unit })"
                label = QLabel( label_text )
                label.setToolTip( "\n".join( tip_parts ) )

                # "×" clear button
                clear_btn = QPushButton( "×" )
                clear_btn.setFixedSize( 18, 18 )
                clear_btn.setFlat( True )
                clear_btn.setToolTip( "Remove override — revert to lower layer / default" )
                clear_btn.setStyleSheet(
                    "QPushButton { color: #888; font-weight: bold; border: none; }"
                    "QPushButton:hover { color: #c00; }"
                )

                # "..." move/copy button
                more_btn = QPushButton( "…" )
                more_btn.setFixedSize( 24, 18 )
                more_btn.setFlat( True )
                more_btn.setToolTip( "Copy / Move to another layer" )
                more_btn.setStyleSheet(
                    "QPushButton { color: #555; border: none; }"
                    "QPushButton:hover { color: #000; background: #ddd; border-radius:2px; }"
                )

                row_widget = QWidget()
                row_layout = QHBoxLayout( row_widget )
                row_layout.setContentsMargins( 0, 0, 0, 0 )
                row_layout.setSpacing( 2 )
                row_layout.addWidget( widget,    stretch=1 )
                row_layout.addWidget( more_btn              )
                row_layout.addWidget( clear_btn             )

                # Colour state
                state = self._compute_state( sdef.key )
                _apply_row_style( label, widget, state )

                form.addRow( label, row_widget )
                self._widgets[ sdef.key ]     = widget
                self._labels[ sdef.key ]      = label
                self._row_widgets[ sdef.key ] = row_widget

                self._connect_change_signal( widget, sdef.key )
                clear_btn.clicked.connect(
                    partial( self._on_clear_btn, sdef.key )
                )
                more_btn.clicked.connect(
                    partial( self._on_more_btn, sdef.key, more_btn )
                )

                # Special: inject extruder enable/disable row after extruder count
                from settings.stack import MachineLayer as _ML
                if sdef.key == "machine_extruder_count" and                         isinstance( self._layer, _ML ):
                    self._inject_extruder_enables( form, widget )

            scroll = _make_scroll( container )
            self._tabs.addTab( scroll, cat )

    # ------------------------------------------------------------------
    # Filter / toolbar actions

    def _on_filter_changed( self ) -> None:
        mode = self._filter_combo.currentData( QtCore.Qt.UserRole ) or "all"
        self._rebuild_tabs( self._categories, self._show_all, filter_mode=mode )

    def _on_select_def_json( self ) -> None:
        """Let user pick a different fdmprinter.def.json."""
        from PySide2.QtWidgets import QFileDialog
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Select fdmprinter.def.json",
            str( QtCore.QDir.homePath() ),
            "Definition files (*.def.json *.json);;All files (*)",
        )
        if not path_str:
            return
        try:
            schema = _get_schema_registry()
            n      = schema.load_from_def_json( path_str )
            QMessageBox.information(
                self, "Schema loaded",
                f"Loaded { n } settings from\n{ path_str }"
            )
            self._rebuild_tabs(
                self._categories, self._show_all,
                filter_mode=self._filter_combo.currentData( QtCore.Qt.UserRole ) or "all",
            )
        except Exception as e:
            QMessageBox.warning( self, "Load failed", str( e ) )

    def _on_import_layer( self ) -> None:
        """Import settings into this layer from JSON, .curaprofile, or gcode."""
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path

        fmt = self._import_fmt.currentData( QtCore.Qt.UserRole )               if hasattr( self, "_import_fmt" ) else "json"

        if fmt == "profile":
            filt = "Cura profiles (*.curaprofile);;All files (*)"
            title = "Import .curaprofile"
        elif fmt == "gcode":
            filt = "G-code files (*.gcode *.g *.gc *.gco);;All files (*)"
            title = "Import G-code"
        else:
            filt = "JSON files (*.json);;All files (*)"
            title = "Import Layer JSON"

        path_str, _ = QFileDialog.getOpenFileName(
            None, title, str( QtCore.QDir.homePath() ), filt,
        )
        if not path_str:
            return

        try:
            if fmt == "profile":
                from ui.profile_import import CuraProfileImport
                tmp = CuraProfileImport( Path( path_str ) ).to_user_layer()
            elif fmt == "gcode":
                from ui.profile_import import GcodeProfileImport
                tmp = GcodeProfileImport( Path( path_str ) ).to_user_layer()
            else:
                from settings.storage import JsonBackend
                tmp = JsonBackend( Path( path_str ).parent ).import_layer(
                    Path( path_str )
                )
            n = 0
            for key, val in tmp.as_dict().items():
                try:
                    self._layer.set( key, val )
                    n += 1
                except Exception:
                    pass
            self._invalidate_effective()
            self._rebuild_tabs(
                self._categories, self._show_all,
                filter_mode=self._filter_combo.currentData( QtCore.Qt.UserRole ) or "all",
            )
            QMessageBox.information(
                None, "Imported",
                f"Merged { n } settings from { Path( path_str ).name }"
            )
        except Exception as e:
            QMessageBox.warning( None, "Import failed", str( e ) )

    def _on_export_layer( self ) -> None:
        """Export this layer's settings to a JSON file."""
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path
        # Sync name from widget in case user hasn't clicked Save yet
        current_name = self._layer.name
        if hasattr( self, "_name_edit" ):
            typed = self._name_edit.text().strip()
            if typed:
                self._layer.name = typed
                current_name = typed
        path_str, _ = QFileDialog.getSaveFileName(
            None, "Export Layer",
            str( pathlib.Path( QtCore.QDir.homePath() ) / f"{ current_name }.json" ),
            "JSON files (*.json);;All files (*)",
        )
        if not path_str:
            return
        try:
            from settings.storage import JsonBackend
            JsonBackend( Path( path_str ).parent ).export_layer(
                self._layer, Path( path_str )
            )
            QMessageBox.information( self, "Exported", f"Saved to\n{ path_str }" )
        except Exception as e:
            QMessageBox.warning( self, "Export failed", str( e ) )

    # ------------------------------------------------------------------
    # "..." context menu — Copy/Move to layer

    def _on_more( self, key: str, btn: QWidget ) -> None:
        """Show context menu for copy/move operations."""
        from PySide2.QtWidgets import QMenu
        from PySide2.QtGui     import QCursor
        from Common            import Log, LogLevel

        # Collect all layers from the registry (not just the stack)
        # so the user can copy/move to any layer, even ones not in the
        # current build volume's stack.
        other_layers = []

        # Try registry first (preferred — all available layers)
        try:
            import FreeCAD
            from registry_object import get_registry
            doc      = FreeCAD.ActiveDocument
            registry = get_registry( doc )
            if registry:
                for layer in registry.all_machine_layers():
                    if layer.id != self._layer.id:
                        other_layers.append( layer )
                for layer in registry.all_user_layers():
                    if layer.id != self._layer.id:
                        other_layers.append( layer )
        except Exception as e:
            Log( LogLevel.debug, f"[LayerEditor] registry lookup: { e }\n" )

        # Fallback to stack if registry gave nothing
        if not other_layers and self._stack:
            for layer in self._stack.user_layers:
                if layer.id != self._layer.id:
                    other_layers.append( layer )
            ml = self._stack.machine_layer
            if ml.id != self._layer.id:
                other_layers.append( ml )

        Log( LogLevel.debug,
            f"[LayerEditor] _on_more key='{ key }' "
            f"other_layers={ [l.name for l in other_layers] }\n" )

        menu = QMenu( self )

        if other_layers:
            copy_menu  = menu.addMenu( "Copy to Layer…" )
            copyd_menu = menu.addMenu( "Copy to Layer with Dependencies…" )
            move_menu  = menu.addMenu( "Move to Layer…" )
            moved_menu = menu.addMenu( "Move to Layer with Dependencies…" )

            for target in other_layers:
                copy_menu.addAction( target.name ).triggered.connect(
                    partial( self._copy_to, key, target, False )
                )
                copyd_menu.addAction( target.name ).triggered.connect(
                    partial( self._copy_to, key, target, True )
                )
                move_menu.addAction( target.name ).triggered.connect(
                    partial( self._move_to, key, target, False )
                )
                moved_menu.addAction( target.name ).triggered.connect(
                    partial( self._move_to, key, target, True )
                )
        else:
            a = menu.addAction(
                "No other layers available — create more layers first"
            )
            a.setEnabled( False )

        self._active_menu = menu   # keep reference alive until selection
        menu.exec_( QCursor.pos() )
        self._active_menu = None

    def _resolve_keys_with_deps( self, key: str ) -> list[str]:
        """
        Show a checkbox dialog listing the key + all its dependencies.
        Returns the keys the user confirmed to include.
        """
        schema   = _get_schema_registry()
        dep_keys = schema.get_dependencies( key )
        # Also include dependents (settings that reference this one)
        dep_keys += schema.get_dependents( key )
        dep_keys  = [ k for k in set( dep_keys ) if k != key ]

        if not dep_keys:
            return [ key ]

        from PySide2.QtWidgets import (
            QDialog, QVBoxLayout, QLabel as _QLabel,
            QListWidget, QListWidgetItem, QPushButton as _QPB, QHBoxLayout,
        )
        dlg = QDialog( self )
        dlg.setWindowTitle( "Select dependencies to include" )
        layout = QVBoxLayout( dlg )
        layout.addWidget( _QLabel( f"Settings related to  '{ key }':" ) )

        lst = QListWidget()
        for k in [ key ] + dep_keys:
            item = QListWidgetItem( k )
            item.setCheckState( QtCore.Qt.Checked )
            lst.addItem( item )
        layout.addWidget( lst )

        btns = QHBoxLayout()
        ok  = _QPB( "OK" )
        can = _QPB( "Cancel" )
        ok.clicked.connect( dlg.accept )
        can.clicked.connect( dlg.reject )
        btns.addWidget( ok );  btns.addWidget( can )
        layout.addLayout( btns )

        if dlg.exec_() != QDialog.Accepted:
            return []

        result = []
        for i in range( lst.count() ):
            item = lst.item( i )
            if item.checkState() == QtCore.Qt.Checked:
                result.append( item.text() )
        return result

    def _copy_to( self, key: str, target, with_deps: bool, *args ) -> None:
        keys = self._resolve_keys_with_deps( key ) if with_deps else [ key ]
        for k in keys:
            val = self._layer.get( k )
            if val is not None:
                try:
                    target.set( k, val )
                except Exception:
                    pass
        from Common import Log, LogLevel
        Log( LogLevel.info,
            f"[LayerEditor] Copied { keys } to '{ target.name }'\n" )

    def _move_to( self, key: str, target, with_deps: bool, *args ) -> None:
        self._copy_to( key, target, with_deps )
        keys = self._resolve_keys_with_deps( key ) if with_deps else [ key ]
        for k in keys:
            self._layer.delete( k )
            widget = self._widgets.get( k )
            label  = self._labels.get( k )
            sdef   = _get_schema_registry().schema.get( k )
            if widget and sdef:
                widget.blockSignals( True )
                try:
                    _reset_widget( widget, sdef )
                finally:
                    widget.blockSignals( False )
            if label and widget:
                state = self._compute_state( k )
                _apply_row_style( label, widget, state )

    # ------------------------------------------------------------------
    # Extruder enable/disable (injected after machine_extruder_count row)

    def _inject_extruder_enables(
        self,
        form,           # QFormLayout
        count_widget,   # the QSpinBox for machine_extruder_count
    ) -> None:
        """
        Add a sub-row of extruder enable checkboxes immediately after the
        machine_extruder_count row. Only shown for MachineLayer.
        """
        # Container widget for the checkboxes
        ext_widget = QWidget()
        ext_layout = QHBoxLayout( ext_widget )
        ext_layout.setContentsMargins( 0, 0, 0, 0 )
        ext_layout.setSpacing( 6 )

        # Read currently enabled extruders
        enabled_raw = self._layer.get( "_fc_enabled_extruders" )
        n = count_widget.value() if hasattr( count_widget, "value" ) else 1
        if enabled_raw is None:
            enabled = set( range( n ) )
        else:
            try:
                enabled = { int(x.strip())
                            for x in str(enabled_raw).split(",")
                            if x.strip() }
            except ValueError:
                enabled = set( range( n ) )

        checks = []
        for i in range( n ):
            cb = QCheckBox( f"{ i }" )
            cb.setChecked( i in enabled )
            checks.append( cb )
            ext_layout.addWidget( cb )
        ext_layout.addStretch()

        # Save checks reference so count changes can rebuild
        self._ext_enable_checks = checks
        self._ext_enable_widget  = ext_widget
        self._ext_enable_form    = form

        def _save( *_ ):
            enabled_ids = [
                str(i) for i, cb in enumerate( self._ext_enable_checks )
                if cb.isChecked()
            ]
            self._layer._data["_fc_enabled_extruders"] = ",".join(enabled_ids)

        for cb in checks:
            cb.stateChanged.connect( _save )

        # Rebuild when count changes
        def _on_count_changed( new_val ):
            self._rebuild_extruder_enable_row( form, new_val )

        count_widget.valueChanged.connect( _on_count_changed )

        form.addRow( QLabel( "Enabled:" ), ext_widget )

    def _rebuild_extruder_enable_row(
        self, form, count: int
    ) -> None:
        """Rebuild extruder enable checkboxes when count changes."""
        if not hasattr( self, "_ext_enable_widget" ):
            return

        # Preserve currently checked indices
        old_enabled = {
            i for i, cb in enumerate( self._ext_enable_checks )
            if cb.isChecked()
        }

        # Clear old checkboxes from the existing container widget
        old_layout = self._ext_enable_widget.layout()
        while old_layout.count():
            item = old_layout.takeAt( 0 )
            if item.widget():
                item.widget().deleteLater()

        # Rebuild checkboxes in-place inside the existing container
        checks = []
        for i in range( count ):
            cb = QCheckBox( f"{ i }" )
            cb.setChecked( i in old_enabled )
            checks.append( cb )
            old_layout.addWidget( cb )
        old_layout.addStretch()

        self._ext_enable_checks = checks

        def _save( *_ ):
            enabled_ids = [
                str(i) for i, cb in enumerate( self._ext_enable_checks )
                if cb.isChecked()
            ]
            self._layer._data["_fc_enabled_extruders"] = ",".join(enabled_ids)

        for cb in checks:
            cb.stateChanged.connect( _save )

        _save()

    # ------------------------------------------------------------------
    # ApplyTo (extruder targeting)

    def _load_apply_to( self ) -> None:
        """Read ApplyTo from FP and configure the radio/checkboxes."""
        fp       = self._get_layer_fp()
        apply_to = getattr( fp, "ApplyTo", "all" ).strip().lower() if fp else "all"

        # Determine extruder count from machine layer in registry
        n_ext = 1
        try:
            from registry_object import get_registry
            import FreeCAD
            doc = FreeCAD.ActiveDocument
            if doc:
                reg = get_registry( doc )
                if reg:
                    machines = reg.all_machine_layers()
                    if machines:
                        n_ext = int( machines[0].get( "machine_extruder_count" ) or 1 )
        except Exception:
            pass

        # Rebuild extruder checkboxes
        for cb in self._extruder_checks:
            self._extruder_layout.removeWidget( cb )
            cb.deleteLater()
        self._extruder_checks = []
        for i in range( n_ext ):
            cb = QCheckBox( str( i ) )
            self._extruder_checks.append( cb )
            self._extruder_layout.addWidget( cb )

        if not apply_to or apply_to == "all":
            self._apply_all_radio.setChecked( True )
            self._apply_extruder_widget.setVisible( False )
        else:
            self._apply_sel_radio.setChecked( True )
            self._apply_extruder_widget.setVisible( True )
            try:
                indices = { int(x.strip()) for x in apply_to.split(",") if x.strip() }
                for i, cb in enumerate( self._extruder_checks ):
                    cb.setChecked( i in indices )
            except ValueError:
                for cb in self._extruder_checks:
                    cb.setChecked( True )

    def _on_apply_radio_changed( self, all_checked: bool ) -> None:
        self._apply_extruder_widget.setVisible( not all_checked )
        self._save_apply_to()

    def _save_apply_to( self ) -> None:
        """Write current ApplyTo value back to the layer FP object."""
        fp = self._get_layer_fp()
        if fp is None:
            return
        if self._apply_all_radio.isChecked():
            fp.ApplyTo = "all"
        else:
            indices = [
                str(i) for i, cb in enumerate( self._extruder_checks )
                if cb.isChecked()
            ]
            fp.ApplyTo = ",".join( indices ) if indices else "all"

    def _get_layer_fp( self ):
        """Return the FP object for self._layer, or None."""
        try:
            import FreeCAD
            from registry_object import get_registry_fp
            doc = FreeCAD.ActiveDocument
            if not doc:
                return None
            reg_fp = get_registry_fp( doc )
            if not reg_fp or not hasattr( reg_fp, "Proxy" ):
                return None
            fp_name = reg_fp.Proxy._layer_fps.get( self._layer.id )
            if not fp_name:
                return None
            return doc.getObject( fp_name )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Linked file methods

    def _refresh_link_bar( self ) -> None:
        """Update the link path label to reflect current state."""
        if not hasattr( self, "_link_path_label" ):
            return
        linked = self._layer.linked_path if hasattr( self._layer, "linked_path" ) else None
        if linked:
            from pathlib import Path
            self._link_path_label.setText( str( Path( linked ).name ) )
            self._link_path_label.setToolTip( linked )
            self._link_path_label.setStyleSheet(
                "color: #1a6a1a; font-size: 11px; font-weight: bold;"
            )
        else:
            self._link_path_label.setText( "— internal storage —" )
            self._link_path_label.setToolTip( "" )
            self._link_path_label.setStyleSheet(
                "color: #888; font-size: 11px; font-style: italic;"
            )

    def _on_link( self ) -> None:
        """Let user pick a JSON file to link this layer to."""
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path
        from Common import Log, LogLevel

        current = self._layer.linked_path or str(
            pathlib.Path( QtCore.QDir.homePath() ) / f"{ self._layer.name }.json"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            None, "Link layer to JSON file",
            current,
            "JSON files (*.json);;All files (*)",
        )
        if not path_str:
            return

        self._layer.link( path_str )

        # Write current data to the file immediately
        if not pathlib.Path( path_str ).exists():
            # New file — write current data
            self._layer.flush_to_file()
        else:
            # Existing file — ask user whether to load from it or overwrite
            reply = QMessageBox.question(
                None,
                "File exists",
                f"{ pathlib.Path( path_str ).name } already exists.\n\n"
                "Load settings FROM this file into the layer?\n"
                "(No = overwrite file with current layer settings)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                ok = self._layer.reload_from_file()
                if not ok:
                    QMessageBox.warning(
                        None, "Reload failed",
                        f"Could not read { path_str }"
                    )
                else:
                    self._invalidate_effective()
                    self._rebuild_tabs(
                        self._categories, self._show_all,
                        filter_mode=self._filter_combo.currentData(
                            QtCore.Qt.UserRole ) or "all",
                    )
            else:
                self._layer.flush_to_file()

        # Persist link path on FP object
        self._persist_link()
        self._refresh_link_bar()
        Log( LogLevel.info,
            f"[LayerEditor] Linked '{ self._layer.name }' → { path_str }\n" )

    def _on_unlink( self ) -> None:
        """Remove the link — layer reverts to internal storage."""
        if not self._layer.is_linked():
            return
        from Common import Log, LogLevel
        self._layer.link( None )
        self._persist_link()
        self._refresh_link_bar()
        Log( LogLevel.info,
            f"[LayerEditor] Unlinked '{ self._layer.name }'\n" )

    def _on_reload_link( self ) -> None:
        """Reload layer data from the linked file."""
        if not self._layer.is_linked():
            QMessageBox.information( None, "Not linked",
                "This layer is not linked to a file." )
            return
        ok = self._layer.reload_from_file()
        if not ok:
            QMessageBox.warning(
                None, "Reload failed",
                f"Could not read:\n{ self._layer.linked_path }\n\n"
                "Falling back to last known values."
            )
            return
        self._invalidate_effective()
        self._rebuild_tabs(
            self._categories, self._show_all,
            filter_mode=self._filter_combo.currentData(
                QtCore.Qt.UserRole ) or "all",
        )

    def _persist_link( self ) -> None:
        """Write the linked_path onto the FP object so it survives document save."""
        try:
            import FreeCAD
            from registry_object import get_registry_fp
            doc    = FreeCAD.ActiveDocument
            reg_fp = get_registry_fp( doc )
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                fp_name = reg_fp.Proxy._layer_fps.get( self._layer.id )
                if fp_name:
                    child_fp = doc.getObject( fp_name )
                    if child_fp and hasattr( child_fp, "LinkedFile" ):
                        child_fp.LinkedFile = self._layer.linked_path or ""
            # Also flush registry so linked_path is in the JSON
            from registry_object import flush_registry
            flush_registry( doc )
        except Exception as e:
            from Common import Log, LogLevel
            Log( LogLevel.debug, f"[LayerEditor] _persist_link: { e }\n" )

    def _on_clear_btn( self, key: str, checked: bool = False ) -> None:
        """Wrapper so partial() works regardless of checked arg."""
        self._on_clear( key )

    def _on_more_btn( self, key: str, btn: QWidget, checked: bool = False ) -> None:
        """Wrapper so partial() works regardless of checked arg."""
        self._on_more( key, btn )

    def _connect_change_signal( self, widget: QWidget, key: str ) -> None:
        """Connect the appropriate change signal to _on_widget_changed."""
        cb = lambda *args, k=key: self._on_widget_changed( k )
        if isinstance( widget, QCheckBox ):
            widget.stateChanged.connect( cb )
        elif isinstance( widget, QComboBox ):
            widget.currentIndexChanged.connect( cb )
        elif isinstance( widget, QTextEdit ):
            widget.textChanged.connect( cb )
        elif isinstance( widget, ( QSpinBox, QDoubleSpinBox ) ):
            widget.valueChanged.connect( cb )
        elif isinstance( widget, QLineEdit ):
            widget.textChanged.connect( cb )

    def _on_widget_changed( self, key: str ) -> None:
        """
        Widget value changed by user interaction.
        Marks key as dirty and writes to layer immediately.
        Does NOT write if value equals schema default and key wasn't set before.
        """
        widget = self._widgets.get( key )
        label  = self._labels.get( key )
        if widget is None or label is None:
            return
        schema = _get_schema_registry()
        sdef   = schema.schema.get( key )
        if sdef is None:
            return

        val = _read_widget_value( sdef, widget )
        try:
            validated = sdef.safe_validate( val )
        except Exception:
            return

        from settings.schema import get_default
        schema_def = get_default( key )
        was_set    = self._layer.has( key )

        if not was_set and validated == schema_def:
            # User changed widget back to default and key wasn't in layer — ignore
            pass
        else:
            # Write to layer and mark dirty
            try:
                self._layer.set( key, validated )
                self._dirty.add( key )
            except Exception:
                pass

        self._invalidate_effective()

        # Refresh this row
        state = self._compute_state( key )
        _apply_row_style( label, widget, state )

        # Refresh dependent rows
        for dep_key in schema.get_dependents( key ):
            dep_widget = self._widgets.get( dep_key )
            dep_label  = self._labels.get( dep_key )
            dep_sdef   = schema.schema.get( dep_key )
            if dep_widget is None or dep_sdef is None:
                continue
            if dep_sdef.value_expr:
                computed = eval_value(
                    dep_sdef.value_expr,
                    self._get_effective(),
                    dep_sdef.dtype,
                )
                if computed is not None:
                    dep_widget.blockSignals( True )
                    try:
                        if isinstance( dep_widget, ( QSpinBox, QDoubleSpinBox ) ):
                            dep_widget.setValue( dep_sdef.dtype( computed ) )
                        elif isinstance( dep_widget, QLineEdit ):
                            dep_widget.setText( str( computed ) )
                    finally:
                        dep_widget.blockSignals( False )
            if dep_label:
                _apply_row_style( dep_label, dep_widget,
                                  self._compute_state( dep_key ) )

    def _on_clear( self, key: str ) -> None:
        """Remove this key from the layer and reset widget to schema default."""
        self._layer.delete( key )
        self._dirty.discard( key )

        widget = self._widgets.get( key )
        label  = self._labels.get( key )
        sdef   = SCHEMA.get( key )
        if widget is None or sdef is None:
            return

        # Reset widget to schema default without re-triggering _on_widget_changed
        widget.blockSignals( True )
        try:
            _reset_widget( widget, sdef )
        finally:
            widget.blockSignals( False )
        self._invalidate_effective()

        if label:
            state = self._compute_state( key )
            _apply_row_style( label, widget, state )

        # If filter hides cleared settings, rebuild the tab to remove the row
        current_filter = "all"
        if hasattr( self, "_filter_combo" ):
            current_filter = self._filter_combo.currentData(
                QtCore.Qt.UserRole ) or "all"
        if current_filter in ( "only_set", ):
            # Row should disappear — full rebuild
            self._rebuild_tabs(
                self._categories, self._show_all,
                filter_mode=current_filter,
            )

    def apply( self ) -> list[str]:
        """
        Flush only keys the user explicitly changed (_dirty set).
        Does NOT write all widget values — that would pollute sparse layers.
        """
        schema  = _get_schema_registry()
        changed = []
        for key in list( self._dirty ):
            widget = self._widgets.get( key )
            sdef   = schema.schema.get( key )
            if widget is None or sdef is None:
                continue
            try:
                new_val   = _read_widget_value( sdef, widget )
                validated = sdef.safe_validate( new_val )
                old_val   = self._layer.get( key )
                if validated != old_val:
                    self._layer.set( key, validated )
                    changed.append( key )
            except Exception as e:
                Console.PrintWarning(
                    f"[LayerEditor] Could not apply '{ key }': { e }\n" )
        self._dirty.clear()
        # Persist ApplyTo selection
        self._save_apply_to()
        return changed

# ---------------------------------------------------------------------------
# MachineLayerPanel
# ---------------------------------------------------------------------------

class MachineLayerPanel:
    """
    Task panel for creating or editing a MachineLayer.

    Features:
      - Name field
      - Full settings editor (Machine + G-Code categories)
      - Import from Cura / OrcaSlicer definition file (auto-scan or browse)
      - Import from any JSON file exported by CuraRebuild
    """

    def __init__(
        self,
        registry: SettingsRegistry,
        doc: FreeCAD.Document,
        existing_layer: MachineLayer | None = None,
    ):
        self._registry = registry
        self._doc      = doc
        self._layer    = existing_layer or MachineLayer( name="New Machine" )
        self._is_new   = existing_layer is None

        self.form = QWidget()
        self.form.setMinimumWidth( 520 )
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui( self ) -> None:
        layout = QVBoxLayout( self.form )

        # --- Name row ---
        name_row = QHBoxLayout()
        name_row.addWidget( QLabel( "Machine name:" ) )
        self._name_edit = QLineEdit( self._layer.name )
        self._name_edit.setPlaceholderText( "Enter machine name…" )
        self._name_edit.textChanged.connect( self._on_name_changed )
        name_row.addWidget( self._name_edit )
        layout.addLayout( name_row )

        # --- Import toolbar ---
        import_grp = QGroupBox( "Import from existing definition" )
        import_layout = QHBoxLayout( import_grp )

        self._import_combo = QComboBox()
        self._import_combo.setPlaceholderText( "Select source application…" )
        self._import_combo.addItem( "Cura / UltiMaker Cura",       userData="cura"    )
        self._import_combo.addItem( "OrcaSlicer / BambuStudio",   userData="orca"    )
        self._import_combo.addItem( "CuraRebuild JSON export",    userData="json"    )
        self._import_combo.addItem( ".curaprofile archive",       userData="profile" )
        self._import_combo.addItem( "Sliced G-code (Cura)",       userData="gcode"   )
        import_layout.addWidget( self._import_combo, stretch=2 )

        btn_scan   = QPushButton( "Scan…" )
        btn_browse = QPushButton( "Browse file…" )
        btn_scan.setToolTip( "Scan known application directories for machine definitions" )
        btn_browse.setToolTip( "Browse for a specific .def.json or .json file" )
        btn_scan.clicked.connect( self._on_scan )
        btn_browse.clicked.connect( self._on_browse )
        import_layout.addWidget( btn_scan )
        import_layout.addWidget( btn_browse )

        layout.addWidget( import_grp )

        # --- Settings editor ---
        # Exclude EXPERIMENTAL — those are object-level overrides
        self._stack  = _build_stack_for_layer( self._layer, self._registry )
        self._editor = LayerEditorWidget(
            self._layer,
            categories=[ Category.MACHINE, Category.GCODE ],
            show_all_settings=True,
            stack=self._stack,
        )
        layout.addWidget( self._editor, stretch=1 )

    def _on_name_changed( self, text: str ) -> None:
        """Update layer name live and sync FP Label in the tree."""
        name = text.strip()
        if not name:
            return
        self._layer.name = name
        # Update tree label if FP object exists
        try:
            import FreeCAD
            from registry_object import get_registry_fp
            reg_fp = get_registry_fp( self._doc )
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                fp_name = reg_fp.Proxy._layer_fps.get( self._layer.id )
                if fp_name:
                    child_fp = self._doc.getObject( fp_name )
                    if child_fp:
                        child_fp.Label = name
        except Exception:
            pass

    def show_as_dialog( self ) -> bool:
        """
        Open as a standalone QDialog rather than a FreeCAD task panel.
        Use this when already inside another task panel (RegistryPanel).
        Returns True if accepted.
        """
        from PySide2.QtWidgets import QDialog
        dlg = QDialog( self.form.parentWidget() )
        dlg.setWindowTitle( "Machine Definition" )
        dlg.setMinimumSize( 560, 640 )

        layout = QVBoxLayout( dlg )
        layout.addWidget( self.form )

        btns = QHBoxLayout()
        btn_ok     = QPushButton( "Save" )
        btn_cancel = QPushButton( "Cancel" )
        btn_ok.clicked.connect( dlg.accept )
        btn_cancel.clicked.connect( dlg.reject )
        btns.addWidget( btn_ok )
        btns.addWidget( btn_cancel )
        layout.addLayout( btns )

        if dlg.exec_() == QDialog.Accepted:
            name = self._name_edit.text().strip()
            if not name:
                QMessageBox.warning( dlg, "Name required", "Please enter a machine name." )
                return False
            self._layer.name = name
            self._editor.apply()
            from registry_object import get_registry_fp
            reg_fp = get_registry_fp( self._doc )
            if self._is_new:
                if reg_fp and hasattr( reg_fp, "Proxy" ):
                    reg_fp.Proxy.add_layer( reg_fp, self._layer )
                else:
                    self._registry.add_machine_layer( self._layer )
                # Also register any profile layer created during Cura import
                profile = getattr( self, "_imported_profile", None )
                if profile is not None:
                    try:
                        if reg_fp and hasattr( reg_fp, "Proxy" ):
                            reg_fp.Proxy.add_layer( reg_fp, profile )
                        else:
                            self._registry.add_user_layer( profile )
                        from Common import Log, LogLevel
                        Log( LogLevel.info,
                            f"[CuraRebuild] Registered profile layer "
                            f"'{ profile.name }'\n" )
                    except Exception as e:
                        from Common import Log, LogLevel
                        Log( LogLevel.warning,
                            f"[CuraRebuild] Could not register profile: { e }\n" )
            else:
                from layer_fp_object import link_layer_fp
                if reg_fp and hasattr( reg_fp, "Proxy" ):
                    fp_name = reg_fp.Proxy._layer_fps.get( self._layer.id )
                    if fp_name:
                        child_fp = self._doc.getObject( fp_name )
                        if child_fp:
                            link_layer_fp( child_fp, self._layer )
            flush_registry( self._doc )
            from Common import Log, LogLevel
            Log( LogLevel.info, f"[CuraRebuild] Machine layer '{ name }' saved.\n" )
            return True
        return False

    # ------------------------------------------------------------------
    # Import actions

    def _on_scan( self ) -> None:
        """Scan / auto-import based on selected source."""
        source = self._import_combo.currentData( QtCore.Qt.UserRole ) or "cura"
        if source == "profile":
            self._import_cura_profile()
        elif source == "gcode":
            self._import_from_gcode()
        elif source == "json":
            self._import_from_json_file()
        else:
            self._scan_cura_instances()

    def _scan_cura_instances( self ) -> None:
        """Scan Cura config directories for saved machine instances."""
        from ui.cura_import import (
            scan_cura_machines, _cura_config_dirs,
            scan_definition_files, load_definition_as_instance,
        )
        QtWidgets.QApplication.setOverrideCursor( QtCore.Qt.WaitCursor )
        try:
            instances = scan_cura_machines()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if instances:
            self._show_instance_picker( instances )
            return
        version_dirs = _cura_config_dirs()
        if not version_dirs:
            QMessageBox.information(
                self.form, "Cura not found",
                "No Cura installation or configuration was found.\n"
                "Try 'Browse file…' to locate a definition file manually.",
            )
            return
        all_defs = []
        for vdir in version_dirs:
            for name, path in scan_definition_files( vdir ):
                all_defs.append( load_definition_as_instance( name, path, vdir ) )
        if not all_defs:
            QMessageBox.information(
                self.form, "No definitions found",
                "Cura was found but no machine definitions could be read.",
            )
            return
        self._show_instance_picker( all_defs )

    def _on_browse( self ) -> None:
        """Browse for a file — delegates based on combo selection."""
        source = self._import_combo.currentData( QtCore.Qt.UserRole ) or "cura"
        if source == "profile":
            self._import_cura_profile()
        elif source == "gcode":
            self._import_from_gcode()
        elif source == "json":
            self._import_from_json_file()
        else:
            self._browse_definition_file()

    def _browse_definition_file( self ) -> None:
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path
        from ui.cura_import import load_json_file
        path_str, _ = QFileDialog.getOpenFileName(
            self.form, "Open machine definition",
            str( QtCore.QDir.homePath() ),
            "Definition files (*.def.json *.json *.cfg);;All files (*)",
        )
        if not path_str:
            return
        path = Path( path_str )
        inst = load_json_file( path )
        if inst is None:
            QMessageBox.warning(
                self.form, "Could not load file",
                f"{ path.name } could not be parsed as a machine definition.",
            )
            return
        self._apply_instance( inst )

    def _import_from_json_file( self ) -> None:
        """Import settings from a CuraRebuild JSON export."""
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path
        from settings.storage import JsonBackend
        path_str, _ = QFileDialog.getOpenFileName(
            None, "Import Layer JSON",
            str( QtCore.QDir.homePath() ),
            "JSON files (*.json);;All files (*)",
        )
        if not path_str:
            return
        try:
            tmp = JsonBackend( Path( path_str ).parent ).import_layer( Path( path_str ) )
            for key, val in tmp.as_dict().items():
                try:
                    self._layer.set( key, val )
                except Exception:
                    pass
            self._editor._invalidate_effective()
            self._editor._rebuild_tabs(
                self._editor._categories, self._editor._show_all,
                filter_mode=self._editor._filter_combo.currentData(
                    QtCore.Qt.UserRole ) or "all",
            )
        except Exception as e:
            QMessageBox.warning( None, "Import failed", str( e ) )

    def _import_cura_profile( self ) -> None:
        """Import from a .curaprofile archive into a new UserLayer."""
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path
        from ui.profile_import import CuraProfileImport
        path_str, _ = QFileDialog.getOpenFileName(
            None, "Open .curaprofile",
            str( QtCore.QDir.homePath() ),
            "Cura profiles (*.curaprofile);;All files (*)",
        )
        if not path_str:
            return
        QtWidgets.QApplication.setOverrideCursor( QtCore.Qt.WaitCursor )
        try:
            imp        = CuraProfileImport( Path( path_str ) )
            user_layer = imp.to_user_layer()
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QMessageBox.warning( None, "Import failed", str( e ) )
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._imported_profile = user_layer
        QMessageBox.information(
            None, "Profile imported",
            f"Imported '{user_layer.name}' with "
            f"{ len( user_layer.as_dict() ) } settings.\n\n"
            f"The profile layer will be created when you click Save."
        )

    def _import_from_gcode( self ) -> None:
        """Import settings from a Cura-sliced .gcode file."""
        from PySide2.QtWidgets import QFileDialog
        from pathlib import Path
        from ui.profile_import import GcodeProfileImport
        path_str, _ = QFileDialog.getOpenFileName(
            None, "Open G-code file",
            str( QtCore.QDir.homePath() ),
            "G-code files (*.gcode *.g *.gc *.gco);;All files (*)",
        )
        if not path_str:
            return
        QtWidgets.QApplication.setOverrideCursor( QtCore.Qt.WaitCursor )
        try:
            imp        = GcodeProfileImport( Path( path_str ) )
            user_layer = imp.to_user_layer()
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QMessageBox.warning( None, "Import failed", str( e ) )
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not user_layer.as_dict():
            QMessageBox.warning(
                None, "No settings found",
                "No Cura settings were found in this G-code file.\n"
                "Make sure it was sliced with Cura."
            )
            return
        self._imported_profile = user_layer
        QMessageBox.information(
            None, "G-code imported",
            f"Imported '{user_layer.name}' with "
            f"{ len( user_layer.as_dict() ) } settings.\n\n"
            f"The profile layer will be created when you click Save."
        )

    def _show_instance_picker( self, instances ) -> None:
        """Show a searchable list dialog for the user to pick a machine."""
        from PySide2.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout,
            QListWidget, QListWidgetItem, QLineEdit,
        )

        dlg = QDialog( self.form )
        dlg.setWindowTitle( f"Select machine  ({ len( instances ) } found)" )
        dlg.resize( 500, 400 )

        layout = QVBoxLayout( dlg )

        # Search filter
        search = QLineEdit()
        search.setPlaceholderText( "Filter…" )
        layout.addWidget( search )

        lst = QListWidget()
        for inst in instances:
            item = QListWidgetItem( inst.display_name )
            item.setData( QtCore.Qt.UserRole, inst )
            lst.addItem( item )
        layout.addWidget( lst )

        def _filter( text ):
            for i in range( lst.count() ):
                lst.item( i ).setHidden(
                    text.lower() not in lst.item( i ).text().lower()
                )

        search.textChanged.connect( _filter )

        btns = QHBoxLayout()
        btn_ok     = QPushButton( "Import" )
        btn_cancel = QPushButton( "Cancel" )
        btn_ok.clicked.connect( dlg.accept )
        btn_cancel.clicked.connect( dlg.reject )
        btns.addWidget( btn_ok )
        btns.addWidget( btn_cancel )
        layout.addLayout( btns )

        if dlg.exec_() != QDialog.Accepted:
            return

        selected = lst.currentItem()
        if selected:
            self._apply_instance( selected.data( QtCore.Qt.UserRole ) )

    def _apply_instance( self, inst ) -> None:
        """
        Import a MachineInstance:
          - Machine-home settings → current MachineLayer
          - Everything else → a new UserLayer registered in the registry
        Rebuilds the editor to reflect imported machine values.
        """
        from Common import Log, LogLevel

        QtWidgets.QApplication.setOverrideCursor( QtCore.Qt.WaitCursor )
        try:
            machine_layer, profile_layer = inst.to_layers()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        # Apply current editor values first so manual edits are preserved
        self._editor.apply()

        # Merge imported machine settings into the current layer
        for key, value in machine_layer.as_dict().items():
            try:
                self._layer.set( key, value )
            except Exception:
                pass

        # Update name field and layer object
        if self._name_edit.text().strip() in ( "", "New Machine" ):
            self._layer.name = inst.name          # update layer object directly
            self._name_edit.blockSignals( True )  # prevent double-update
            self._name_edit.setText( inst.name )
            self._name_edit.blockSignals( False )

        # Store profile layer for potential later use — it gets registered
        # only when the user saves (show_as_dialog accepted).
        self._imported_profile = profile_layer
        if profile_layer is not None:
            Log( LogLevel.info,
                f"[CuraRebuild] Profile layer '{ profile_layer.name }' "
                f"ready ({len(profile_layer.as_dict())} settings).\n" )

        # Rebuild editor in-place so widgets show imported machine values
        layout = self.form.layout()
        layout.removeWidget( self._editor )
        self._editor.deleteLater()

        self._stack  = _build_stack_for_layer( self._layer, self._registry )
        self._editor = LayerEditorWidget(
            self._layer,
            categories=[ Category.MACHINE, Category.GCODE ],
            show_all_settings=True,
            stack=self._stack,
        )
        layout.addWidget( self._editor, stretch=1 )

        Log( LogLevel.info, f"[CuraRebuild] Imported '{ inst.name }'\n" )

    # ------------------------------------------------------------------
    # Panel protocol

# ---------------------------------------------------------------------------
# UserLayerPanel
# ---------------------------------------------------------------------------

class UserLayerPanel:
    """Task panel for creating or editing a UserLayer."""

    def __init__(
        self,
        registry: SettingsRegistry,
        doc: FreeCAD.Document,
        existing_layer: UserLayer | None = None,
    ):
        self._registry = registry
        self._doc      = doc
        self._layer    = existing_layer or UserLayer(name="New Layer")
        self._is_new   = existing_layer is None

        self.form = QWidget()
        self._build_ui()

    def _build_ui( self ) -> None:
        layout = QVBoxLayout( self.form )

        name_row = QHBoxLayout()
        name_row.addWidget( QLabel( "Layer name:" ) )
        self._name_edit = QLineEdit( self._layer.name )
        self._name_edit.setPlaceholderText( "Enter layer name…" )
        self._name_edit.textChanged.connect( self._on_name_changed )
        name_row.addWidget( self._name_edit )
        layout.addLayout( name_row )

        # Show all settings — user layers can hold anything
        # Exclude EXPERIMENTAL (object-level mesh overrides)
        from settings.schema import Category as _Cat
        _all_cats = [ c for c in BY_CATEGORY.keys() if c != _Cat.EXPERIMENTAL ]
        self._stack  = _build_stack_for_layer( self._layer, self._registry )
        self._editor = LayerEditorWidget(
            self._layer,
            categories=_all_cats,
            show_all_settings=True,
            stack=self._stack,
        )
        layout.addWidget( self._editor, stretch=1 )

    def _on_name_changed( self, text: str ) -> None:
        """Update layer name live and sync FP Label in the tree."""
        name = text.strip()
        if not name:
            return
        self._layer.name = name
        try:
            import FreeCAD
            from registry_object import get_registry_fp
            reg_fp = get_registry_fp( self._doc )
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                fp_name = reg_fp.Proxy._layer_fps.get( self._layer.id )
                if fp_name:
                    child_fp = self._doc.getObject( fp_name )
                    if child_fp:
                        child_fp.Label = name
        except Exception:
            pass

    def show_as_dialog( self ) -> bool:
        """Open as a standalone QDialog — use when inside another task panel."""
        from PySide2.QtWidgets import QDialog
        dlg = QDialog( self.form.parentWidget() )
        dlg.setWindowTitle( "Settings Layer" )
        dlg.setMinimumSize( 560, 640 )

        layout = QVBoxLayout( dlg )
        layout.addWidget( self.form )

        btns = QHBoxLayout()
        btn_ok     = QPushButton( "Save" )
        btn_cancel = QPushButton( "Cancel" )
        btn_ok.clicked.connect( dlg.accept )
        btn_cancel.clicked.connect( dlg.reject )
        btns.addWidget( btn_ok )
        btns.addWidget( btn_cancel )
        layout.addLayout( btns )

        if dlg.exec_() == QDialog.Accepted:
            name = self._name_edit.text().strip()
            if not name:
                QMessageBox.warning( dlg, "Name required", "Please enter a layer name." )
                return False
            self._layer.name = name
            self._editor.apply()
            if self._is_new:
                from registry_object import get_registry_fp
                reg_fp = get_registry_fp( self._doc )
                if reg_fp and hasattr( reg_fp, "Proxy" ):
                    reg_fp.Proxy.add_layer( reg_fp, self._layer )
                else:
                    self._registry.add_user_layer( self._layer )
            else:
                from registry_object import get_registry_fp
                from layer_fp_object import link_layer_fp
                reg_fp = get_registry_fp( self._doc )
                if reg_fp and hasattr( reg_fp, "Proxy" ):
                    fp_name = reg_fp.Proxy._layer_fps.get( self._layer.id )
                    if fp_name:
                        child_fp = self._doc.getObject( fp_name )
                        if child_fp:
                            link_layer_fp( child_fp, self._layer )
            flush_registry( self._doc )
            from Common import Log, LogLevel
            Log( LogLevel.info, f"[CuraRebuild] User layer '{ name }' saved.\n" )
            return True
        return False

# ---------------------------------------------------------------------------
# RegistryPanel
# ---------------------------------------------------------------------------

class RegistryPanel:
    """
    Overview panel showing all machine and user layers in the registry,
    with buttons to create, edit, and delete each.
    """

    def __init__(self, fp, registry: SettingsRegistry):
        self._fp       = fp
        self._registry = registry
        self._doc      = FreeCAD.ActiveDocument
        self.form      = QWidget()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.form)

        # --- Machine layers ---
        machine_grp = QGroupBox("Machine Layers")
        machine_vbox = QVBoxLayout(machine_grp)

        self._machine_list = QListWidget()
        self._refresh_machine_list()
        self._machine_list.itemDoubleClicked.connect(
            lambda item: self._edit_machine()
        )
        machine_vbox.addWidget(self._machine_list)

        m_btns = QHBoxLayout()
        btn_new_m  = QPushButton("New…")
        btn_edit_m = QPushButton("Edit…")
        btn_del_m  = QPushButton("Delete")
        btn_new_m.clicked.connect(self._new_machine)
        btn_edit_m.clicked.connect(self._edit_machine)
        btn_del_m.clicked.connect(self._delete_machine)
        for b in (btn_new_m, btn_edit_m, btn_del_m):
            m_btns.addWidget(b)
        machine_vbox.addLayout(m_btns)
        layout.addWidget(machine_grp)

        # --- User layers ---
        user_grp  = QGroupBox("User Layers")
        user_vbox = QVBoxLayout(user_grp)

        self._user_list = QListWidget()
        self._refresh_user_list()
        self._user_list.itemDoubleClicked.connect(
            lambda item: self._edit_user()
        )
        user_vbox.addWidget(self._user_list)

        u_btns = QHBoxLayout()
        btn_new_u  = QPushButton("New…")
        btn_edit_u = QPushButton("Edit…")
        btn_del_u  = QPushButton("Delete")
        btn_new_u.clicked.connect(self._new_user)
        btn_edit_u.clicked.connect(self._edit_user)
        btn_del_u.clicked.connect(self._delete_user)
        for b in (btn_new_u, btn_edit_u, btn_del_u):
            u_btns.addWidget(b)
        user_vbox.addLayout(u_btns)
        layout.addWidget(user_grp)

    # ------------------------------------------------------------------

    def _refresh_machine_list(self) -> None:
        self._machine_list.clear()
        for layer in self._registry.all_machine_layers():
            item = QListWidgetItem(
                f"{layer.name}  [{len(layer.keys())} settings]"
            )
            item.setData(QtCore.Qt.UserRole, layer.id)
            self._machine_list.addItem(item)

    def _refresh_user_list(self) -> None:
        self._user_list.clear()
        for layer in self._registry.all_user_layers():
            item = QListWidgetItem(
                f"{layer.name}  [{len(layer.keys())} settings]"
            )
            item.setData(QtCore.Qt.UserRole, layer.id)
            self._user_list.addItem(item)

    def _selected_machine_id(self) -> str | None:
        item = self._machine_list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def _selected_user_id(self) -> str | None:
        item = self._user_list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def _new_machine( self ) -> None:
        panel = MachineLayerPanel( self._registry, self._doc )
        if panel.show_as_dialog():
            self._refresh_machine_list()

    def _edit_machine( self ) -> None:
        lid = self._selected_machine_id()
        if lid is None:
            return
        layer = self._registry.get_machine_layer( lid )
        panel = MachineLayerPanel( self._registry, self._doc, existing_layer=layer )
        if panel.show_as_dialog():
            self._refresh_machine_list()

    def _delete_machine( self ) -> None:
        lid = self._selected_machine_id()
        if lid is None:
            return
        layer = self._registry.get_machine_layer( lid )
        if _confirm( self.form, "Delete Machine",
                     f"Delete machine layer '{ layer.name }'?" ):
            from registry_object import get_registry_fp
            reg_fp = get_registry_fp( self._doc )
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                reg_fp.Proxy.remove_layer( reg_fp, lid )
            else:
                self._registry.remove_machine_layer( lid )
            flush_registry( self._doc )
            self._refresh_machine_list()

    def _new_user( self ) -> None:
        panel = UserLayerPanel( self._registry, self._doc )
        if panel.show_as_dialog():
            self._refresh_user_list()

    def _edit_user( self ) -> None:
        lid = self._selected_user_id()
        if lid is None:
            return
        layer = self._registry.get_user_layer( lid )
        panel = UserLayerPanel( self._registry, self._doc, existing_layer=layer )
        if panel.show_as_dialog():
            self._refresh_user_list()

    def _delete_user( self ) -> None:
        lid = self._selected_user_id()
        if lid is None:
            return
        layer = self._registry.get_user_layer( lid )
        if _confirm( self.form, "Delete Layer",
                     f"Delete user layer '{ layer.name }'?" ):
            from registry_object import get_registry_fp
            reg_fp = get_registry_fp( self._doc )
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                reg_fp.Proxy.remove_layer( reg_fp, lid )
            else:
                self._registry.remove_user_layer( lid )
            flush_registry( self._doc )
            self._refresh_user_list()

    def accept(self) -> bool:
        flush_registry(self._doc)
        FreeCADGui.Control.closeDialog()
        return True

    def reject(self) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return int(QDialogButtonBox.Close)


# ---------------------------------------------------------------------------
# BuildVolumeCreationPanel
# ---------------------------------------------------------------------------

class BuildVolumeCreationPanel:
    """Panel for creating a new BuildVolume and wiring it to a machine layer."""

    def __init__( self, registry: SettingsRegistry, doc: FreeCAD.Document ):
        self._registry = registry
        self._doc      = doc
        self.form      = QWidget()
        self._build_ui()

    def _build_ui( self ) -> None:
        layout = QFormLayout( self.form )

        self._name_edit = QLineEdit( "BuildVolume" )
        layout.addRow( "Name:", self._name_edit )

        self._machine_combo = QComboBox()
        for layer in self._registry.all_machine_layers():
            self._machine_combo.addItem( layer.name, userData=layer.id )
        layout.addRow( "Machine:", self._machine_combo )

        # Dimensions — pre-filled from machine layer if available
        self._width_spin  = QDoubleSpinBox()
        self._depth_spin  = QDoubleSpinBox()
        self._height_spin = QDoubleSpinBox()
        for spin in ( self._width_spin, self._depth_spin, self._height_spin ):
            spin.setRange( 1.0, 10000.0 )
            spin.setSuffix( " mm" )
            spin.setDecimals( 1 )

        self._width_spin.setValue( 220.0 )
        self._depth_spin.setValue( 220.0 )
        self._height_spin.setValue( 220.0 )

        self._machine_combo.currentIndexChanged.connect( self._on_machine_changed )
        self._on_machine_changed()   # populate from first machine

        layout.addRow( "Width (X):",  self._width_spin )
        layout.addRow( "Depth (Y):",  self._depth_spin )
        layout.addRow( "Height (Z):", self._height_spin )

        # G-code output
        gcode_row = QHBoxLayout()
        self._gcode_edit = QLineEdit()
        self._gcode_edit.setPlaceholderText( "Path to output .gcode file…" )
        btn_browse = QPushButton( "…" )
        btn_browse.setFixedWidth( 28 )
        btn_browse.clicked.connect( self._browse_gcode )
        gcode_row.addWidget( self._gcode_edit, stretch=1 )
        gcode_row.addWidget( btn_browse )
        layout.addRow( "G-code output:", gcode_row )

        self._auto_slice_check = QCheckBox( "Auto-slice on change" )
        layout.addRow( "", self._auto_slice_check )

    def _browse_gcode( self ) -> None:
        from PySide2.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            None, "G-code output file", "",
            "G-code (*.gcode *.g);;All files (*)"
        )
        if path:
            self._gcode_edit.setText( path )

    def _on_machine_changed( self ) -> None:
        """Pre-fill dimensions from selected machine layer."""
        lid = self._machine_combo.currentData( QtCore.Qt.UserRole )
        if not lid:
            return
        try:
            layer = self._registry.get_machine_layer( lid )
            w = layer.get( "machine_width" )
            d = layer.get( "machine_depth" )
            h = layer.get( "machine_height" )
            if w: self._width_spin.setValue( float( w ) )
            if d: self._depth_spin.setValue( float( d ) )
            if h: self._height_spin.setValue( float( h ) )
        except Exception:
            pass

    def accept( self ) -> bool:
        from build_volume.build_volume import make_build_volume
        from registry_object import get_registry_fp

        name      = self._name_edit.text().strip() or "BuildVolume"
        lid       = self._machine_combo.currentData( QtCore.Qt.UserRole )
        width     = self._width_spin.value()
        depth     = self._depth_spin.value()
        height    = self._height_spin.value()
        gcode_out = self._gcode_edit.text().strip()
        auto_slice = self._auto_slice_check.isChecked()

        fp = make_build_volume( self._doc, name=name,
                                width=width, depth=depth, height=height )
        if gcode_out:
            fp.GCodeOutputFile = gcode_out
        fp.EnableAutoSlice = auto_slice

        # Link to machine layer FP object
        if lid:
            reg_fp = get_registry_fp( self._doc )
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                ml_fp_name = reg_fp.Proxy._layer_fps.get( lid )
                if ml_fp_name:
                    ml_fp = self._doc.getObject( ml_fp_name )
                    if ml_fp:
                        fp.MachineLayer = ml_fp

        self._doc.recompute()
        FreeCADGui.Control.closeDialog()
        from Common import Log, LogLevel
        Log( LogLevel.info, f"[CuraRebuild] Created BuildVolume '{ name }'.\n" )
        return True

    def reject( self ) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons( self ):
        return int( QDialogButtonBox.Ok | QDialogButtonBox.Cancel )


# ---------------------------------------------------------------------------
# BuildVolumePanel
# ---------------------------------------------------------------------------

class BuildVolumePanel:
    """
    Panel for editing a BuildVolume:
      - Which machine layer it uses
      - Which user layers are in its stack and in what order
        (shows setting count per layer, double-click to edit)
      - Assigned bodies
    """

    def __init__( self, fp, registry: SettingsRegistry ):
        self._fp       = fp
        self._registry = registry
        self._doc      = FreeCAD.ActiveDocument
        self.form      = QWidget()
        self.form.setMinimumWidth( 480 )
        self._build_ui()

    def _build_ui( self ) -> None:
        layout = QVBoxLayout( self.form )

        # --- Machine selector ---
        machine_row = QHBoxLayout()
        machine_row.addWidget( QLabel( "Machine:" ) )
        self._machine_combo = QComboBox()
        for layer in self._registry.all_machine_layers():
            self._machine_combo.addItem( layer.name, userData=layer.id )
        # Select current
        current_ml = getattr( self._fp, "MachineLayer", None )
        current_mid = getattr( current_ml, "LayerId", "" ) if current_ml else ""
        for i in range( self._machine_combo.count() ):
            if self._machine_combo.itemData( i, QtCore.Qt.UserRole ) == current_mid:
                self._machine_combo.setCurrentIndex( i )
                break
        machine_row.addWidget( self._machine_combo, stretch=1 )
        layout.addLayout( machine_row )

        # --- User layer stack ---
        stack_grp  = QGroupBox( "User Layer Stack  (top = highest priority)" )
        stack_vbox = QVBoxLayout( stack_grp )

        self._stack_list = QListWidget()
        self._stack_list.itemDoubleClicked.connect( self._edit_layer )
        self._refresh_stack_list()
        stack_vbox.addWidget( self._stack_list )

        stack_btns = QHBoxLayout()
        btn_add  = QPushButton( "Add Layer…" )
        btn_rem  = QPushButton( "Remove" )
        btn_edit = QPushButton( "Edit Layer…" )
        btn_up   = QPushButton( "▲" )
        btn_down = QPushButton( "▼" )
        btn_add.clicked.connect( self._add_layer )
        btn_rem.clicked.connect( self._remove_layer )
        btn_edit.clicked.connect( self._edit_layer )
        btn_up.clicked.connect( self._move_up )
        btn_down.clicked.connect( self._move_down )
        for b in ( btn_add, btn_rem, btn_edit, btn_up, btn_down ):
            stack_btns.addWidget( b )
        stack_vbox.addLayout( stack_btns )
        layout.addWidget( stack_grp )

        # --- Slicing ---
        slice_grp  = QGroupBox( "Slicing" )
        slice_form = QFormLayout( slice_grp )

        # CuraEngine binary
        cura_row = QHBoxLayout()
        self._cura_edit = QLineEdit(
            getattr( self._fp, "CuraEnginePath", "" )
        )
        self._cura_edit.setPlaceholderText( "Auto-detect if empty…" )
        btn_cura = QPushButton( "…" )
        btn_cura.setFixedWidth( 28 )
        btn_cura.clicked.connect( self._browse_cura )
        cura_row.addWidget( self._cura_edit, stretch=1 )
        cura_row.addWidget( btn_cura )
        slice_form.addRow( "CuraEngine:", cura_row )

        gcode_row = QHBoxLayout()
        self._gcode_edit = QLineEdit(
            getattr( self._fp, "GCodeOutputFile", "" )
        )
        self._gcode_edit.setPlaceholderText( "Path to output .gcode file…" )
        btn_browse = QPushButton( "…" )
        btn_browse.setFixedWidth( 28 )
        btn_browse.clicked.connect( self._browse_gcode )
        gcode_row.addWidget( self._gcode_edit, stretch=1 )
        gcode_row.addWidget( btn_browse )
        slice_form.addRow( "G-code output:", gcode_row )

        self._auto_slice_check = QCheckBox( "Auto-slice on change" )
        self._auto_slice_check.setChecked(
            getattr( self._fp, "EnableAutoSlice", False )
        )
        slice_form.addRow( "", self._auto_slice_check )

        btn_slice_now = QPushButton( "▶ Slice Now" )
        btn_slice_now.clicked.connect( self._slice_now )
        slice_form.addRow( "", btn_slice_now )
        layout.addWidget( slice_grp )

        # --- Assigned bodies ---
        body_grp  = QGroupBox( "Assigned Bodies" )
        body_vbox = QVBoxLayout( body_grp )
        self._body_list = QListWidget()
        self._refresh_body_list()
        body_vbox.addWidget( self._body_list )

        body_btns = QHBoxLayout()
        btn_add_body = QPushButton( "Add Selected…" )
        btn_rem_body = QPushButton( "Remove" )
        btn_add_body.clicked.connect( self._add_body )
        btn_rem_body.clicked.connect( self._remove_body )
        body_btns.addWidget( btn_add_body )
        body_btns.addWidget( btn_rem_body )
        body_vbox.addLayout( body_btns )
        layout.addWidget( body_grp )

    def _layer_label( self, layer ) -> str:
        """Build a list item label showing name and setting count."""
        n = len( layer.keys() )
        return f"{ layer.name }  ({ n } settings)"

    def _refresh_stack_list( self ) -> None:
        self._stack_list.clear()
        for lid in self._fp.Proxy.get_user_layer_ids( self._fp ):
            try:
                layer = self._registry.get_user_layer( lid )
                item  = QListWidgetItem( self._layer_label( layer ) )
                item.setData( QtCore.Qt.UserRole, lid )
                self._stack_list.addItem( item )
            except KeyError:
                pass

    def _refresh_body_list( self ) -> None:
        self._body_list.clear()
        for body in self._fp.Proxy.get_assigned_body_objects( self._fp ):
            if body:
                self._body_list.addItem(
                    QListWidgetItem( getattr( body, "Label", body.Name ) )
                )

    def _current_user_ids( self ) -> list[str]:
        return [
            self._stack_list.item(i).data( QtCore.Qt.UserRole )
            for i in range( self._stack_list.count() )
        ]

    def _add_layer( self ) -> None:
        available = [
            l for l in self._registry.all_user_layers()
            if l.id not in self._current_user_ids()
        ]
        if not available:
            QMessageBox.information( self.form, "No Layers",
                "All user layers are already in this stack." )
            return
        names = [ l.name for l in available ]
        name, ok = QInputDialog.getItem(
            self.form, "Add Layer", "Select layer to add:", names, 0, False )
        if ok and name:
            layer = next( l for l in available if l.name == name )
            item  = QListWidgetItem( self._layer_label( layer ) )
            item.setData( QtCore.Qt.UserRole, layer.id )
            self._stack_list.addItem( item )

    def _remove_layer( self ) -> None:
        row = self._stack_list.currentRow()
        if row >= 0:
            self._stack_list.takeItem( row )

    def _edit_layer( self ) -> None:
        """Open the layer editor for the selected layer."""
        row = self._stack_list.currentRow()
        if row < 0:
            return
        lid = self._stack_list.item( row ).data( QtCore.Qt.UserRole )
        try:
            layer = self._registry.get_user_layer( lid )
            # Build stack context for colour differentiation
            from settings.stack import SettingsStack, MachineLayer as ML
            machines = self._registry.all_machine_layers()
            users    = self._registry.all_user_layers()
            stack    = SettingsStack( machines[0], users ) if machines else None
            panel = UserLayerPanel( self._registry, self._doc,
                                    existing_layer=layer )
            panel.show_as_dialog()
            # Refresh label after edit
            self._stack_list.item( row ).setText( self._layer_label( layer ) )
        except Exception as e:
            QMessageBox.warning( self.form, "Edit failed", str( e ) )

    def _move_up( self ) -> None:
        row = self._stack_list.currentRow()
        if row > 0:
            item = self._stack_list.takeItem( row )
            self._stack_list.insertItem( row - 1, item )
            self._stack_list.setCurrentRow( row - 1 )

    def _move_down( self ) -> None:
        row = self._stack_list.currentRow()
        if row < self._stack_list.count() - 1:
            item = self._stack_list.takeItem( row )
            self._stack_list.insertItem( row + 1, item )
            self._stack_list.setCurrentRow( row + 1 )

    def _browse_cura( self ) -> None:
        from PySide2.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "CuraEngine binary",
            self._cura_edit.text() or "/usr/bin",
            "Executables (*CuraEngine*);;All files (*)"
        )
        if path:
            self._cura_edit.setText( path )

    def _browse_gcode( self ) -> None:
        from PySide2.QtWidgets import QFileDialog
        current = self._gcode_edit.text() or ""
        path, _ = QFileDialog.getSaveFileName(
            None, "G-code output file", current,
            "G-code (*.gcode *.g);;All files (*)"
        )
        if path:
            self._gcode_edit.setText( path )

    def _slice_now( self ) -> None:
        """Save current settings then run slice immediately."""
        self.accept()   # saves all settings first
        # accept() closed the dialog — run slice directly
        try:
            from registry_object import get_registry
            from slicer.engine import slice_build_volume
            from Common import Log, LogLevel
            registry = get_registry( self._fp.Document )
            stack    = self._fp.Proxy.resolve_stack( self._fp, registry )
            result   = slice_build_volume(
                self._fp, stack,
                progress_cb=lambda m: Log( LogLevel.info,
                    f"[Slice] { m }\n" ),
            )
            if result.success and result.gcode_path:
                gcode_out = getattr( self._fp, "GCodeOutputFile", "" )
                if gcode_out:
                    import shutil
                    shutil.copy2( str( result.gcode_path ), gcode_out )
                Log( LogLevel.info,
                    f"[Slice] Done → { result.gcode_path }\n" )
                QMessageBox.information( None, "Slice complete",
                    f"G-code written to:\n{ gcode_out or result.gcode_path }" )
            else:
                QMessageBox.warning( None, "Slice failed",
                    result.error or "Unknown error" )
        except Exception as e:
            import traceback
            QMessageBox.critical( None, "Slice error",
                f"{ e }\n\n{ traceback.format_exc() }" )

    def _add_body( self ) -> None:
        import FreeCADGui
        sel = FreeCADGui.Selection.getSelection( self._doc.Name )
        if not sel:
            QMessageBox.information( self.form, "No selection",
                "Select one or more bodies in the 3D view first." )
            return
        for obj in sel:
            self._fp.Proxy.assign_body( self._fp, obj )
        self._refresh_body_list()
        self._doc.recompute()

    def _remove_body( self ) -> None:
        row = self._body_list.currentRow()
        if row < 0:
            return
        bodies = self._fp.Proxy.get_assigned_body_objects( self._fp )
        if row < len( bodies ):
            self._fp.Proxy.unassign_body( self._fp, bodies[ row ] )
        self._refresh_body_list()
        self._doc.recompute()

    def accept( self ) -> bool:
        from registry_object import get_registry_fp

        # Save slicing settings — properties may not exist on old volumes
        # (added by onDocumentRestored, but guard anyway)
        if hasattr( self._fp, "CuraEnginePath" ):
            self._fp.CuraEnginePath  = self._cura_edit.text().strip()
        if hasattr( self._fp, "GCodeOutputFile" ):
            self._fp.GCodeOutputFile = self._gcode_edit.text().strip()
        if hasattr( self._fp, "EnableAutoSlice" ):
            self._fp.EnableAutoSlice = self._auto_slice_check.isChecked()

        # Link machine layer
        lid    = self._machine_combo.currentData( QtCore.Qt.UserRole )
        reg_fp = get_registry_fp( self._doc )
        if lid and reg_fp and hasattr( reg_fp, "Proxy" ):
            ml_fp_name = reg_fp.Proxy._layer_fps.get( lid )
            if ml_fp_name:
                ml_fp = self._doc.getObject( ml_fp_name )
                if ml_fp:
                    self._fp.MachineLayer = ml_fp

        # Link user layers in order
        # Build a lookup: LayerId → FP object, using registry map + doc scan
        def _find_layer_fp( layer_id: str ):
            # 1. Try registry map
            if reg_fp and hasattr( reg_fp, "Proxy" ):
                fp_name = reg_fp.Proxy._layer_fps.get( layer_id )
                if fp_name:
                    obj = self._doc.getObject( fp_name )
                    if obj:
                        return obj
            # 2. Scan doc for any FP with matching LayerId property
            for obj in self._doc.Objects:
                if getattr( obj, "LayerId", None ) == layer_id:
                    return obj
            return None

        user_fps = []
        for uid in self._current_user_ids():
            fp_obj = _find_layer_fp( uid )
            if fp_obj:
                user_fps.append( fp_obj )
            else:
                from Common import Log, LogLevel
                Log( LogLevel.warning,
                    f"[BuildVolumePanel] Could not find FP for layer "
                    f"id={ uid!r }\n" )
        self._fp.Proxy.set_user_layer_fps( self._fp, user_fps )

        self._doc.recompute()
        FreeCADGui.Control.closeDialog()
        from Common import Log, LogLevel
        Log( LogLevel.info,
            f"[CuraRebuild] BuildVolume '{ self._fp.Name }' stack updated.\n" )
        return True

    def reject( self ) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons( self ):
        return int( QDialogButtonBox.Ok | QDialogButtonBox.Cancel )


class AssignBodiesPanel:
    """Panel for assigning selected bodies to a BuildVolume."""

    def __init__(self, selected_objects: list, build_volumes: list):
        self._selected   = selected_objects
        self._volumes    = build_volumes
        self._doc        = FreeCAD.ActiveDocument
        self.form        = QWidget()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QFormLayout(self.form)

        self._vol_combo = QComboBox()
        for fp in self._volumes:
            self._vol_combo.addItem(fp.Label, userData=fp.Name)
        layout.addRow("Build Volume:", self._vol_combo)

        names = ", ".join(o.Label for o in self._selected)
        layout.addRow("Bodies:", QLabel(names))

    def accept(self) -> bool:
        vol_name = self._vol_combo.currentData()
        fp = self._doc.getObject(vol_name)
        if fp is None or not hasattr(fp, "Proxy"):
            return False

        for obj in self._selected:
            fp.Proxy.assign_body(fp, obj)

        self._doc.recompute()
        FreeCADGui.Control.closeDialog()
        Console.PrintMessage(
            f"[CuraRebuild] Assigned {len(self._selected)} body/bodies "
            f"to '{fp.Label}'.\n"
        )
        return True

    def reject(self) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return int(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)


# ---------------------------------------------------------------------------
# SlicePanel
# ---------------------------------------------------------------------------

class SlicePanel:
    """
    Panel for launching a slice operation.
    Shows all BuildVolumes with assigned bodies; user picks one and slices.
    """

    def __init__(self, doc: FreeCAD.Document, registry: SettingsRegistry):
        self._doc      = doc
        self._registry = registry
        self.form      = QWidget()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.form)

        self._vol_combo = QComboBox()
        for obj in self._doc.Objects:
            if (
                hasattr(obj, "Proxy")
                and getattr(obj.Proxy, "Type", "") == "BuildVolume"
                and obj.Proxy.get_assigned_bodies(obj)
            ):
                label = (
                    f"{obj.Label}  "
                    f"({len(obj.Proxy.get_assigned_bodies(obj))} bodies)"
                )
                self._vol_combo.addItem(label, userData=obj.Name)

        layout.addWidget(QLabel("Build Volume to slice:"))
        layout.addWidget(self._vol_combo)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setPlaceholderText("Slice log will appear here…")
        layout.addWidget(self._log_output)

        btn_row = QHBoxLayout()
        self._slice_btn = QPushButton( "▶ Slice Now" )
        self._slice_btn.clicked.connect( self._run_slice )
        self._open_log_btn = QPushButton( "📄 Open Log File" )
        self._open_log_btn.clicked.connect( self._open_log )
        self._open_log_btn.setVisible( False )
        self._log_path = None
        btn_row.addWidget( self._slice_btn )
        btn_row.addWidget( self._open_log_btn )
        layout.addLayout( btn_row )

    def _run_slice(self) -> None:
        vol_name = self._vol_combo.currentData()
        if not vol_name:
            return

        fp = self._doc.getObject(vol_name)
        if fp is None:
            return

        self._slice_btn.setEnabled(False)
        self._log_output.clear()

        def log(msg: str) -> None:
            self._log_output.append(msg)
            QtWidgets.QApplication.processEvents()

        try:
            stack = fp.Proxy.resolve_stack(fp, self._registry)

            from slicer.engine import slice_build_volume
            result = slice_build_volume(fp, stack, progress_cb=log)

            if result.success:
                log(f"\n✓ Slice complete: {result.gcode_path}")
                gcode_out = getattr( fp, "GCodeOutputFile", "" )
                if gcode_out and result.gcode_path:
                    import shutil
                    shutil.copy2( str( result.gcode_path ), gcode_out )
                    log( f"✓ Copied to: {gcode_out}" )
                # Refresh G-code viewer if active
                if getattr( fp, "ShowGCode", False ):
                    vp = getattr( fp, "ViewObject", None )
                    if vp and hasattr( vp, "Proxy" ) and                             hasattr( vp.Proxy, "update_gcode" ):
                        vp.Proxy._loaded_gcode_mtime = 0
                        vp.Proxy.update_gcode( fp )
            else:
                log(f"\n✗ Slice failed: {result.error}")

            # Always show log path and contents
            if result.log_path and pathlib.Path( str(result.log_path) ).exists():
                log( f"\n--- CuraEngine log: {result.log_path} ---" )
                try:
                    log_text = pathlib.Path( str(result.log_path) ).read_text(
                        encoding="utf-8", errors="replace"
                    )
                    # Show last 200 lines — first part is just the invocation
                    lines = log_text.splitlines()
                    shown = lines[-200:] if len(lines) > 200 else lines
                    log( "\n".join( shown ) )
                except Exception as le:
                    log( f"(could not read log: {le})" )
                self._log_path = result.log_path
                self._open_log_btn.setVisible( True )

        except Exception as e:
            import traceback
            log(f"\n✗ Exception: {e}\n{traceback.format_exc()}")
            Console.PrintError(f"[CuraRebuild] Slice error: {e}\n")
        finally:
            self._slice_btn.setEnabled(True)

    def _open_log( self ) -> None:
        if self._log_path:
            import subprocess, os
            try:
                # Try xdg-open, then fallback to opening in text editor
                subprocess.Popen( ["xdg-open", str( self._log_path )] )
            except Exception:
                os.startfile( str( self._log_path ) )

    def accept(self) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def reject(self) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return int(QDialogButtonBox.Close)
