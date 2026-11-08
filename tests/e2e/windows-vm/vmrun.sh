#!/bin/bash
# Run a PowerShell script in the UTM Windows guest and print its output.
# usage: VM=<uuid-or-name> vmrun.sh [--user] SCRIPT.ps1 [LIB.ps1 ...] [-t SECONDS]
#   --user   run as the logged-in desktop user (default: SYSTEM, the guest agent's account)
#   Several .ps1 files are concatenated in order (put lib first). Scripts may call O "text" to log.
# env: VM (required), GUEST_USER (default vagrant), UTMCTL (default /Applications/UTM.app/Contents/MacOS/utmctl)
set -u
U=${UTMCTL:-/Applications/UTM.app/Contents/MacOS/utmctl}; V=${VM:?set VM=<uuid or name>}; GU=${GUEST_USER:-vagrant}
HERE="$(cd "$(dirname "$0")" && pwd)"; AS_USER=0; T=120; FILES=()
while [ $# -gt 0 ]; do case "$1" in --user) AS_USER=1;; -t) shift; T=$1;; *) FILES+=("$1");; esac; shift; done
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
pre='$null=New-Item -ItemType Directory -Force C:\Users\Public\bt; $global:OUT="C:\Users\Public\bt\out.txt"; "" | Out-File $OUT -Encoding utf8; function O($x){ ($x | Out-String) | Out-File $OUT -Append -Encoding utf8 }'
{ printf '\357\273\277'; echo "$pre"; cat "${FILES[@]}"; echo '"DONE" | Out-File $OUT -Append -Encoding utf8'; } > "$W/run.ps1"
ex() { perl -e 'alarm 120; exec @ARGV' "$U" exec "$V" --cmd 'C:\Windows\System32\cmd.exe' /c "$1"; }
ex 'if not exist C:\Users\Public\bt mkdir C:\Users\Public\bt'
perl -e 'alarm 120; exec @ARGV' "$U" file push "$V" 'C:\Users\Public\bt\run.ps1' < "$W/run.ps1"
if [ $AS_USER = 1 ]; then
  sed "s/\/RU vagrant/\/RU $GU/" "$HERE/runuser.bat" > "$W/runuser.bat"
  perl -e 'alarm 60; exec @ARGV' "$U" file push "$V" 'C:\Users\Public\bt\runuser.bat' < "$W/runuser.bat"
  ex 'C:\Users\Public\bt\runuser.bat'
else
  ex 'del /q C:\Users\Public\bt\out.txt & C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Public\bt\run.ps1 > C:\Users\Public\bt\err.txt 2>&1'
fi
for ((i=0;i<T/4;i++)); do sleep 4; perl -e 'alarm 30; exec @ARGV' "$U" file pull "$V" 'C:\Users\Public\bt\out.txt' > "$W/out.txt" 2>/dev/null; grep -q DONE "$W/out.txt" && break; done
tr -d '\r\357\273\277' < "$W/out.txt" | grep -v '^\s*$'
