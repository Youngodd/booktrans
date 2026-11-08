$exe="$env:LOCALAPPDATA\Programs\BookTranslator\BookTranslator.exe"
$env:BOOKTRANS_FAKE_BACKEND='1'; $env:BOOKTRANS_DATA='C:\Users\Public\bt\data'
function Procs { Get-CimInstance Win32_Process -Filter "Name='BookTranslator.exe'" | Select ProcessId,ParentProcessId,@{n='Sidecar';e={$_.CommandLine -match '--sidecar'}} }
# S1: window within 15 s
$t0=Get-Date; $p=Start-Process $exe -PassThru; $title=''
while(((Get-Date)-$t0).TotalSeconds -lt 40){ $m=Get-Process -Id $p.Id -ErrorAction SilentlyContinue; if($m -and $m.MainWindowTitle){$title=$m.MainWindowTitle;break}; Start-Sleep -Milliseconds 250 }
O ("S1 title='" + $title + "' after " + [math]::Round(((Get-Date)-$t0).TotalSeconds,1) + " s")
Start-Sleep 5
O ("processes: "); O (Procs | Format-Table | Out-String)
O ("console windows: " + ((Get-Process | Where-Object { $_.MainWindowTitle -and $_.ProcessName -match 'cmd|conhost|powershell' }) | Select -Expand ProcessName))
# screenshot of the VM screen
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object Drawing.Bitmap $b.Width,$b.Height
[Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location,[Drawing.Point]::Empty,$b.Size); $bmp.Save('C:\Users\Public\bt\s1.png'); O ("screenshot " + $b.Width + "x" + $b.Height)
# S2: close the window
$m=Get-Process -Id $p.Id; $null=$m.CloseMainWindow(); Start-Sleep 6
O ("S2 after close, BookTranslator processes left: " + @(Get-Process BookTranslator -ErrorAction SilentlyContinue).Count)
Get-Process BookTranslator -ErrorAction SilentlyContinue | Stop-Process -Force
# S3: kill main, sidecar must go
Start-Sleep 2; $p=Start-Process $exe -PassThru; Start-Sleep 12
$all=Procs; O "before kill:"; O ($all | Format-Table | Out-String)
$main=($all | Where-Object { -not $_.Sidecar } | Select -First 1).ProcessId
Stop-Process -Id $main -Force; Start-Sleep 5
O ("S3 after killing main " + $main + ", remaining:"); O (Procs | Format-Table | Out-String)
Get-Process BookTranslator -ErrorAction SilentlyContinue | Stop-Process -Force
