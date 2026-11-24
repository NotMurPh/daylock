# Daylock source

This is everything that builds the Daylock maps. It doesn't contain any game files: it reads Midtown and the
Hideout from your own Deadlock install and writes day versions of them.

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

That takes about 10 minutes and writes `work\out\dl_midtown.vpk` and `work\out\dl_hideout.vpk`. With Deadlock
closed, `.\install_daylock.ps1` copies them to `citadel\addons\maps\` (`-Uninstall` removes them), or double-click
`Daylock Toggle.bat` to switch between day and night.

If Steam isn't in the default folder, change `GAME` at the top of `daymod\build_daymod.py` and
`daymod\extract_geom.py`.

After a Deadlock update that changes a map, run `build_all.ps1` again.

## Files

- `daymod\build_daymod.py`: the build, all settings are in `CFG` at the top
- `daymod\sunbake\`: sun and sky ray tracer (Go)
- `daymod\sunlight.py`, `daylight.py`, `probes_sun.py`: night to day lighting
- `daymod\build_sky.py`: the cloudy day sky
- `daymod\s2res.py`, `kv3.py`, `kv3t.py`, `texio.py`, `bc6h.py`, `texgrade.py`, `vpkwrite.py`, `murmur.py`:
  reading and writing Source 2 files

## Credits

- `sunbake\meshopt.go` is a port of the vertex/index decoders from
  [meshoptimizer](https://github.com/zeux/meshoptimizer) (MIT, Arseny Kapoulkine)
- `kv3.py` follows the KV3 reader in [ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat) (MIT)
