# 台股羅盤：安裝機器學習套件（numpy、lightgbm）到本資料夾的 runtime 裡。失敗也不影響使用（只用原本的加權分數）。
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'runtime\python\python.exe'
$mark = Join-Path $root 'runtime\ml_setup_done.txt'
if (Test-Path $mark) { exit 0 }
if (-not (Test-Path $py)) { exit 0 }
Write-Host ''
Write-Host '台股羅盤：第一次安裝機器學習套件（約 30 MB，只需一次）...'
try {
    $pth = Get-ChildItem (Join-Path $root 'runtime\python') -Filter 'python*._pth' | Select-Object -First 1
    if ($pth) {
        $c = Get-Content $pth.FullName
        $c = $c -replace '^#\s*import site', 'import site'
        if (-not ($c -match '^Lib\\site-packages$')) { $c += 'Lib\site-packages' }
        Set-Content -Path $pth.FullName -Value $c -Encoding ASCII
    }
    $gp = Join-Path $env:TEMP 'twc-get-pip.py'
    Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $gp -UseBasicParsing
    & $py $gp --no-warn-script-location -q
    & $py -m pip install --no-warn-script-location -q numpy lightgbm
    & $py -c "import numpy, lightgbm; print('ok')"
    if ($LASTEXITCODE -eq 0) { Write-Host '完成。' } else { Write-Host '安裝未完成，先只用加權分數。' }
} catch {
    Write-Host ('安裝機器學習套件失敗：' + $_.Exception.Message + '（不影響使用）')
}
Set-Content -Path $mark -Value (Get-Date -Format 'yyyy-MM-dd HH:mm') -Encoding ASCII
exit 0
