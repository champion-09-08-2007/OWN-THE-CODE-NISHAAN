@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv || (echo Python 3.10+ is required. & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
echo Installing requirements...
python -m pip install -q --disable-pip-version-check -r requirements.txt
echo.
echo Nishaan is starting. Open http://localhost:8000
start "" http://localhost:8000
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
