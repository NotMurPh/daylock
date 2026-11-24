# Install / uninstall the Daylock day-time mod (Midtown + Hideout).
#   .\install_daylock.ps1             install the built maps (work\out\*.vpk); gameinfo.gi is left original
#   .\install_daylock.ps1 -Uninstall  remove everything (game goes back to the normal night maps)
# Each map is a full modified copy at citadel\addons\maps\<map>.vpk (only lighting, sky, reflections,
# glow strength, fog/glow particles, storm clouds and colour grade differ; geometry is untouched, Midtown's
# entities are untouched, the Hideout (always a local server) has its fog entities switched off).
# After a Deadlock update, rebuild first:
#   .venv\Scripts\python daymod\build_daymod.py work                    (Midtown)
#   .venv\Scripts\python daymod\build_daymod.py work --map dl_hideout   (Hideout)
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$G = 'C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\citadel'
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
    & (Join-Path $here 'fog_gameinfo.ps1') -Remove
    & (Join-Path $here 'sun_gameinfo.ps1')
    Write-Host 'Daylock uninstalled.' -ForegroundColor Green
    exit 0
}
New-Item -ItemType Directory -Force (Join-Path $G 'addons\maps') | Out-Null
foreach ($m in $maps) {
    $src = Join-Path $here "work\out\$m.vpk"
    $info = Join-Path $here ($(if ($m -eq 'dl_midtown') { 'work\out\build_info.json' } else { "work\out\build_info_$m.json" }))
    if (-not (Test-Path $src)) { Write-Host "no build for $m, skipped" -ForegroundColor Yellow; continue }
    $sig = Get-MapSig (Join-Path $G "maps\$m.vpk")
    $built = (Get-Content $info -Raw | ConvertFrom-Json).source_map_signature
    if ($sig -ne $built) { Write-Host "$m changed since the last build (game update). Rebuild it first; skipped." -ForegroundColor Red; continue }
    Copy-Item $src (Join-Path $G "addons\maps\$m.vpk") -Force
    Write-Host "installed $m"
}
& (Join-Path $here 'sun_gameinfo.ps1')      # make sure the test-only sun setting is at its default
& (Join-Path $here 'fog_gameinfo.ps1') -Remove   # older versions added fog convars here; they had no effect, so keep gameinfo original
Write-Host 'Daylock installed.' -ForegroundColor Green
