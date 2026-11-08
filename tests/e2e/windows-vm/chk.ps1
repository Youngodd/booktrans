O ("procs: " + (Procs | Measure).Count)
Stop-App
O ("cmdkey: " + ((cmdkey /list | Select-String -Context 0,3 'BookTranslator') | Out-String))
$d="$env:APPDATA\BookTranslator"
O (Get-ChildItem $d -Force | Select Name,LastWriteTime,Length | Format-Table | Out-String)
O (Get-ChildItem "$d\jobs" -ErrorAction SilentlyContinue | Select Name,LastWriteTime | Format-Table | Out-String)
O ("prefs: " + (Get-Content "$d\prefs.json" -ErrorAction SilentlyContinue))
O ("log tail: " + ((Get-Content "$d\sidecar.log" -Tail 4 -ErrorAction SilentlyContinue) -join ' / '))
