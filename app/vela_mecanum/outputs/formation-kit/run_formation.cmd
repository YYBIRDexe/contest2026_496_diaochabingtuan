@echo off
setlocal
set "ROOT=%~dp0..\.."
set "PY=%ROOT%\work\.venv\Scripts\python.exe"
if not exist "%PY%" (
  python -m venv "%ROOT%\work\.venv" || exit /b 1
  "%PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements-control.txt" || exit /b 1
)
"%PY%" "%~dp0run_autonomous_formation.py" %*
exit /b %errorlevel%
