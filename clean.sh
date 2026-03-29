#!/bin/sh
#

find . -name *.pyc -execdir rm "{}" \;
find . -name __pycache__ -execdir rmdir "{}" \;
