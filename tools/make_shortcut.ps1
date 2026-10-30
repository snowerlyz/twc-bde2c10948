# 在桌面建立「台股羅盤」捷徑（套用羅盤圖示，雙擊就能開啟）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$desk = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desk '台股羅盤.lnk'
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = Join-Path $root '啟動台股羅盤.bat'
$s.WorkingDirectory = $root
$s.IconLocation = (Join-Path $root 'web\icon.ico') + ',0'
$s.WindowStyle = 7
$s.Description = '台股羅盤：台股分析、買賣建議與模擬交易'
$s.Save()
Write-Host ''
Write-Host ('已在桌面建立捷徑：' + $lnk)
Write-Host '之後雙擊桌面上的「台股羅盤」就能開啟。'
