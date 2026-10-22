@echo off
rem Author:  Corey Preston
rem Company: Fischer Connectors, Inc
rem Date:    October 2026
setlocal EnableExtensions
rem PDF Sniffer launcher. Double-click, or drag one or more folders onto this file.
pushd "%~dp0"
title PDF Sniffer

if not exist "runtime\.installed" call :install
if not exist "runtime\.installed" goto :failed

"runtime\python\python.exe" -m pdf_sniffer %*
set RC=%ERRORLEVEL%
goto :done

:install
echo.
echo First-time setup: installing the bundled Python and libraries into this folder ...
if exist "runtime" rmdir /s /q "runtime"
mkdir "runtime\python"
xcopy "vendor\python" "runtime\python\" /E /I /Q /Y >nul
if not exist "runtime\python\python.exe" (
  echo Could not copy the bundled Python from the vendor folder. Was the download complete?
  goto :eof
)
"runtime\python\python.exe" "tools\bootstrap.py"
goto :eof

:failed
echo.
echo Setup did not finish. See the message above, then run this file again.
set RC=1

:done
echo.
pause
popd
exit /b %RC%
