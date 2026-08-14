@echo off
sc.exe start "Rockstar Service"
set GTAIV_SERVICE_START_RC=%ERRORLEVEL%
echo GTAIV_SERVICE_START_RC=%GTAIV_SERVICE_START_RC%
rem A stale/already-stopped SCM result must not suppress the signed launcher.
"S:\common\Grand Theft Auto IV\GTAIV\PlayGTAIV.exe"
exit /b %ERRORLEVEL%
