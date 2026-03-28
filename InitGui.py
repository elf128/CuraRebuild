#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# InitGui.py
#
#   Created on:    Mar 15, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   UI and command registration for the CuraRebuild workbench.
#   Also handle reload on workbench activation for development convenience.
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


# import os
# import sys
from Common import Log, LogLevel
import Commands
            

def Reload( mod ):
    from importlib import reload
    print( "Reload module" )
    reload( mod )
    mod.Reload()


# Patch Python's json encoder so FreeCAD's PropertyPythonObject::toString()
# doesn't spam the log with TypeError for every proxy object on document save.
def _patch_json_encoder():
    import json as _json
    _orig = _json.JSONEncoder.default
    def _safe_default( self, obj ):
        gs = getattr( obj, "__getstate__", None )
        if gs is not None:
            try:
                state = gs()
                if isinstance( state, ( str, int, float, bool, list, dict, type(None) ) ):
                    return state
            except Exception:
                pass
        return f"<{obj.__class__.__name__}>"
    _json.JSONEncoder.default = _safe_default
_patch_json_encoder()


class CuraRebuildWB( Workbench ):  # noqa: F821
    from Common import getIconPath

    MenuText = "CuraRebuild"
    ToolTip  = "CuraRebuild — FDM slicer for FreeCAD (CuraEngine)"
    Icon     = getIconPath( "3DPrint.svg" )

    _MACHINE_CMDS = [
        "CuraRebuild_CreateMachineLayer",
        "CuraRebuild_CreateUserLayer",
    ]

    _VOLUME_CMDS = [
        "CuraRebuild_CreateBuildVolume",
        "CuraRebuild_EditBuildVolume",
        "CuraRebuild_AssignBodies",
    ]

    _SLICE_CMDS = [
        "CuraRebuild_Slice",
    ]

    def GetClassName( self ):
        return "Gui::PythonWorkbench"

    def Initialize( self ):
        import traceback
        from Common import Log, LogLevel

        Log( LogLevel.info, "[CuraRebuild] Initialize() called\n" )

        # Register icons directory for toolbar button icons
        """
        try:
            import CuraRebuild as _pkg
            _icons = os.path.join( os.path.dirname( os.path.abspath( _pkg.__file__ ) ), "icons" )
            if os.path.isdir( _icons ):
                FreeCAD.addResourcePath( _icons )  # noqa: F821
                Log( LogLevel.info, f"[CuraRebuild] Registered icons dir: {_icons}\n" )
        except Exception as e:
            Log( LogLevel.info, f"[CuraRebuild] Icons dir warning: {e}\n" )
        """
        
        try:
            Log( LogLevel.info, "[CuraRebuild] Importing Commands...\n" )
            import Commands
            
            Log( LogLevel.info, "[CuraRebuild] Calling register_all()...\n" )
            Commands.register_all()
            Log( LogLevel.info, "[CuraRebuild] register_all() done\n" )
        except Exception as e:
            Log( LogLevel.info, f"[CuraRebuild] Failed to register commands: {e}\n" )
            Log( LogLevel.info, traceback.format_exc() + "\n" )
            return

        try:
            self.appendToolbar( "CuraRebuild", self._VOLUME_CMDS + self._SLICE_CMDS )
            self.appendToolbar( "CuraRebuild Settings", self._MACHINE_CMDS )
            self.appendMenu( "CuraRebuild", [
                "CuraRebuild_CreateBuildVolume",
                "CuraRebuild_EditBuildVolume",
                "CuraRebuild_AssignBodies",
                "Separator",
                "CuraRebuild_Slice",
                "Separator",
                "CuraRebuild_CreateMachineLayer",
                "CuraRebuild_CreateUserLayer",
            ] )
            Log( LogLevel.info, "[CuraRebuild] Toolbars and menu appended\n" )
        except Exception as e:
            Log( LogLevel.info, f"[CuraRebuild] Failed to append toolbar/menu: {e}\n" )
            Log( LogLevel.info, traceback.format_exc() + "\n" )
            return

        Log( LogLevel.info, "[CuraRebuild] Initialised successfully.\n" )

    def Activated( self ):
        from Common import Log, LogLevel

        Log( LogLevel.info, "[CuraRebuild] Activated.\n" )  # noqa: F821
        self._reload_( self._mod_ )
        return

    def Deactivated( self ):
        from Common import Log, LogLevel

        Log( LogLevel.info, "[CuraRebuild] Deactivated.\n" )  # noqa: F821

wb = CuraRebuildWB()
wb._reload_ = Reload
wb._mod_    = Commands

Gui.addWorkbench( wb )
