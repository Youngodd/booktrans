@echo off
schtasks /End /TN btrun >nul 2>&1
del /q C:\Users\Public\bt\out.txt 2>nul
schtasks /Create /TN btrun /TR "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Users\Public\bt\run.ps1" /SC ONCE /ST 23:59 /RU vagrant /IT /F > C:\Users\Public\bt\err.txt 2>&1
schtasks /Run /TN btrun >> C:\Users\Public\bt\err.txt 2>&1
