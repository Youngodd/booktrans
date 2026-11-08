$EXE="$env:LOCALAPPDATA\Programs\BookTranslator\BookTranslator.exe"
$script:BASE=$null; $script:TOK=$null
function Start-Side($data){
  $env:BOOKTRANS_FAKE_BACKEND='1'; $env:BOOKTRANS_DATA=$data; $env:PYTHONIOENCODING='utf-8'
  $null=New-Item -ItemType Directory -Force $data
  $ready="C:\Users\Public\bt\ready-" + [guid]::NewGuid().ToString('N')
  $p=Start-Process $EXE -ArgumentList '--sidecar','--ready-file',$ready -PassThru -WindowStyle Hidden
  $end=(Get-Date).AddSeconds(90); while(-not (Test-Path $ready) -and (Get-Date) -lt $end){ Start-Sleep -Milliseconds 300 }
  $t=Get-Content $ready -Raw; $m=[regex]::Match($t,'port=(\d+) token=(\S+)')
  $script:BASE="http://127.0.0.1:" + $m.Groups[1].Value; $script:TOK=$m.Groups[2].Value
  for($i=0;$i -lt 100;$i++){ $r=(curl.exe -s --noproxy "*" "$script:BASE/healthz"); if($r){break}; Start-Sleep -Milliseconds 300 }
  $p
}
function Api($method,$path,$body=$null){
  $a=@('-s','--noproxy','*','-X',$method,'-H',"X-Booktrans-Token: $script:TOK",'-w','\n%{http_code}')
  if($body -ne $null){ $f="C:\Users\Public\bt\body.json"; [IO.File]::WriteAllText($f,($body|ConvertTo-Json -Compress),(New-Object Text.UTF8Encoding $false)); $a+=@('-H','Content-Type: application/json','--data-binary',"@$f") }
  $out=& curl.exe @a "$script:BASE$path"; $code=$out[-1]; $txt=($out[0..($out.Count-2)] -join "`n")
  [pscustomobject]@{Code=[int]$code; Json=$(try{$txt|ConvertFrom-Json}catch{$null}); Raw=$txt}
}
function Upload($path,$name){
  $out=& curl.exe -s --noproxy '*' -H "X-Booktrans-Token: $script:TOK" -F "file=@$path;filename=$name" -w '\n%{http_code}' "$script:BASE/api/jobs"
  [pscustomobject]@{Code=[int]$out[-1]; Json=$(try{($out[0..($out.Count-2)] -join "`n")|ConvertFrom-Json}catch{$null})}
}
function Wait-Job($id,$states=@('done','failed','paused','needs_decision'),$sec=240){
  $end=(Get-Date).AddSeconds($sec)
  while((Get-Date) -lt $end){ $j=(Api GET "/api/jobs/$id").Json; if($states -contains $j.state){return $j}; Start-Sleep -Milliseconds 400 }
  return $j
}
function Dl($id,$to){ & curl.exe -s --noproxy '*' -H "X-Booktrans-Token: $script:TOK" -D C:\Users\Public\bt\hdr.txt -o $to "$script:BASE/api/jobs/$id/download"; (Get-Item $to).Length }
function Stop-All { Get-Process BookTranslator -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 2 }
