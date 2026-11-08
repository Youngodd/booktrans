O ("user: " + (whoami))
$inst='C:\Users\Public\bt\BookTranslator-Setup-0.1.19.exe'
$t0=Get-Date
$p = Start-Process $inst -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG=C:\Users\Public\bt\inst.log' -PassThru -Wait
O ("installer exit code: " + $p.ExitCode + " in " + [int]((Get-Date)-$t0).TotalSeconds + " s")
$dir="$env:LOCALAPPDATA\Programs\BookTranslator"
O ("install dir exists: " + (Test-Path $dir) + "  " + $dir)
O (Get-ChildItem $dir -ErrorAction SilentlyContinue | Select -First 12 Name,Length | Format-Table | Out-String)
O ("exe: " + (Test-Path "$dir\BookTranslator.exe"))
$lnk = Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | Where Name -match 'Book'
O ("start menu: " + ($lnk | Select -Expand FullName))
O (Get-Content C:\Users\Public\bt\inst.log -ErrorAction SilentlyContinue | Select -Last 6)
