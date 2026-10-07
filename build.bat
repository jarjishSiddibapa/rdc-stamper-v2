@echo off
setlocal
call "%~dp0build-installer.bat" %*
exit /b %errorlevel%
