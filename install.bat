@echo off
cls
echo ============================================
echo   Iotift VS Code Extension Installer
echo ============================================
echo.

:: ── Get the directory this script lives in ──
set IOTIFT_DIR=%~dp0
set IOTIFT_DIR=%IOTIFT_DIR:~0,-1%
echo [1/4] Iotift directory: "%IOTIFT_DIR%"

:: ── Add to PATH if not already there ──
echo [2/4] Checking PATH...
reg query "HKCU\Environment" /v PATH 2>nul | findstr /i /c:"%IOTIFT_DIR%" >nul
if %errorlevel% equ 0 (
    echo         Already on PATH -- skipping.
) else (
    echo         Adding to user PATH...
    for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v PATH 2^>nul`) do set CURRENT_PATH=%%B
    if "%CURRENT_PATH%"=="" (
        setx PATH "%IOTIFT_DIR%" >nul
    ) else (
        setx PATH "%CURRENT_PATH%;%IOTIFT_DIR%" >nul
    )
    echo         Done. Restart any open terminals for the change to take effect.
)

:: ── Install VS Code extension ──
echo [3/4] Installing VS Code extension...
set EXT_DIR=%USERPROFILE%\.vscode\extensions\iotift.iotift-1.0.0

if not exist "%EXT_DIR%" mkdir "%EXT_DIR%"

copy /Y "%IOTIFT_DIR%\vscode-extension\package.json"              "%EXT_DIR%\" >nul 2>&1
copy /Y "%IOTIFT_DIR%\vscode-extension\language-configuration.json" "%EXT_DIR%\" >nul 2>&1
copy /Y "%IOTIFT_DIR%\vscode-extension\README.md"                   "%EXT_DIR%\" >nul 2>&1

if exist "%IOTIFT_DIR%\vscode-extension\out\" (
    if not exist "%EXT_DIR%\out" mkdir "%EXT_DIR%\out"
    copy /Y "%IOTIFT_DIR%\vscode-extension\out\*" "%EXT_DIR%\out\" >nul 2>&1
)

if exist "%IOTIFT_DIR%\vscode-extension\syntaxes\" (
    if not exist "%EXT_DIR%\syntaxes" mkdir "%EXT_DIR%\syntaxes"
    copy /Y "%IOTIFT_DIR%\vscode-extension\syntaxes\*" "%EXT_DIR%\syntaxes\" >nul 2>&1
)

if exist "%IOTIFT_DIR%\vscode-extension\snippets\" (
    if not exist "%EXT_DIR%\snippets" mkdir "%EXT_DIR%\snippets"
    copy /Y "%IOTIFT_DIR%\vscode-extension\snippets\*" "%EXT_DIR%\snippets\" >nul 2>&1
)

echo         Installed to %EXT_DIR%

:: ── Verify ──
echo [4/4] Verifying...
python "%IOTIFT_DIR%\iotift.py" version >nul 2>&1
if %errorlevel% equ 0 (
    echo         iotift CLI: OK
) else (
    echo         iotift CLI: FAILED -- check that Python is on your PATH
)

echo.
echo ============================================
echo   Installation complete.
echo.
echo   What happens now:
echo     1. Restart VS Code (if it is open)
echo     2. Open any .iot file
echo     3. The extension activates automatically
echo     4. LSP server starts with diagnostics,
echo        completion, hover, go-to-definition
echo ============================================
echo.
pause
exit /b 0
