@echo off
REM Put Blender in PATH, or replace blender with its full executable path.
blender -b --factory-startup --python "%~dp0generate_rfc.py" -- --output "%~dp0RFC_BUILD" --mode full --export
pause
