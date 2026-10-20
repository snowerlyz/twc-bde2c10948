# 台股羅盤：第一次使用時下載免安裝的 Python（只放在本資料夾的 runtime 裡，不會安裝到系統）
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root 'runtime\python'
$ver = '3.12.10'
$arch = 'amd64'
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $arch = 'arm64' }
elseif ($env:PROCESSOR_ARCHITECTURE -eq 'x86' -and -not $env:PROCESSOR_ARCHITEW6432) { $arch = 'win32' }
$url = "https://www.python.org/ftp/python/$ver/python-$ver-embed-$arch.zip"
Write-Host ''
Write-Host '台股羅盤：第一次使用，正在下載免安裝的 Python（約 11 MB）...'
Write-Host "來源：$url"
$zip = Join-Path $env:TEMP "twc-python-$ver-$arch.zip"
try {
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Remove-Item $zip -ErrorAction SilentlyContinue
    Write-Host '完成。'
} catch {
    Write-Host ''
    Write-Host ('下載失敗：' + $_.Exception.Message)
    Write-Host '請確認電腦可以連上網路後，再重新執行「啟動台股羅盤」。'
    exit 1
}
