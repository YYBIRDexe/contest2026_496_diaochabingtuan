@echo off
setlocal
call "%~dp0run_formation.cmd" %* --motion-mode synchronized
exit /b %errorlevel%
