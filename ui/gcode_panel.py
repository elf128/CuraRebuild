#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# gcode_panel.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   G-code viewer control panel.
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

import FreeCAD
import FreeCADGui

from PySide2 import QtCore
from PySide2.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QSlider, QSpinBox, QCheckBox, QComboBox,
    QPushButton, QRadioButton, QDialogButtonBox,
)


class GCodeViewerPanel:
    """Task panel for controlling G-code visualisation on a BuildVolume."""

    def __init__( self, bv_fp: FreeCAD.DocumentObject ):
        self._fp       = bv_fp
        self.form      = QWidget()
        self.form.setWindowTitle( f"G-Code — {bv_fp.Label}" )
        self.form.setMinimumWidth( 340 )
        self._updating = False
        self._build_ui()
        self._fp.ShowGCode = True   # enable rendering immediately
        self._sync_from_fp()

    def _build_ui( self ) -> None:
        layout = QVBoxLayout( self.form )

        # --- Layer control ---
        layer_grp  = QGroupBox( "Layer" )
        layer_form = QFormLayout( layer_grp )

        self._layer_slider = QSlider( QtCore.Qt.Horizontal )
        self._layer_slider.setMinimum( 0 )
        self._layer_slider.setMaximum( 0 )
        self._layer_slider.valueChanged.connect( self._on_layer_changed )

        self._layer_spin = QSpinBox()
        self._layer_spin.setMinimum( 0 )
        self._layer_spin.setMaximum( 0 )
        self._layer_spin.valueChanged.connect( self._on_layer_changed )

        layer_row = QHBoxLayout()
        layer_row.addWidget( self._layer_slider, stretch=1 )
        layer_row.addWidget( self._layer_spin )
        layer_form.addRow( "Layer:", layer_row )

        self._total_label = QLabel( "— not loaded —" )
        self._total_label.setStyleSheet( "color: #888; font-size: 11px;" )
        layer_form.addRow( "", self._total_label )

        mode_row = QHBoxLayout()
        self._upto_radio = QRadioButton( "Cumulative" )
        self._only_radio = QRadioButton( "Single layer" )
        self._upto_radio.setChecked( True )
        self._upto_radio.toggled.connect( self._on_mode_changed )
        mode_row.addWidget( self._upto_radio )
        mode_row.addWidget( self._only_radio )
        mode_row.addStretch()
        layer_form.addRow( "Mode:", mode_row )
        layout.addWidget( layer_grp )

        # --- Colour mode ---
        colour_grp  = QGroupBox( "Colour Mode" )
        colour_form = QFormLayout( colour_grp )
        self._colour_combo = QComboBox()
        self._colour_combo.addItems( ["Feature", "Speed", "Extruder"] )
        self._colour_combo.currentTextChanged.connect( self._on_colour_changed )
        colour_form.addRow( "Colour by:", self._colour_combo )
        layout.addWidget( colour_grp )

        # --- Feature visibility ---
        feat_grp    = QGroupBox( "Feature Visibility" )
        feat_layout = QVBoxLayout( feat_grp )

        self._feat_checks: dict[str, QCheckBox] = {}
        features = [
            ( "WallOuter",  "Outer Wall",    "#FF9900" ),
            ( "WallInner",  "Inner Wall",    "#66AAFF" ),
            ( "Fill",       "Infill",        "#FF6666" ),
            ( "Skin",       "Top/Bottom",    "#FFCC00" ),
            ( "Support",    "Support",       "#66DD66" ),
            ( "Skirt",      "Skirt/Brim",    "#BB88FF" ),
            ( "PrimeTower", "Prime Tower",   "#888888" ),
        ]
        for suffix, label, colour in features:
            row = QHBoxLayout()
            swatch = QLabel( "■" )
            swatch.setStyleSheet( f"color: {colour}; font-size: 14px;" )
            cb = QCheckBox( label )
            cb.setChecked( True )
            cb.stateChanged.connect(
                lambda state, s=suffix: self._on_feat_changed( s, bool(state) )
            )
            row.addWidget( swatch )
            row.addWidget( cb, stretch=1 )
            feat_layout.addLayout( row )
            self._feat_checks[ suffix ] = cb

        self._travel_check = QCheckBox( "Travel moves" )
        self._travel_check.stateChanged.connect( self._on_travel_changed )
        feat_layout.addWidget( self._travel_check )
        layout.addWidget( feat_grp )

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_reload = QPushButton( "↺ Reload" )
        btn_reload.clicked.connect( self._on_reload )
        btn_row.addWidget( btn_reload )
        layout.addLayout( btn_row )
        layout.addStretch()

    def _get_n_layers( self ) -> int:
        vp = getattr( self._fp, "ViewObject", None )
        if vp and hasattr( vp, "Proxy" ):
            r = getattr( vp.Proxy, "_gcode_renderer", None )
            if r and r._gcode:
                return r._gcode.layer_count()
        return 0

    def _sync_from_fp( self ) -> None:
        self._updating = True
        try:
            n = self._get_n_layers()
            self._layer_slider.setMaximum( max(0, n-1) )
            self._layer_spin.setMaximum( max(0, n-1) )
            self._total_label.setText(
                f"{n} layers" if n else "— not loaded —" )

            cur = getattr( self._fp, "GCodeLayer", 0 )
            self._layer_slider.setValue( cur )
            self._layer_spin.setValue( cur )

            self._upto_radio.setChecked(
                getattr( self._fp, "GCodeShowUpTo", True ) )
            self._only_radio.setChecked(
                not getattr( self._fp, "GCodeShowUpTo", True ) )

            idx = self._colour_combo.findText(
                getattr( self._fp, "GCodeColourMode", "Feature" ) )
            if idx >= 0:
                self._colour_combo.setCurrentIndex( idx )

            for suffix, cb in self._feat_checks.items():
                cb.setChecked( getattr( self._fp, f"GCodeShow{suffix}", True ) )

            self._travel_check.setChecked(
                getattr( self._fp, "GCodeShowTravel", False ) )
        finally:
            self._updating = False

    def _on_layer_changed( self, value: int ) -> None:
        if self._updating: return
        self._updating = True
        self._layer_slider.setValue( value )
        self._layer_spin.setValue( value )
        self._updating = False
        self._fp.GCodeLayer = value

    def _on_mode_changed( self, *_ ) -> None:
        if self._updating: return
        self._fp.GCodeShowUpTo = self._upto_radio.isChecked()

    def _on_colour_changed( self, text: str ) -> None:
        if self._updating: return
        self._fp.GCodeColourMode = text

    def _on_feat_changed( self, suffix: str, checked: bool ) -> None:
        if self._updating: return
        setattr( self._fp, f"GCodeShow{suffix}", checked )

    def _on_travel_changed( self, state: int ) -> None:
        if self._updating: return
        self._fp.GCodeShowTravel = bool( state )

    def _on_reload( self ) -> None:
        vp = getattr( self._fp, "ViewObject", None )
        if vp and hasattr( vp, "Proxy" ):
            vp.Proxy._loaded_gcode_path = None   # force re-parse
        self._fp.ShowGCode = True   # trigger updateData
        self._sync_from_fp()

    def reject( self ) -> bool:
        self._fp.ShowGCode = False   # hide on close
        FreeCADGui.Control.closeDialog()
        return True

    def accept( self ) -> bool:
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons( self ):
        return int( QDialogButtonBox.Close )
