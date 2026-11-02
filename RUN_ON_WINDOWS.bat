@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo TradeAssist AI - Local Research App
echo ========================================
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  set "PYTHON=py"
) else (
  set "PYTHON=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto :failed
)
call ".venv\Scripts\activate.bat"
echo Installing or confirming packages (needs internet the first time)...
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed
echo Launching the dashboard. Open http://localhost:8501 if browser does not open.
python -m streamlit run app.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo Setup or launch failed. Check Python installation and network, then retry.
pause
exit /b 1
