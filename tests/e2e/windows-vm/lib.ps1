$EXE="$env:LOCALAPPDATA\Programs\BookTranslator\BookTranslator.exe"
function Procs { @(Get-CimInstance Win32_Process -Filter "Name='BookTranslator.exe'" | Select ProcessId,ParentProcessId,@{n='Sidecar';e={$_.CommandLine -match '--sidecar'}}) }
function CdpEval($expr,$port=9333){
  $targets = Invoke-RestMethod "http://127.0.0.1:$port/json" -Proxy $null
  $page = $targets | Where-Object type -eq 'page' | Select -First 1
  $ws = New-Object System.Net.WebSockets.ClientWebSocket
  $null = $ws.ConnectAsync([Uri]$page.webSocketDebuggerUrl,[Threading.CancellationToken]::None).Wait()
  $msg = @{id=1;method='Runtime.evaluate';params=@{expression=$expr;awaitPromise=$true;returnByValue=$true}} | ConvertTo-Json -Depth 5 -Compress
  $bytes=[Text.Encoding]::UTF8.GetBytes($msg)
  $null=$ws.SendAsync((New-Object ArraySegment[byte] -ArgumentList (,$bytes)),'Text',$true,[Threading.CancellationToken]::None).Wait()
  $buf=New-Object byte[] 4194304; $sb=''
  do { $seg=New-Object ArraySegment[byte] -ArgumentList (,$buf); $r=$ws.ReceiveAsync($seg,[Threading.CancellationToken]::None).Result; $sb+=[Text.Encoding]::UTF8.GetString($buf,0,$r.Count) } until($r.EndOfMessage)
  $ws.Dispose()
  $o=$sb | ConvertFrom-Json
  if($o.result.exceptionDetails){ return "EXC: " + ($o.result.exceptionDetails | ConvertTo-Json -Depth 4 -Compress) }
  $o.result.result.value
}
function Launch-App($extraEnv=@{}){
  $env:BOOKTRANS_FAKE_BACKEND='1'; $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9333'
  foreach($k in $extraEnv.Keys){ Set-Item "env:$k" $extraEnv[$k] }
  $p=Start-Process $EXE -PassThru
  $end=(Get-Date).AddSeconds(60)
  while((Get-Date) -lt $end){ try { $v=CdpEval "window.pywebview && window.pywebview.api ? 'ready' : ''"; if($v -eq 'ready'){break} } catch {}; Start-Sleep 1 }
  $p
}
function Conn { (CdpEval "window.pywebview.api.connection().then(c=>JSON.stringify(c))") | ConvertFrom-Json }
function Stop-App { Get-Process BookTranslator -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 2 }
