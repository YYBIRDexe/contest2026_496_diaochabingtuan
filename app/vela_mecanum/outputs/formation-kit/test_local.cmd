@echo off
setlocal
set "ROOT=%~dp0..\.."
set "PY=%ROOT%\work\.venv\Scripts\python.exe"
if not exist "%PY%" (
  python -m venv "%ROOT%\work\.venv" || exit /b 1
  "%PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements-control.txt" || exit /b 1
)
"%PY%" -m py_compile "%~dp0run_autonomous_formation.py" "%~dp0run_formation_lap.py" "%~dp0build_bundle.py" "%~dp0verify_bundle.py" || exit /b 1
for %%F in ("%~dp0payload\planner\*.py") do "%PY%" -m py_compile "%%~fF" || exit /b 1
for %%F in ("%~dp0payload\baseline_robot1\*.py") do "%PY%" -m py_compile "%%~fF" || exit /b 1
"%PY%" "%~dp0payload\planner\test_reconfiguration.py" || exit /b 1
call "%~dp0run_formation.cmd" square --spacing 0.5 --simulate || exit /b 1
"%PY%" "%~dp0payload\planner\simulate_formation_lap.py" --formation triangle --spacing 0.5 --speed 0.875 || exit /b 1
"%PY%" "%~dp0build_bundle.py" || exit /b 1
"%PY%" "%~dp0verify_bundle.py" || exit /b 1
echo LOCAL_TESTS_OK
