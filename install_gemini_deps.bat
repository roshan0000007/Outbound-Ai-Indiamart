@echo off
REM Quick installation script for Gemini Live dependencies (Windows)

setlocal enabledelayedexpansion

echo ==================================
echo INSTALLING GEMINI LIVE DEPENDENCIES
echo ==================================
echo.

REM Check if in virtual environment
if "%VIRTUAL_ENV%"=="" (
    echo WARNING: Virtual environment not activated
    echo Please activate: venv\Scripts\activate.bat
    exit /b 1
)

echo OK Using virtual environment: %VIRTUAL_ENV%
echo.

echo [1] Upgrading pip...
python -m pip install --upgrade pip setuptools wheel -q

echo [2] Installing google-generativeai...
pip install "google-generativeai>=0.4.0" -q

echo [3] Installing websockets...
pip install "websockets>=11.0" -q

echo.
echo [4] Verifying installation...
python -c "import google.generativeai; import websockets; print('OK All packages installed successfully')"

echo.
echo ==================================
echo OK INSTALLATION COMPLETE
echo ==================================
echo.
echo Next steps:
echo 1. cd app directory
echo 2. python main.py
echo.
echo You should see:
echo [Gemini Live] OK Client initialized successfully
echo.

pause
