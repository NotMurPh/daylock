# Turn Deadlock's sun-light system on or off by editing ONE line of gameinfo.gi
# (SceneSystem / SunLightManagerCount). Nothing else in the file is touched.
#   .\sun_gameinfo.ps1 -Enable    -> SunLightManagerCount 1
#   .\sun_gameinfo.ps1            -> SunLightManagerCount 0 (game default)
param([switch]$Enable)
$gi = 'C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\citadel\gameinfo.gi'
$v = if ($Enable) { 1 } else { 0 }
$text = [System.IO.File]::ReadAllText($gi)
$new = [regex]::Replace($text, '(?m)^(\s*SunLightManagerCount\s+)\d+', "`${1}$v")
if ($new -ne $text) { [System.IO.File]::WriteAllText($gi, $new); Write-Host "SunLightManagerCount set to $v" }
else { Write-Host "SunLightManagerCount already $v" }
