# Find the Deadlock install (dot-source: . .\daymod\gamepath.ps1).
# Order: the DEADLOCK_DIR environment variable (your ...\steamapps\common\Deadlock folder), then every Steam library
# listed in Steam's libraryfolders.vdf, then the default Steam folder. Same logic as gamepath.py.
$script:DefaultSteam = 'C:\Program Files (x86)\Steam'

function Get-SteamDir {
  $p = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -Name SteamPath -ErrorAction SilentlyContinue).SteamPath
  if ($p) { return [IO.Path]::GetFullPath($p) }
  $script:DefaultSteam
}

function Get-DeadlockDir {
  if ($env:DEADLOCK_DIR) {
    if (Test-Path (Join-Path $env:DEADLOCK_DIR 'game\citadel\gameinfo.gi')) { return [IO.Path]::GetFullPath($env:DEADLOCK_DIR) }
    throw "DEADLOCK_DIR=$env:DEADLOCK_DIR is not a Deadlock folder (no game\citadel\gameinfo.gi)"
  }
  $steam = Get-SteamDir
  $libs = @($steam)
  $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
  if (Test-Path $vdf) {
    $libs += [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"') | ForEach-Object { $_.Groups[1].Value -replace '\\\\', '\' }
  }
  foreach ($lib in $libs + $script:DefaultSteam) {
    $d = Join-Path $lib 'steamapps\common\Deadlock'
    if (Test-Path (Join-Path $d 'game\citadel\gameinfo.gi')) { return [IO.Path]::GetFullPath($d) }
  }
  throw 'Deadlock not found. Set DEADLOCK_DIR to your ...\steamapps\common\Deadlock folder.'
}

# ...\Deadlock\game\citadel
function Get-Citadel { Join-Path (Get-DeadlockDir) 'game\citadel' }

function Get-SteamExe { Join-Path (Get-SteamDir) 'steam.exe' }
