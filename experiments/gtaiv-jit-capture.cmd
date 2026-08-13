@echo off
set "CAPTURE_LOG=C:\gtaiv-jit-capture.log"
echo === GTAIV JIT CAPTURE INVOKED %DATE% %TIME% ===>"%CAPTURE_LOG%"
C:\windows\system32\winedbg.exe --file C:\gtaiv-jit-capture.wdb %1 %2 >>"%CAPTURE_LOG%" 2>&1
