$dir="$env:LOCALAPPDATA\Programs\BookTranslator"
$d="$env:APPDATA\BookTranslator"
O ("before: app dir=" + (Test-Path $dir) + " data dir=" + (Test-Path $d) + " jobs=" + @(Get-ChildItem "$d\jobs" -ErrorAction SilentlyContinue).Count)
$p=Start-Process "$dir\unins000.exe" -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -PassThru -Wait
O ("uninstaller exit: " + $p.ExitCode)
Start-Sleep 3
O ("I5 app dir exists after: " + (Test-Path $dir))
O ("I5 data dir kept: " + (Test-Path $d) + "; jobs=" + @(Get-ChildItem "$d\jobs" -ErrorAction SilentlyContinue).Count)
O ("I5 credential kept: " + ((cmdkey /list | Select-String 'BookTranslator') -join ' '))
O ("start menu shortcut gone: " + -not (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Book Translator.lnk"))
