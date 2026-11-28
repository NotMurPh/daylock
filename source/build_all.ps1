# Build both Daylock maps from your own Deadlock install (run again after every game update).
#   .\build_all.ps1                         the original look: geometry, sun bakes, Midtown + Hideout -> work\out\*.vpk
#   .\build_all.ps1 -Map dl_hideout         only one map
#   .\build_all.ps1 -Looks day,dusk         both looks -> work\out\*.vpk (day) + work\out_dusk\*.vpk
#                                           (each look ships as its own mod: tools\package.py --maps work\out_dusk)
# Needs Python 3.14+ (packages in requirements.txt) and Go 1.22+. One look takes ~10 minutes on a 32-core CPU.
# Deadlock is found through Steam; if it isn't, set DEADLOCK_DIR to your ...\steamapps\common\Deadlock folder.
param([ValidateSet('all', 'dl_midtown', 'dl_hideout')][string]$Map = 'all',
      [ValidateSet('day', 'dusk')][string[]]$Looks = @('day'))
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$py = if (Test-Path "$here\.venv\Scripts\python.exe") { "$here\.venv\Scripts\python.exe" } else { 'python' }
$bake = "$here\daymod\sunbake\sunbake.exe"
function Run { param([string]$Exe) & $Exe @args; if ($LASTEXITCODE) { throw "$Exe failed ($LASTEXITCODE)" } }

if (-not (Test-Path $bake)) { Push-Location "$here\daymod\sunbake"; Run go build -o sunbake.exe .; Pop-Location }
New-Item -ItemType Directory -Force work | Out-Null

# geometry + sun bake per map and look (must match sun_bake in CFG / LOOKS of daymod\build_daymod.py)
$geom = @{ dl_midtown = 'work\geom_midtown'; dl_hideout = 'work\geom_hideout' }
$suns = @{
  'dl_midtown/day'  = @{ dir = 'work\sun_midtown'; az = 60; el = 58 }
  'dl_midtown/dusk' = @{ dir = 'work\sun_midtown_az170_el30'; az = 170; el = 30 }
  'dl_hideout/day'  = @{ dir = 'work\sun_hideout_az170'; az = 170; el = 35 }   # every look shares the Hideout bake
}
$maps = @('dl_midtown', 'dl_hideout') | Where-Object { $Map -eq 'all' -or $Map -eq $_ }
foreach ($m in $maps) {
  Write-Host "== ${m}: geometry"; Run $py daymod\extract_geom.py $m $geom[$m]
  $done = @{}
  foreach ($look in $Looks) {
    $s = $suns["$m/$look"]; if (-not $s) { $s = $suns["$m/day"] }
    if ($done[$s.dir]) { continue }; $done[$s.dir] = $true
    Write-Host "== ${m}: sun bake $($s.dir) (az $($s.az) el $($s.el))"
    Run $bake lightmap -geom $geom[$m] -out $s.dir -az $s.az -el $s.el -cone 0.27 -samples 64 -skyvis 64   # real sun size: crisp far shadows
  }
  if ($m -eq 'dl_hideout') {   # practice hall gets its own lighting settings (lightmap_regions in build_daymod.py)
    Run $bake lmbox -geom $geom[$m] -pick '10850,-9550,-450,12500,-7250,1300' -out work\mask_hideout_hall.u8 -size 8192
  }
  foreach ($look in $Looks) {
    Write-Host "== ${m}: build $look"
    Push-Location daymod; Run $py build_daymod.py ..\work --map $m --look $look; Pop-Location
  }
}
Write-Host 'Done: work\out[_<look>]\. Install with .\install_daylock.ps1 (Deadlock closed) or pack a look with tools\package.py.' -ForegroundColor Green
