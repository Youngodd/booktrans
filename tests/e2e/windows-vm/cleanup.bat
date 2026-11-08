@echo off
schtasks /End /TN btrun >nul 2>&1
schtasks /Delete /TN btrun /F > C:\Users\Public\cleanup.txt 2>&1
taskkill /F /IM BookTranslator.exe >> C:\Users\Public\cleanup.txt 2>&1
rmdir /s /q C:\Users\Public\bt >> C:\Users\Public\cleanup.txt 2>&1
for /d %%D in (C:\*) do if exist "%%D\*" echo %%D > nul
powershell -NoProfile -Command "Remove-Item -LiteralPath ('C:\' + [string]::new([char[]](0x6D4B,0x8BD5))) -Recurse -Force -ErrorAction SilentlyContinue; Test-Path ('C:\' + [string]::new([char[]](0x6D4B,0x8BD5))) | Out-File -Encoding ascii C:\Users\Public\cleanup2.txt; Test-Path C:\Users\Public\bt | Out-File -Append -Encoding ascii C:\Users\Public\cleanup2.txt; (schtasks /Query /TN btrun 2>&1) | Out-File -Append -Encoding ascii C:\Users\Public\cleanup2.txt"
