$data='C:\Users\Public\bt\data2'; if(Test-Path $data){Remove-Item $data -Recurse -Force}
function WS { [math]::Round((Get-Process BookTranslator -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum/1MB) }
$p=Start-Side $data; $null=Api PUT /api/key @{api_key='sk-test-0000';provider='api'}
O ("idle sidecar working set MB: " + (WS))
$u=Upload 'C:\Users\Public\bt\files\long300.pdf' 'long300.pdf'; $id=$u.Json.id; O ("uploaded pages_total=" + $u.Json.pages_total)
$null=Api POST "/api/jobs/$id/start" @{auto_glossary=$false;spend_limit=0}
$t0=Get-Date; $peak=0
do { Start-Sleep -Milliseconds 300; $j=(Api GET "/api/jobs/$id").Json; $peak=[math]::Max($peak,(WS)) } until(($j.state -eq 'running' -and $j.done -ge 8) -or @('done','failed') -contains $j.state)
O ("before cancel: state=" + $j.state + " stage=" + $j.stage + " done=" + $j.done + "/" + $j.total + " calls=" + $j.usage.calls)
$c=Api POST "/api/jobs/$id/cancel"; O ("cancel: " + $c.Code)
$j=Wait-Job $id @('paused','done','failed') 60; $calls1=$j.usage.calls
O ("after cancel: state=" + $j.state + " done=" + $j.done + " calls=" + $calls1)
Start-Sleep 3; $j2=(Api GET "/api/jobs/$id").Json; O ("3 s later: state=" + $j2.state + " calls=" + $j2.usage.calls)
$s=Api POST "/api/jobs/$id/start" @{auto_glossary=$false;spend_limit=0}; O ("continue: " + $s.Code)
do { Start-Sleep -Milliseconds 500; $j=(Api GET "/api/jobs/$id").Json; $peak=[math]::Max($peak,(WS)) } until(@('done','failed','paused') -contains $j.state)
O ("T4 finished: state=" + $j.state + " total calls=" + $j.usage.calls + " (300 pages; calls at pause were " + $calls1 + ") total secs=" + [int]((Get-Date)-$t0).TotalSeconds + " peak WS MB=" + $peak + " err=" + $j.error)
# T5: kill the app mid-run, relaunch
$u=Upload 'C:\Users\Public\bt\files\long300.pdf' 'long300.pdf'; $id2=$u.Json.id
$null=Api POST "/api/jobs/$id2/start" @{auto_glossary=$false;spend_limit=0}
do { Start-Sleep -Milliseconds 300; $j=(Api GET "/api/jobs/$id2").Json } until(($j.state -eq 'running' -and $j.done -ge 8) -or @('done','failed') -contains $j.state)
O ("T5 before kill: state=" + $j.state + " done=" + $j.done); Stop-All
$p=Start-Side $data; $list=(Api GET /api/jobs).Json; $mine=$list | Where-Object { $_.id -eq $id2 }
O ("T5 after relaunch: state=" + $mine.state)
$null=Api PUT /api/key @{api_key='sk-test-0000';provider='api'}
$s=Api POST "/api/jobs/$id2/start" @{auto_glossary=$false;spend_limit=0}; O ("T5 continue: " + $s.Code + " " + $(if($s.Code -ne 200){$s.Raw}))
$j=Wait-Job $id2 @('done','failed') 300; O ("T5 finished: state=" + $j.state + " err=" + $j.error)
Stop-All; O ("processes left: " + @(Get-Process BookTranslator -ErrorAction SilentlyContinue).Count)
