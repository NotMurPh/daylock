# Install / uninstall the Daylock maps you built (work\out\*.vpk). Deadlock must be closed.
#   .\install_daylock.ps1             copy the built maps to citadel\addons\maps\
#   .\install_daylock.ps1 -Uninstall  remove them (the game goes back to the normal night maps)
# Each map is a full modified copy of the original, so a map is skipped if Deadlock updated it after your build:
# run .\build_all.ps1 again in that case. Nothing else in the game folder is changed.
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'daymod\gamepath.ps1')
$G = Get-Citadel
$maps = @('dl_midtown', 'dl_hideout')
if (Get-Process deadlock -ErrorAction SilentlyContinue) { Write-Host 'Close Deadlock first.' -ForegroundColor Yellow; exit 1 }

function Get-MapSig($path) {
    $fs = [System.IO.File]::OpenRead($path); $buf = New-Object byte[] 1048576; [void]$fs.Read($buf, 0, $buf.Length); $fs.Close()
    $md5 = [System.BitConverter]::ToString([System.Security.Cryptography.MD5]::Create().ComputeHash($buf)).Replace('-', '').ToLower()
    "${md5}_$((Get-Item $path).Length)"
}

if ($Uninstall) {
    foreach ($m in $maps) {
        $dst = Join-Path $G "addons\maps\$m.vpk"
        if (Test-Path $dst) { Remove-Item $dst -Force; Write-Host "removed $m" }
    }
    $md = Join-Path $G 'addons\maps'
    if ((Test-Path $md) -and -not (Get-ChildItem $md)) { Remove-Item $md }
    Write-Host 'Daylock uninstalled.' -ForegroundColor Green
    exit 0
}
New-Item -ItemType Directory -Force (Join-Path $G 'addons\maps') | Out-Null
foreach ($m in $maps) {
    $src = Join-Path $here "work\out\$m.vpk"
    $info = Join-Path $here ($(if ($m -eq 'dl_midtown') { 'work\out\build_info.json' } else { "work\out\build_info_$m.json" }))
    if (-not (Test-Path $src)) { Write-Host "no build for $m, skipped" -ForegroundColor Yellow; continue }
    # build_daymod.py records which original map it was built from (MD5 of its first MB + its size)
    $built = (Get-Content $info -Raw | ConvertFrom-Json).source_map_signature
    if ((Get-MapSig (Join-Path $G "maps\$m.vpk")) -ne $built) {
        Write-Host "$m changed since your build (game update). Run .\build_all.ps1 first; skipped." -ForegroundColor Red; continue
    }
    Copy-Item $src (Join-Path $G "addons\maps\$m.vpk") -Force
    Write-Host "installed $m"
}
Write-Host 'Daylock installed.' -ForegroundColor Green
