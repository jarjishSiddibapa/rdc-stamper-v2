@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\build-installer.ps1" %*
if errorlevel 1 exit /b %errorlevel%
