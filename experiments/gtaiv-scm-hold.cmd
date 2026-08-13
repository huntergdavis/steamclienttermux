@echo off
sc.exe start "Rockstar Service"
echo SCM_START_RC=%ERRORLEVEL%
ping.exe -n 51 127.0.0.1 >nul
sc.exe query "Rockstar Service"
echo SCM_QUERY_RC=%ERRORLEVEL%
sc.exe stop "Rockstar Service"
echo SCM_STOP_RC=%ERRORLEVEL%
ping.exe -n 6 127.0.0.1 >nul
exit /b 0
