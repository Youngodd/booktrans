$exe="$env:LOCALAPPDATA\Programs\BookTranslator\BookTranslator.exe"
$env:BOOKTRANS_FAKE_BACKEND='1'; $env:BOOKTRANS_DATA='C:\Users\Public\bt\data4'
$p=Start-Process $exe -PassThru; Start-Sleep 60
$ps=Get-Process BookTranslator,msedgewebview2 -ErrorAction SilentlyContinue
O ($ps | Group-Object ProcessName | ForEach-Object { $_.Name + ": n=" + $_.Count + " WS MB=" + [math]::Round(($_.Group | Measure-Object WorkingSet64 -Sum).Sum/1MB) })
O ("BookTranslator only: " + [math]::Round((Get-Process BookTranslator | Measure-Object WorkingSet64 -Sum).Sum/1MB) + " MB")
Get-Process BookTranslator | Stop-Process -Force; Start-Sleep 3
Get-Process msedgewebview2 -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*EdgeWebView*' } | Out-Null
O ("left after close: " + @(Get-Process BookTranslator -ErrorAction SilentlyContinue).Count)
