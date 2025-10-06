@echo off
REM ============================================================
REM Lexington Food Inspection Data Pipeline
REM
REM This script runs the complete data pipeline to download and
REM process food inspection data from LFCHD.
REM
REM Suggested Usage:
REM   - Run manually: Double-click this file
REM   - Run daily via Task Scheduler to auto-check for updates
REM
REM The script will:
REM   1. Check if Python is installed
REM   2. Download latest PDF (skips if unchanged via MD5)
REM   3. Process data and generate final CSV
REM ============================================================

echo.
echo ============================================================
echo LEXINGTON FOOD INSPECTION DATA PIPELINE
echo ============================================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo.
    echo Please install Python from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

echo [INFO] Python found:
python --version
echo.

REM Check if required Python packages are installed
echo [INFO] Checking dependencies...
python -c "import pandas, camelot, pdfplumber" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Some Python packages may be missing
    echo [INFO] Attempting to install required packages...
    python -m pip install pandas camelot-py pdfplumber
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        echo Please run: pip install pandas camelot-py pdfplumber
        pause
        exit /b 1
    )
)
echo [SUCCESS] Dependencies OK
echo.

REM Run the pipeline
echo [INFO] Starting pipeline...
echo.
python run_pipeline.py

if errorlevel 1 (
    echo.
    echo [ERROR] Pipeline failed!
    echo Check the error messages above for details.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo PIPELINE COMPLETED SUCCESSFULLY
echo ============================================================
echo.
echo Final output: joined_scores_violations.csv
echo.
echo To schedule this to run automatically:
echo 1. Open Task Scheduler
echo 2. Create Basic Task
echo 3. Set trigger (Daily recommended)
echo 4. Action: Start a program
echo 5. Program: %~dp0run_pipeline.bat
echo.
pause
