# One-click Daylock on/off (run "Daylock Toggle.bat"). Deadlock must be closed: the day lighting is baked into the
# map files, which the game only reads at startup / map load.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'daymod\gamepath.ps1')
$G = Get-Citadel
function Say($msg, $icon = 'Information') { if ($env:DAYLOCK_QUIET) { Write-Output $msg } else { [void][System.Windows.Forms.MessageBox]::Show($msg, 'Daylock', 'OK', $icon) } }

if (Get-Process deadlock -ErrorAction SilentlyContinue) {
    Say "Close Deadlock first, then run the toggle again.`n(The day lighting is part of the map files, which the game only loads at startup.)" 'Warning'
    exit 1
}
$on = Test-Path (Join-Path $G 'addons\maps\dl_midtown.vpk')
$inst = Join-Path $here 'install_daylock.ps1'
if ($on) { $log = & $inst -Uninstall *>&1 | Out-String } else { $log = & $inst *>&1 | Out-String }
$nowOn = Test-Path (Join-Path $G 'addons\maps\dl_midtown.vpk')
if ($on -and -not $nowOn) { Say 'Daylock is OFF - Deadlock will use the normal night maps.' }
elseif (-not $on -and $nowOn) { Say 'Daylock is ON - daytime Midtown and Hideout.' }
else { Say "Nothing changed:`n$log" 'Warning'; exit 1 }
