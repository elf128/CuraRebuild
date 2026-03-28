#
# CuraRebuild — FreeCAD workbench for managing layered settings stacks
#
# Common.py
#
#   Created on:    Mar 16, 2026
#       Author:    Vlad A. < elf128@gmail.com >
#       Coauthors: Claude AI, Sonnet 4.6
#
#   Common utilities for the CuraRebuild workbench, 
#   including path management and logging.
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



import os

_dir_    = os.path.dirname( __file__ )
iconPath = os.path.join( _dir_, 'icons' )
uiPath   = os.path.join( _dir_, 'ui' )

def getIconPath( filename ):
    return os.path.join( iconPath, filename )

def getUiPath( filename ):
    return os.path.join( uiPath, filename )

def getModRoot():
    return _dir_

class bcolors:
    HEADER    = '\033[95m'
    OKBLUE    = '\033[94m'
    OKCYAN    = '\033[96m'
    OKGREEN   = '\033[92m'
    WARNING   = '\033[93m'
    FAIL      = '\033[91m'
    BOLD      = '\033[1m'
    UNDERLINE = '\033[4m'
    ENDC      = '\033[0m'


class LogLevel:
    error   = 0
    warning = 1
    info    = 2
    debug   = 3
    
def Log( *args ):
    if len( args ) > 0:
        level = args[ 0 ]
        if level == 0:
            color = bcolors.FAIL
        elif level == 1:
            color = bcolors.WARNING
        elif level == 2:
            color = bcolors.OKCYAN
        else:
            color = bcolors.ENDC
        
        print( color, *args[1:], bcolors.ENDC )
    else:
        print( *args )
    
print(" Common is in %s " % _dir_ )
