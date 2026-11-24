# Daylock source

Everything that builds, tests and packages Daylock. There are no game files in here: the build reads Midtown and
the Hideout from your own Deadlock install and writes day versions of them.

## How it works

Deadlock's maps have no sun. The night look is baked into the lighting data (lightmaps, light probes, fog volume,
reflections), so swapping the sky isn't enough. The build:

1. pulls the world geometry out of the map (`extract_geom.py`)
2. ray traces a sun and the sky over it (`sunbake`, written in Go): which surfaces are in sunlight, how much sky
   they see
3. rebuilds the lightmaps and light probes from that, keeping some of the original light indoors (`sunlight.py`)
4. tones down lamps, neon and window glow, removes the storm and smog, adds a blue sky with clouds and a day colour
   grade (`build_daymod.py`, `build_sky.py`)
5. packs everything into a full copy of the map (`vpkwrite.py`)

Walls, cover (vent steam, plaza fog), items and spawns aren't touched.

## Build it

You need Windows, Deadlock, [Python 3.14+](https://www.python.org/) and [Go 1.22+](https://go.dev/).

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.\build_all.ps1
```

It writes `work\out\dl_midtown.vpk` and `work\out\dl_hideout.vpk`. That took 11 minutes on a 32-core CPU; expect
longer on smaller ones, and a few GB of disk in `work\`.

The game folder is found through Steam (any library folder). If it isn't, set `DEADLOCK_DIR` to your
`...\steamapps\common\Deadlock` folder.

With Deadlock closed, `.\install_daylock.ps1` copies the maps to `citadel\addons\maps\` (`-Uninstall` removes
them), or double-click `Daylock Toggle.bat` to switch between day and night. After a Deadlock update that changes a
map, run `build_all.ps1` again: the installer refuses a map that was built from an older version.

All the look settings (sun direction and strength, glow dimming, colour grade, sky) are in `CFG` at the top of
`daymod\build_daymod.py`.

## Test it

`tools\tour.ps1` flies a noclip camera through fixed spots and saves a screenshot at each one:

```
.\tools\tour.ps1 -Launch                    # starts Deadlock, loads local Midtown, you pick a hero, it does the rest
.\tools\tour.ps1 -Map dl_hideout -Launch    # the Hideout
.\tools\tour.ps1 -Only 01_broadway,b5_mid_low
python tools\compare.py screenshots\night screenshots\day night_vs_day.jpg --labels Night Day
```

It types into the in-game console, so the console has to be enabled; it uses F7 unless you set
`DAYLOCK_CONSOLE_KEY` (for example `GRAVE` for the ` key). Offline only: it turns on `sv_cheats` and noclip in your
own local game and turns them off again at the end. Don't touch the mouse or keyboard while it runs. Your clipboard
and the window you were in are put back afterwards.

`daymod\contact.py <folder> <out.jpg>` makes a contact sheet of a screenshot folder.

## Package and publish

```
python tools\package.py --version 1.2 --note "Built for the 2026-12-01 patch." --page https://you.github.io/daylock/
```

makes `work\release\Daylock_v1.2.zip` (`pak99_dir.vpk` holding both maps, plus a README) and prints its size and
SHA-256.

For Deadlock Mod Manager, `tools\dmm_source.py` writes a static mod source (`dmm-source.json`, `catalog.json`,
`mods\daylock.json`) that points at the zip on GitHub Releases:

```
python tools\dmm_source.py --site https://you.github.io/daylock/ --repo https://github.com/you/daylock --version 1.2 --zip work\release\Daylock_v1.2.zip --out site
```

Upload the zip as `Daylock_v1.2.zip` to a release tagged `v1.2`, host the `site` folder on GitHub Pages, and people add
`https://you.github.io/daylock/dmm-source.json` under Settings > Mods > Mod sources. Custom mod sources are only in
the Mod Manager's [Nightly build](https://github.com/deadlock-mod-manager/deadlock-mod-manager/releases/tag/nightly)
for now (they came after 2.3.0).

## Things worth knowing

- Files inside `maps\<map>.vpk` can't be overridden one by one with an addon pak, so the mod ships the whole map in
  `addons\maps\`. That's also why every map update from Valve needs a rebuild.
- Test a new build with a fresh game start. The game caches map files, materials and the sky per session, and
  replacing a map file while the game is running can freeze it on the next map load.
- Colour parameters inside compiled materials do nothing at runtime. To recolour something, change its texture
  (`texgrade.py`).
- Draw call numbers change whenever Valve recompiles a map. Match things by stable values instead (the bridge tint
  is matched by its original colour).
- The white haze in the distance comes from the fog sampling the blurry sky mips; darkening those mips removes it
  (`sky_fog_mip_scale`). The `r_enable_*_fog` convars in `gameinfo.gi` do nothing.
- The bakes use random rays, so two builds are never byte-identical. The difference is tiny noise.
- Leave gameplay cover alone (vent steam, the sunken plaza fog). Removing it would be an unfair advantage.
- Closing the game with the `quit` console command saves convars to your config. The tour only uses `sv_cheats`
  and noclip, which aren't saved.

## Files

- `build_all.ps1`: the whole build
- `daymod\build_daymod.py`: builds one map, all settings are in `CFG`
- `daymod\sunbake\`: sun and sky ray tracer (Go), also has debug modes (`pick`, `topdown`, `lmbox`)
- `daymod\sunlight.py`, `daylight.py`, `probes_sun.py`: night to day lighting
- `daymod\build_sky.py`: the cloudy day sky
- `daymod\s2res.py`, `kv3.py`, `kv3t.py`, `texio.py`, `bc6h.py`, `texgrade.py`, `vpkwrite.py`, `murmur.py`:
  reading and writing Source 2 files
- `daymod\gamepath.py`, `gamepath.ps1`: find the Deadlock folder
- `daymod\decode_tex.py`, `dump_ents.py`, `ent_query.py`, `pick_spots.py`, `measure.py`, `contact.py`: helpers for
  looking inside maps and screenshots
- `tools\tour.ps1`, `game.ps1`, `compare.py`: screenshot tests
- `tools\package.py`, `release_readme.txt`, `dmm_source.py`: release zip and Mod Manager source

## Credits

- `sunbake\meshopt.go` is a port of the vertex/index decoders from
  [meshoptimizer](https://github.com/zeux/meshoptimizer) (MIT, Arseny Kapoulkine)
- `kv3.py` follows the KV3 reader in [ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat) (MIT)
