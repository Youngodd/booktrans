# WARNING: this script saves a dummy key through the REAL Windows Credential Manager entry "BookTranslator" and then
# deletes it. If the account already has such an entry (a real key), do NOT run it: it would overwrite and remove it.
$data="$env:APPDATA\BookTranslator"
O ("data dir existed before: " + (Test-Path $data))
O ("cmdkey before: " + ((cmdkey /list | Select-String 'BookTranslator') -join ' | '))
$p=Launch-App
O ("app launched, pid " + $p.Id)
$c=Conn; O ("connection base: " + $c.base)
O ("has_key (first run): " + (CdpEval "window.pywebview.api.has_key().then(r=>JSON.stringify(r))"))
O ("K4-like: empty key: " + (CdpEval "window.pywebview.api.save_key('api','').then(r=>JSON.stringify(r))"))
O ("save_key sk-test-0000: " + (CdpEval "window.pywebview.api.save_key('api','sk-test-0000').then(r=>JSON.stringify(r))"))
O ("has_key after save: " + (CdpEval "window.pywebview.api.has_key().then(r=>JSON.stringify(r))"))
O ("K1 cmdkey /list: " + ((cmdkey /list | Select-String 'BookTranslator') -join ' | '))
$hits=@(Get-ChildItem $data -Recurse -File -ErrorAction SilentlyContinue | Select-String -SimpleMatch 'sk-test-0000' -List)
O ("K2 files in data dir: " + @(Get-ChildItem $data -Recurse -File | Select -Expand Name) -join ',' )
O ("K2 files containing the key: " + $hits.Count)
Stop-App
$p=Launch-App; 
O ("after restart has_key: " + (CdpEval "window.pywebview.api.has_key().then(r=>JSON.stringify(r))"))
O ("use_stored_key: " + (CdpEval "window.pywebview.api.use_stored_key().then(r=>JSON.stringify(r))"))
O ("K3 delete_key: " + (CdpEval "window.pywebview.api.delete_key().then(r=>JSON.stringify(r))"))
O ("has_key after delete: " + (CdpEval "window.pywebview.api.has_key().then(r=>JSON.stringify(r))"))
O ("K3 cmdkey after delete: [" + ((cmdkey /list | Select-String 'BookTranslator') -join ' | ') + "]")
Stop-App
