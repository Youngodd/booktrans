$data='C:\Users\Public\bt\data3'; if(Test-Path $data){Remove-Item $data -Recurse -Force}
$p=Start-Side $data; $null=Api PUT /api/key @{api_key='sk-test-0000';provider='api'}
$u=Upload 'C:\Users\Public\bt\files\long300.pdf' 'long300.pdf'; $id=$u.Json.id
$null=Api POST "/api/jobs/$id/start" @{auto_glossary=$false;spend_limit=0}
do { Start-Sleep -Milliseconds 150; $j=(Api GET "/api/jobs/$id").Json } until(($j.stage -eq 'translate' -and $j.done -ge 40) -or @('done','failed') -contains $j.state)
O ("before cancel: state=" + $j.state + " stage=" + $j.stage + " done=" + $j.done + "/" + $j.total + " calls=" + $j.usage.calls)
$c=Api POST "/api/jobs/$id/cancel"; O ("cancel: " + $c.Code)
$j=Wait-Job $id @('paused','done','failed') 60; $c1=$j.usage.calls
O ("after cancel: state=" + $j.state + " done=" + $j.done + "/" + $j.total + " calls=" + $c1 + " stage=" + $j.stage)
$s=Api POST "/api/jobs/$id/start" @{auto_glossary=$false;spend_limit=0}; O ("continue: " + $s.Code)
$j=Wait-Job $id @('done','failed','paused') 300
O ("finished: state=" + $j.state + " total calls=" + $j.usage.calls + " (pages=300, calls at pause=" + $c1 + ", redo=" + ($j.usage.calls - 300) + ")")
Stop-All
