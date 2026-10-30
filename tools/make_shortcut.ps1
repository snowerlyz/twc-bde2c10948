# 在桌面建立「台股羅盤」捷徑（套用羅盤圖示，雙擊就能開啟）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$desk = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desk '台股羅盤.lnk'
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$bat = Join-Path $root '啟動台股羅盤.bat'
# 用傳統主控台（conhost）開啟：Windows 11 預設的「終端機」不會套用捷徑與程式設定的圖示
$conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
if (Test-Path $conhost) {
  $s.TargetPath = $conhost
  $s.Arguments = ('cmd.exe /c "{0}"' -f $bat)
} else {
  $s.TargetPath = $bat
}
$s.WorkingDirectory = $root
$s.IconLocation = (Join-Path $root 'web\icon.ico') + ',0'
$s.WindowStyle = 7
$s.Description = '台股羅盤：台股分析、買賣建議與模擬交易'
$s.Save()
Write-Host ''
Write-Host ('已在桌面建立捷徑：' + $lnk)
Write-Host '之後雙擊桌面上的「台股羅盤」就能開啟。'
