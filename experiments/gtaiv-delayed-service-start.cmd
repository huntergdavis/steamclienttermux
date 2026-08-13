@echo off
set "RGL_LOG=C:\users\steamuser\Documents\Rockstar Games\Launcher\launcher.log"
:wait_patcher
tasklist.exe /FI "IMAGENAME eq LauncherPatcher.exe" | findstr.exe /I /C:"LauncherPatcher.exe" >nul
if errorlevel 1 (
  ping.exe -n 2 127.0.0.1 >nul
  goto wait_patcher
)
:wait_first_launcher_gone
tasklist.exe /FI "IMAGENAME eq Launcher.exe" | findstr.exe /I /C:"Launcher.exe" >nul
if not errorlevel 1 (
  ping.exe -n 2 127.0.0.1 >nul
  goto wait_first_launcher_gone
)
:wait_relaunched_launcher
tasklist.exe /FI "IMAGENAME eq Launcher.exe" | findstr.exe /I /C:"Launcher.exe" >nul
if errorlevel 1 (
  ping.exe -n 2 127.0.0.1 >nul
  goto wait_relaunched_launcher
)
:wait_old_service_marker_gone
findstr.exe /C:"Starting service (attempt 1 / 3)" "%RGL_LOG%" >nul 2>&1
if not errorlevel 1 goto wait_old_service_marker_gone
:wait_new_service_request
findstr.exe /C:"Starting service (attempt 1 / 3)" "%RGL_LOG%" >nul 2>&1
if errorlevel 1 goto wait_new_service_request
sc.exe start "Rockstar Service"
echo DELAYED_SERVICE_START_RC=%ERRORLEVEL%
exit /b 0
