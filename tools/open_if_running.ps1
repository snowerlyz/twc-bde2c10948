# 台股羅盤已經在執行時：直接打開瀏覽器，不再開第二個（成功回傳 0）
$root = Split-Path -Parent $PSScriptRoot
$f = Join-Path $root 'data\server.json'
if (-not (Test-Path $f)) { exit 1 }
try {
  $p = (Get-Content $f -Raw | ConvertFrom-Json).port
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ('http://localhost:{0}/api/status' -f $p) | Out-Null
  Start-Process ('http://localhost:{0}/' -f $p)
  exit 0
} catch { exit 1 }
