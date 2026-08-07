<#
    setup_task_hardening.ps1

    Run ONCE from an elevated PowerShell (right-click > Run as Administrator).

    Fixes two things that make the nightly run unreliable on a laptop:

      1. Task Scheduler's history log is disabled by default, so when a run
         fails there is no record of why.

      2. The scheduled task's default settings are hostile to a laptop:
           - DisallowStartIfOnBatteries : the run is SKIPPED ENTIRELY if the
                                         laptop is unplugged at trigger time
           - StopIfGoingOnBatteries     : a run in progress is killed if you unplug
           - StartWhenAvailable = False : a missed run is never made up
           - RestartCount = 0           : a transient failure is never retried
           - RunOnlyIfNetworkAvailable  : off, so it runs before the network is up
#>

$TaskName = 'Food Scores Log'

Write-Host "== Enabling Task Scheduler history ==" -ForegroundColor Cyan
try {
    wevtutil set-log Microsoft-Windows-TaskScheduler/Operational /enabled:true
    Write-Host "   History enabled." -ForegroundColor Green
} catch {
    Write-Warning "   Could not enable history: $_"
}

Write-Host "== Hardening scheduled task '$TaskName' ==" -ForegroundColor Cyan
try {
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 10) `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -MultipleInstances IgnoreNew

    # Not exposed as switches on New-ScheduledTaskSettingsSet, so set directly.
    $settings.DisallowStartIfOnBatteries = $false
    $settings.StopIfGoingOnBatteries = $false

    Set-ScheduledTask -TaskName $TaskName -Settings $settings -ErrorAction Stop | Out-Null
    Write-Host "   Task settings updated." -ForegroundColor Green

    Get-ScheduledTask -TaskName $TaskName |
        Select-Object -ExpandProperty Settings |
        Select-Object StartWhenAvailable, RunOnlyIfNetworkAvailable, RestartCount,
                      RestartInterval, DisallowStartIfOnBatteries, StopIfGoingOnBatteries,
                      ExecutionTimeLimit |
        Format-List
} catch {
    Write-Warning "   Could not update the task: $_"
}

Write-Host "Done. Verify anytime with:" -ForegroundColor Cyan
Write-Host "    Get-ScheduledTaskInfo -TaskName '$TaskName'"
