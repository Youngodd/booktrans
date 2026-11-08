$f='C:\Users\Public\bt\BookTranslator-Setup-0.1.19.exe'
O ((Get-Item $f).Length)
O ((Get-FileHash $f -Algorithm SHA256).Hash)
