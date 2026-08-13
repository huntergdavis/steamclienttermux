@echo off
sc.exe start "Rockstar Service"
echo GTAIV_SERVICE_START_RC=%ERRORLEVEL%
if errorlevel 1 exit /b 1
"S:\common\Grand Theft Auto IV\GTAIV\PlayGTAIV.exe"
exit /b %ERRORLEVEL%
