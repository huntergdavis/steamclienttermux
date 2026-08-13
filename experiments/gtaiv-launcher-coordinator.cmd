@echo off
"C:\Program Files\Rockstar Games\Launcher\Launcher.exe"
echo COORD_LAUNCHER_RC=%ERRORLEVEL%
ping.exe -n 121 127.0.0.1 >nul
sc.exe query "Rockstar Service"
echo COORD_SERVICE_QUERY_RC=%ERRORLEVEL%
exit /b 0
