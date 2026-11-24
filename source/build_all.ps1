# Build both Daylock maps from your own Deadlock install (run again after every game update).
#   .\build_all.ps1                 everything: geometry, sun bakes, Midtown + Hideout -> work\out\*.vpk
#   .\build_all.ps1 -Map dl_hideout only one map
# Needs Python 3.14+ (packages in requirements.txt) and Go 1.22+. Takes ~10 minutes on a 32-core CPU.
# Deadlock is found through Steam; if it isn't, set DEADLOCK_DIR to your ...\steamapps\common\Deadlock folder.
param([ValidateSet('all', 'dl_midtown', 'dl_hideout')][string]$Map = 'all')
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$py = if (Test-Path "$here\.venv\Scripts\python.exe") { "$here\.venv\Scripts\python.exe" } else { 'python' }
$bake = "$here\daymod\sunbake\sunbake.exe"
function Run { param([string]$Exe) & $Exe @args; if ($LASTEXITCODE) { throw "$Exe failed ($LASTEXITCODE)" } }

if (-not (Test-Path $bake)) { Push-Location "$here\daymod\sunbake"; Run go build -o sunbake.exe .; Pop-Location }
New-Item -ItemType Directory -Force work | Out-Null

# sun direction per map (must match sun_bake in daymod\build_daymod.py)
$maps = [ordered]@{
  dl_midtown = @{ geom = 'work\geom_midtown'; sun = 'work\sun_midtown'; az = 60; el = 58 }
  dl_hideout = @{ geom = 'work\geom_hideout'; sun = 'work\sun_hideout_az170'; az = 170; el = 35 }
}
foreach ($m in $maps.Keys) {
  if ($Map -ne 'all' -and $Map -ne $m) { continue }
  $c = $maps[$m]
  Write-Host "== ${m}: geometry"; Run $py daymod\extract_geom.py $m $c.geom
  Write-Host "== ${m}: sun bake"; Run $bake lightmap -geom $c.geom -out $c.sun -az $c.az -el $c.el -samples 32 -skyvis 64
  if ($m -eq 'dl_hideout') {   # practice hall gets its own lighting settings (lightmap_regions in build_daymod.py)
    Run $bake lmbox -geom $c.geom -pick '10850,-9550,-450,12500,-7250,1300' -out work\mask_hideout_hall.u8 -size 8192
  }
  Write-Host "== ${m}: build"; Push-Location daymod; Run $py build_daymod.py ..\work --map $m; Pop-Location
}
Write-Host 'Done: work\out\. Install with .\install_daylock.ps1 (Deadlock closed).' -ForegroundColor Green
