$zhdir = 'C:\' + [string]::new([char[]](0x6D4B,0x8BD5)) + '\' + [string]::new([char[]](0x4E66,0x7C4D))   # C:\测试\书籍
$zhname = [string]::new([char[]](0x5316,0x5B66,0x4E4B,0x6811)) + '.pdf'                                  # 化学之树.pdf
$null=New-Item -ItemType Directory -Force $zhdir; Copy-Item C:\Users\Public\bt\files\zh4.pdf (Join-Path $zhdir $zhname) -Force
$data = Join-Path $zhdir ([string]::new([char[]](0x6570,0x636E)))                                         # ...\数据
$p=Start-Side $data; O ("sidecar up: " + $script:BASE + " data=" + $data + " (Chinese path)")
O ("no-token request: " + (curl.exe -s --noproxy '*' -o NUL -w '%{http_code}' "$script:BASE/api/config"))
$r=Api PUT /api/key @{api_key='sk-test-0000';provider='api'}; O ("PUT /api/key: " + $r.Code)
$nl=@{auto_glossary=$false;spend_limit=0}
function Run($label,$file,$name,$extra=@{}){
  $u=Upload $file $name; if($u.Code -ne 200){ O "$label upload failed $($u.Code)"; return }
  $id=$u.Json.id; $s=Api POST "/api/jobs/$id/start" ($nl + $extra); if($s.Code -ne 200){ O "$label start $($s.Code) $($s.Raw)"; return }
  $j=Wait-Job $id; $pdfout="C:\Users\Public\bt\out\$label.pdf"
  $size= if($j.state -eq 'done'){ Dl $id $pdfout } else {0}
  O ("$label : state=" + $j.state + " pages_total=" + $u.Json.pages_total + " filename=" + $u.Json.filename + " out_bytes=" + $size + " err=" + $j.error)
  $id
}
$null=Run 'pdf12' 'C:\Users\Public\bt\files\book12.pdf' 'book12.pdf'
$null=Run 'epub' 'C:\Users\Public\bt\files\book.epub' 'book.epub'
$null=Run 'txt' 'C:\Users\Public\bt\files\book.txt' 'book.txt'
$null=Run 'range' 'C:\Users\Public\bt\files\book12.pdf' 'book12.pdf' @{pages='3-5'}
$null=Run 'preview' 'C:\Users\Public\bt\files\book12.pdf' 'book12.pdf' @{preview=$true}
$zid=Run 'zh' (Join-Path $zhdir $zhname) $zhname
O ("zh download header: " + ((Get-Content C:\Users\Public\bt\hdr.txt | Select-String -Pattern 'content-disposition') -join ''))
# delete (T6)
$jd=$data + '\jobs\' + $zid; O ("job folder exists before delete: " + (Test-Path $jd))
$d=Api DELETE "/api/jobs/$zid"; O ("DELETE: " + $d.Code + "; folder exists after: " + (Test-Path $jd) + "; GET after: " + (Api GET "/api/jobs/$zid").Code)
# spend guard
$u=Upload 'C:\Users\Public\bt\files\book12.pdf' 'book12.pdf'; $id=$u.Json.id
$null=Api POST "/api/jobs/$id/start" @{auto_glossary=$false;spend_limit=3}; $j=Wait-Job $id
O ("spend limit 3: state=" + $j.state + " spent=" + $j.spent_cny + " est_rest=" + $j.est_rest_cny)
$null=Api POST "/api/jobs/$id/start" @{auto_glossary=$false;only_cached=$true;spend_limit=3}; $j=Wait-Job $id; O ("finish partial: state=" + $j.state + " partial=" + $j.partial)
O ("log has key? " + [bool](Select-String -Path "$data\sidecar.log" -SimpleMatch 'sk-test-0000' -Quiet))
O ("files containing key under data dir: " + @(Get-ChildItem $data -Recurse -File | Select-String -SimpleMatch 'sk-test-0000' -List).Count)
Stop-All; O ("processes left: " + @(Get-Process BookTranslator -ErrorAction SilentlyContinue).Count)
