@echo off
setlocal enabledelayedexpansion
title LoL Skin Exporter
cd /d "%~dp0"

REM This launcher tries to use Python if it's already installed.
REM If not found, it downloads a small "embeddable" portable Python
REM (official python.org build, ~10MB) into a local folder, just once,
REM so the user never has to install anything system-wide.

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0export_skins.py"
    goto :end
)

if exist "%~dp0python_embed\python.exe" (
    "%~dp0python_embed\python.exe" "%~dp0export_skins.py"
    goto :end
)

echo Python wasn't found on this PC. Downloading a small portable copy...
echo ^(one-time only, about 10MB^)
echo.

powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip' -OutFile '%~dp0python_embed.zip'"
if not exist "%~dp0python_embed.zip" (
    echo.
    echo Download failed. Please check your internet connection and try again,
    echo or ask whoever sent you this tool for the .exe version instead.
    pause
    goto :end
)

powershell -Command "Expand-Archive -Path '%~dp0python_embed.zip' -DestinationPath '%~dp0python_embed' -Force"
del "%~dp0python_embed.zip"

"%~dp0python_embed\python.exe" "%~dp0export_skins.py"

:end
endlocal
