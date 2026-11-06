# 작업 스케줄러가 매일 아침 실행하는 스크립트입니다.
# briefing.py 를 실행하고, 결과를 briefing.log 에 남기고, Windows 알림으로 알려 줍니다.

Set-Location -LiteralPath $PSScriptRoot

# Python 이 내보내는 한글이 깨지지 않게 UTF-8 로 읽습니다.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 2>&1 은 오류 메시지도 함께 받겠다는 뜻입니다.
$output = @(& python3 briefing.py 2>&1 | ForEach-Object { "$_" })
$exitCode = $LASTEXITCODE

# 실행할 때마다 로그 파일 끝에 덧붙입니다.
$time = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$log = @("=== $time (exit $exitCode) ===") + $output
Add-Content -LiteralPath 'briefing.log' -Value $log -Encoding UTF8

# 알림에는 기사 개수와 요약 결과가 적힌 마지막 두 줄만 보여 줍니다.
if ($exitCode -eq 0) {
    $message = ($output | Select-Object -Last 2) -join "`n"
} else {
    $message = '실행에 실패했습니다. briefing.log 를 확인해 주세요.'
}

try {
    $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

    $title = [System.Security.SecurityElement]::Escape('회계·감사 아침 브리핑')
    $body = [System.Security.SecurityElement]::Escape($message)
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")

    # 알림을 보내는 앱으로 Windows PowerShell 을 지정합니다.
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
} catch {
    # 알림이 실패해도 브리핑 결과는 이미 저장되어 있으므로 로그에만 남깁니다.
    Add-Content -LiteralPath 'briefing.log' -Value "알림 실패: $_" -Encoding UTF8
}

exit $exitCode
