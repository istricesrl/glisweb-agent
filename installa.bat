@echo off
rem installa il GlisWeb Agent: il lavoro lo fa installa.ps1, questo serve a lanciarlo con un doppio clic
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installa.ps1"
echo.
pause
