# Screenshot tour: fly a noclip camera through fixed spots and save a screenshot at each one.
# Use it to check a build, or to compare day vs night (run it twice and use tools\compare.py).
#   .\tools\tour.ps1 -Launch                      start Deadlock, load local Midtown; you pick a hero, then it runs
#   .\tools\tour.ps1                              you're already in a local game on the map
#   .\tools\tour.ps1 -Map dl_hideout -Launch      the Hideout (no hero pick needed)
#   .\tools\tour.ps1 -Only 01_broadway,b5_mid_low -OutDir screenshots\test
# Offline only: it turns on sv_cheats/noclip in your own local game, and turns them off again at the end.
# The in-game console must be on the key in DAYLOCK_CONSOLE_KEY (default F7). Don't touch mouse/keyboard while it runs.
param(
  [ValidateSet('dl_midtown', 'dl_hideout')][string]$Map = 'dl_midtown',
  [string]$OutDir = '',
  [string[]]$Only = @(),
  [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$Only = @($Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ })   # also accept "a,b" as one string
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $root 'daymod\gamepath.ps1')
. (Join-Path $root 'tools\game.ps1')
if (-not $OutDir) { $OutDir = Join-Path $root ("screenshots\{0}_{1:yyyyMMdd_HHmmss}" -f $Map, (Get-Date)) }

$spots = if ($Map -eq 'dl_midtown') { [ordered]@{
  '01_broadway'       = 'setpos 0 -1500 400; setang 15 90 0'
  '02_blue_guardian'  = 'setpos -1288 -4100 650; setang 12 90 0'
  '03_yellow_t2'      = 'setpos -6272 -5300 650; setang 12 80 0'
  '04_purple_t2'      = 'setpos 5628 -5600 650; setang 12 100 0'
  '05_theater'        = 'setpos 4544 1300 520; setang 10 90 0'
  '06_basketball'     = 'setpos -4916 -2300 520; setang 12 90 0'
  '07_chinatown'      = 'setpos 3872 -4500 600; setang 10 90 0'
  '08_park_point'     = 'setpos 8300 -400 550; setang 10 45 0'
  '09_york_point'     = 'setpos -8300 400 560; setang 10 -135 0'
  '10_patron_base'    = 'setpos -1280 -6900 1000; setang 15 -90 0'
  '11_overview'       = 'setpos 0 -2500 2600; setang 45 90 0'
  '12_underground'    = 'setpos 0 -600 -700; setang 5 90 0'
  '13_sky_up'         = 'setpos 8300 -400 900; setang -30 160 0'
  '14_sky_city'       = 'setpos 0 -2500 1800; setang -8 60 0'
  '16_greenwich'      = 'setpos 6400 1200 330; setang 5 110 0'
  '18_archmother_base' = 'setpos 1280 6900 1000; setang 15 90 0'
  '19_york_high'      = 'setpos -7900 900 1150; setang 38 -40 0'
  '20_park_high'      = 'setpos 7900 -900 1150; setang 38 140 0'
  'b1_mid_high'       = 'setpos 0 -3000 1700; setang 22 90 0'
  'b3_cross_e'        = 'setpos 3936 -1300 1250; setang 12 90 0'
  'b4_cross_w'        = 'setpos -3936 -1300 1250; setang 12 90 0'
  'b5_mid_low'        = 'setpos 0 -1200 650; setang 2 90 0'
  'b5b_bridge_close'  = 'setpos 1200 -300 1000; setang 8 90 0'
  'i01_record_store'  = 'setpos -3800 -560 280; setang 10 0 0'
  'i02_tunnel_west'   = 'setpos -4024 -2264 40; setang 5 0 0'
  'i03_subway_entry'  = 'setpos 6200 2288 250; setang 10 180 0'
  'i04_apothecary'    = 'setpos 3900 -784 300; setang 10 0 0'
  'i05_factory_in'    = 'setpos 5984 3912 420; setang 10 90 0'
  'i08_shop_tunnel'   = 'setpos 0 0 -280; setang 5 90 0'
  'i09_point_house'   = 'setpos 8064 -900 260; setang 10 180 0'
  'x1_vent_steam'     = 'setpos -668 2860 560; setang 18 90 0'
  'x2_plaza_fog'      = 'setpos -2700 1600 520; setang 14 90 0'
} } else { [ordered]@{
  'h1_spawn_view'     = 'setpos 11598 -6144 -260; setang 5 180 0'
  'h2_window_city'    = 'setpos 10700 -6084 120; setang -3 180 0'
  'h3_window_wide'    = 'setpos 11200 -6084 60; setang -6 180 0'
  'h4_room_side'      = 'setpos 11500 -7900 0; setang 8 90 0'
  'h5_room_back'      = 'setpos 10900 -6100 -250; setang 5 0 0'
  'h6_library'        = 'setpos 11658 -6363 -273; setang 8 -104 0'
  'p2_hall_from_s'    = 'setpos 11650 -9200 150; setang 25 90 0'
  'p3_hall_from_e'    = 'setpos 12250 -8300 -100; setang 15 180 0'
  'p4_hall_from_w'    = 'setpos 11050 -8300 -100; setang 15 0 0'
  'p5_buttons'        = 'setpos 11300 -7750 -230; setang 20 -150 0'
  'p6_orb_corner'     = 'setpos 11400 -8900 -200; setang 20 -140 0'
  'p7_crates'         = 'setpos 11950 -7900 -50; setang 25 30 0'
  'p8_sinners'        = 'setpos 11800 -7900 -220; setang 15 60 0'
  'p9_hall_low'       = 'setpos 11300 -8950 -270; setang 5 25 0'
} }

$unknown = @($Only | Where-Object { -not $spots.Contains($_) })
if ($unknown.Count) { throw "unknown spot(s): $($unknown -join ', '). Spots on ${Map}: $($spots.Keys -join ', ')" }

$cheatsOn = $false
try {
  if ($Launch) {
    if (Get-GameWindow) { throw 'Deadlock is already running: close it, or run without -Launch' }
    Start-Process (Get-SteamExe) -ArgumentList '-applaunch', '1422450', '-novid', '-console'
    if (-not (Wait-Until { Get-GameWindow } 180)) { throw 'Deadlock window did not appear' }
    Write-Host 'game started, waiting for the title screen...'
    Start-Sleep 25; Send-GameKey SPACE; Start-Sleep 8      # title screen -> Hideout
    if ($Map -eq 'dl_midtown') {
      Send-GameCommand 'map dl_midtown'
      Restore-Desktop
      Write-Host "`nIn Deadlock: pick a team and a hero and wait until you're in the map." -ForegroundColor Yellow
      Read-Host 'Then come back here and press Enter'
    }
  } elseif (-not (Get-GameWindow)) { throw 'Deadlock is not running (use -Launch)' }

  Send-GameCommand 'sv_cheats 1; noclip 1' 500; $cheatsOn = $true
  $n = 0
  foreach ($k in $spots.Keys) {
    if ($Only.Count -and -not ($Only -contains $k)) { continue }
    Send-GameCommand $spots[$k] 600
    Save-GameShot (Join-Path $OutDir "$k.png"); $n++
  }
  Write-Host "$n screenshots in $OutDir" -ForegroundColor Green
} finally {
  if ($cheatsOn -and (Get-GameWindow)) { Send-GameCommand 'noclip 0; sv_cheats 0' 300 }
  Restore-Desktop
}
