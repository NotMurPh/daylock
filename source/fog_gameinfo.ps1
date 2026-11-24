# Add or remove Daylock's three fog-off lines in gameinfo.gi (ConVars section).
# Same method the "Daylock" GameBanana mod uses. Lines are tagged "// Daylock" so removal is exact.
#   .\fog_gameinfo.ps1 -Remove     -> take them out again
param([switch]$Remove)
$gi = 'C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\citadel\gameinfo.gi'
$text = [System.IO.File]::ReadAllText($gi)
$nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
# always strip our lines first (idempotent)
$clean = [regex]::Replace($text, '(?m)^[ \t]*"r_enable_(volume|gradient|cubemap)_fog"[ \t]+"0"[ \t]*// Daylock\r?\n', '')
if ($Remove) {
    if ($clean -ne $text) { [System.IO.File]::WriteAllText($gi, $clean); Write-Host 'Daylock fog lines removed from gameinfo.gi' }
    else { Write-Host 'No Daylock fog lines in gameinfo.gi' }
    exit 0
}
$m = [regex]::Match($clean, '(?m)^([ \t]*)ConVars[ \t]*\r?\n[ \t]*\{[ \t]*\r?\n')
if (-not $m.Success) { Write-Host 'ConVars section not found in gameinfo.gi' -ForegroundColor Red; exit 1 }
$ind = $m.Groups[1].Value + "`t"
$lines = ($ind + '"r_enable_volume_fog" "0" // Daylock' + $nl + $ind + '"r_enable_gradient_fog" "0" // Daylock' + $nl + $ind + '"r_enable_cubemap_fog" "0" // Daylock' + $nl)
$new = $clean.Insert($m.Index + $m.Length, $lines)
[System.IO.File]::WriteAllText($gi, $new)
Write-Host 'Daylock fog lines added to gameinfo.gi'
