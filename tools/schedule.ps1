# 台股羅盤：設定（或取消）每個交易日晚上自動更新資料
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$name = 'TWCompass_DailyUpdate'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host '已取消每日自動更新。'
    exit 0
}
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'runtime\python\pythonw.exe'
if (-not (Test-Path $py)) {
    Write-Host '找不到 Python，請先執行一次「啟動台股羅盤」完成第一次設定。'
    exit 1
}
$main = Join-Path $root 'app\main.py'
$action = New-ScheduledTaskAction -Execute $py -Argument "-X utf8 `"$main`" update" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '21:40'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description '台股羅盤：每個交易日晚上 9:40 自動抓取官方資料並重新分析' -Force | Out-Null
Write-Host ''
Write-Host '已設定完成：每週一到週五晚上 9:40 自動更新資料（電腦開著並登入時執行；錯過的話會在下次開機後補跑）。'
Write-Host '想取消時，執行「取消每日自動更新」。'
