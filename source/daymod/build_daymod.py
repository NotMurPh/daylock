"""Build a Daylock day-time map (dl_midtown by default, also dl_hideout).

usage: build_daymod.py <work_dir> [--map dl_midtown|dl_hideout] [--install] [--only lightmap,probes,fog,cubemap,ents,sky] [--cache]
Reads the CURRENT game files, so re-run it after every Deadlock update.
Output: <work_dir>/out/dl_midtown.vpk  (--install copies it to citadel/addons/maps/)
"""
import os, re, sys, time, json, struct, shutil, hashlib, argparse
import numpy as np
import vpk
from s2res import Resource, Texture
import texio, daylight, kv3t, scan_emissive, gamepath
from vpkwrite import write_vpk, from_vpk

GAME = gamepath.citadel()   # set DEADLOCK_DIR if it isn't found
MAPNAME = 'dl_midtown'
MAP = os.path.join(GAME, 'maps', 'dl_midtown.vpk')
PAK = os.path.join(GAME, 'pak01_dir.vpk')
LM = 'maps/dl_midtown/lightmaps/'
SKY_NAMES = ('dl_midtown_dusk_02', 'sky_dl_dusk03', 'dl_midtown_halloween', 'sky_dl_hideout_storm_01',
             'sky_dl_hideout_dusk01', 'sky_dl_hideout_sunset_clouds_01', 'sky_dl_hideout_sunset_clouds_01_winter')

# ---------------------------------------------------------------- settings ---
CFG = dict(
    # real ray-traced sun (daymod/sunbake): per map bake dir + sun direction used for the bake
    sun_bake={'dl_midtown': dict(dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'sun_midtown'),
                                 geom=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'geom_midtown'), az=60, el=58),
              'dl_hideout': dict(dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'sun_hideout_az170'),
                                 # az 170 / el 35 (was 200/32): sun also reaches the practice hall (~5% of its floor vs 0.6%), spawn room unchanged (~6%)
                                 geom=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'geom_hideout'), az=170, el=35)},
    lightmap_sun=dict(__import__('sunlight').V9, vis_sharpen=1.0),   # crisper sun edges (bake: cone 0.27, 64 rays)
    probes_sun=dict(__import__('sunlight').V9, fill_gain=0.52),   # objects slightly less fill than surfaces: boxes don't pop out of rooms
    lightmap=dict(daylight.V8),
    probes=dict(daylight.V8),
    fog=dict(daylight.V8, sky_gain=0.8, bounce_gain=0.4, sun_gain=0.3, scale=0.12),  # fog barely lit -> no glowing haze
    cubemap=dict(daylight.V8, scale=0.12),  # 0.4 gave white painted props (crates, Sinner's Sacrifice, buttons) a pale milky sheen
    sky_material='materials/skybox/light_test_quarry.vmat_c',   # its texture is replaced by build_sky.compose()
    sky_fog_mip_scale=[0.20, 0.22, 0.27],  # darken only the blurry sky mips that cubemap fog samples -> no white haze (works online)
    # NOTE: vent steam (street_steam_02) and the sunken-plaza fog (plaza_fog_*, fog_plane_01) are gameplay cover
    # (they hide players) -> never removed.
    blank_particles=[   # lamp halos and the Patron storm glow -> empty particle systems
        'particles/environmental/street_light_glow_01.vpcf_c', 'particles/environmental/street_light_glow_02.vpcf_c',
        'particles/environmental/lamp_glow_01.vpcf_c', 'particles/environmental/storm_glow_01.vpcf_c',
    ],
    vpost=dict(  # day colour grade for Midtown (copy of basepostprocess_deadlock with tweaks)
        files=['postprocessing/basepostprocess_deadlock.vpost_c'],
        set={'m_bloomParams.m_flSkyboxBloomStrength': 0.25, 'm_bloomParams.m_flBloomStrength': 0.35,
             'm_vignetteParams.m_flVignetteStrength': -0.25},
        lut=dict(contrast=0.32, saturation=1.25, cool_shadows=0.03, warm_highlights=0.03, shadow_lift=0.08, highlight_rolloff=0.35),
    ),
    emissive_rules=[  # (regex on material path, glow multiplier); first match wins
        (r'props_gameplay|props_endgame|/base/|abilit|heroes|npc|zipline|objective|abstract_emissive', 1.0),
        (r'rune|sigil|portal|artifact|atlas_eye|statue_fairfax|crystal_ball|fortune_teller|king_crab|mushroom|temple', 1.0),  # magic / landmark glows (not lamps): keep the stock look
        (r'window|glass', 0.12),
        (r'lamp|light|bulb|candle|sconce|chandelier|lantern|illum', 0.20),
        (r'neon|sign|billboard|marquee|poster', 0.45),
        (r'.', 0.2),
    ],
    null_models=[  # storm funnel clouds, fake fog planes, factory smog -> engine's empty model
        'models/clouds/blender/sky_funnelcloud_02.vmdl_c', 'models/clouds/funnelcloud_rings_test01.vmdl_c',
        'models/clouds/blender/sky_funnelcloud_hideout_01.vmdl_c', 'models/clouds/cloudtest_001.vmdl_c',
        'models/clouds/funnelcloud_test01.vmdl_c',
        'models/factory/factory_pollution_cloud_test_01.vmdl_c',
    ],
    null_world_models=r'pollution_cloud|hotel_doorman_sky|campus_smoke_animated',   # map-local world meshes that are invisible in daylight -> empty model (not drawn at all)
    albedo_tint=[  # (regex, multiplier) on g_vColorTint1: tone down very bright surface sets so districts balance
        (r'materials/marble/museum/', 0.72),
    ],
    # Hideout practice hall only (it looked plain next to the spawn room):
    # less flat fill, stronger sun patches, darker corners; mask = sunbake lmbox of the hall's box
    lightmap_regions={'dl_hideout': [(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'mask_hideout_hall.u8'),
                                      dict(fill_gain=0.45, sun_gain=3.2, sky_gamma=1.6, lamp_in=0.75))]},
    texture_grades={  # colour texture -> saturation/gain applied to the texture itself (material vector params don't stick)
        # heavy 'HEAVY' crate + the other tough crate: lighter and more coloured so they pop like the other boxes
        'models/items/materials/crate_tough_2_color_png_223c6656.vtex_c': dict(sat=1.7, gain=1.12),
        'models/items/materials/item_crate_tough_color_tga_571c4dc0.vtex_c': dict(sat=1.7, gain=1.12),
    },
    # gameplay objects (breakables, Sinner's Sacrifice, team-switch orb) keep their original materials/colours
    world_tints={},  # per-draw paint tint {model: {draw index: rgb}} (previews via --extra-world-tints; indices change every map recompile)
    # paint tint (m_vTintColor) of world meshes in worldnodes/n0, matched by the STOCK colour (survives map recompiles):
    # mid-lane stone bridge, stock tan (211,182,139) is used only by its pieces and read gold in sunlight;
    # toned down to a neutral stone
    world_tint_recolor=[((211, 182, 139), (184, 180, 172))],
    material_replace={  # material -> (donor material, param overrides): makes opaque world meshes invisible
        'models/factory/factory_pollution_cloud_01.vmat_c': ('models/architecture/campus_01/campus_smoke_animated_01.vmat_c', {'g_flOpacityScale1': 0.0}),
        'models/backdrop/hotel_doorman/hotel_doorman_sky_01.vmat_c': ('models/architecture/campus_01/campus_smoke_animated_01.vmat_c', {'g_flOpacityScale1': 0.0}),
    },
    material_params={  # exact parameter overrides
        'models/architecture/campus_01/campus_smoke_animated_01.vmat_c': {'g_flOpacityScale1': 0.0},
    },
    sun=dict(color=[255, 241, 222], brightness=3.0, lumens=100000, pitch=52.0, yaw=150.0,
             skycolor=[150, 190, 235], skyintensity=1.0),
    sky='daylock',   # 'daylock' = composed cloudy sky (build_sky.py); 'stock:<material>' = a stock sky material
)

# ---------------------------------------------------------------- looks ---
# Each look is a full build (own sun bake, lighting, sky, colour grade), shipped as its own mod: day and dusk.
# Keys: sun (lightmap+probe sun params, all maps), probes (probe-only), sun_bake {map: dir/az/el}, fog, cubemap,
# sky, vpost_set, lut, emissive_rules, blank_particles, maps {map: {same keys}} (applied after the map's own settings).
_W = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work')
LOOKS = {
    'day': {},   # the original Daylock (v1.1)
    # Issue #1: the old (pre-3-lane) Deadlock late-afternoon look (references: screenshots/ref_dusk): crisp and clear,
    # painted clear sky with a big low sun (build_sky.clear_sky), creamy sunlight, cool blue-grey shade, no haze.
    # Light is baked at az 170 el 30: at el 17 only ~10% of the open lane floor got sun (everything one flat shade);
    # at az 170 el 30 ~21%, evenly over the three lanes, with diagonal shadow edges (sunbake sunscan).
    # The painted sun disc sits lower (el 19, the references' height) so it still shows down the streets.
    'dusk': dict(
        sun_bake={'dl_midtown': dict(dir=os.path.join(_W, 'sun_midtown_az170_el30'), az=170, el=30)},
        sun=dict(sun_gain=3.6, sun_color=(1.00, 0.91, 0.78), sky_gain=1.28, sky_color=(0.70, 0.78, 0.92), sky_gamma=1.35,
                 fill_gain=0.90, fill_color=(0.94, 0.93, 0.93)),   # creamy-white sun, blue-grey shade (refs are cool)
        fog=dict(scale=0.08),                 # less lit fog than Day: clear air
        sky='clear',
        clear_sky=dict(sun_el=19, zenith=(0.082, 0.124, 0.190), horizon=(0.180, 0.178, 0.176)),
        sky_fog_mip_scale=[0.30, 0.32, 0.38],   # the fog samples these blurry sky mips: kept dim -> no haze
        vpost_set={'m_bloomParams.m_flSkyboxBloomStrength': 0.20, 'm_bloomParams.m_flBloomStrength': 0.30},
        lut=dict(contrast=0.32, saturation=1.14, cool_shadows=0.025, warm_highlights=0.02, shadow_lift=0.03, highlight_rolloff=0.30),
    ),
}


def _apply(v, name=None):
    for k in ('lightmap_sun', 'probes_sun'):
        if 'sun' in v: CFG[k] = dict(CFG[k], **v['sun'])
    if 'probes' in v: CFG['probes_sun'] = dict(CFG['probes_sun'], **v['probes'])
    for k in ('fog', 'cubemap'):
        if k in v: CFG[k] = dict(CFG[k], **v[k])
    for m, sb in v.get('sun_bake', {}).items():
        CFG['sun_bake'][m] = dict(CFG['sun_bake'][m], **sb)
    for k in ('sky', 'sky_fog_mip_scale', 'clear_sky', 'emissive_rules', 'blank_particles'):
        if k in v: CFG[k] = v[k]
    if 'vpost_set' in v or 'lut' in v:
        CFG['vpost'] = dict(CFG['vpost'], set=dict(CFG['vpost']['set'], **v.get('vpost_set', {})),
                            lut=dict(CFG['vpost']['lut'], **v.get('lut', {})))
    if name and name in v.get('maps', {}):
        _apply(v['maps'][name])


def apply_variant(look, name=None):
    """name=None: settings for all maps; name=<map>: that map's extra settings (call after the map's own block)"""
    if name is None:
        _apply({k: x for k, x in LOOKS[look].items() if k != 'maps'})
    else:
        _apply(LOOKS[look].get('maps', {}).get(name, {}))


def tex_jobs(name):
    lm = 'maps/%s/lightmaps/' % name
    return {
        'lightmap': lm + 'directional_irradiance_sh2_dc.vtex_c',
        'probes': lm + 'env_light_probe_volume_atlas.vtex_c',
        'fog': lm + 'fog_irradiance_volume.vtex_c',
        'cubemap': 'maps/%s/cubemaps/env_cubemap_array.vtex_c' % name,
    }


TEX_JOBS = tex_jobs(MAPNAME)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


HERE = os.path.dirname(os.path.abspath(__file__))


def cache_key(*parts, code=(), funcs=(), dirs=()):
    """fingerprint of everything a cached stage output depends on: settings, helper module sources,
    converter function sources and input files (size + mtime)"""
    import inspect
    h = hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode())
    for m in code:
        h.update(open(os.path.join(HERE, m), 'rb').read())
    for f in funcs:
        h.update(inspect.getsource(f).encode())
    for d in dirs:
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            st = os.stat(os.path.join(d, fn)); h.update(('%s %d %d' % (fn, st.st_size, st.st_mtime_ns)).encode())
    return h.hexdigest()


def cache_ok(use_cache, paths, key):
    """cached files exist AND were made from the same settings/code/inputs (key file next to the first path)"""
    if not use_cache or not all(os.path.exists(x) for x in paths):
        return False
    try:
        if open(paths[0] + '.key').read() == key:
            return True
    except OSError:
        pass
    log('cache out of date, rebuilding', os.path.basename(paths[0]))
    return False


def cache_mark(path, key):
    open(path + '.key', 'w').write(key)


def convert_texture(raw, params, pool):
    tex = Texture(raw)
    assert tex.format == 'BC6H', tex.format
    px = texio.decode_all_blocks(raw, tex, pool)
    out = np.empty_like(px)
    step = 1 << 20
    for i in range(0, len(px), step):
        out[i:i + step] = daylight.convert(px[i:i + step].astype(np.float32), params).astype(np.float16)
    payload = texio.encode_all_blocks(out, pool)
    return texio.rebuild(raw, tex, payload)


def convert_lightmap_sun(mp, name, params, sb, pool):
    """real-sun daylight for the sh2 lightmap pair -> (dc_raw, lum_raw)"""
    import sunlight, texture2ddecoder
    lm = 'maps/%s/lightmaps/' % name
    raw = mp[lm + 'directional_irradiance_sh2_dc.vtex_c'].read()
    tex = Texture(raw)
    W, H = tex.width, tex.height
    px = texio.decode_all_blocks(raw, tex, pool)                      # (nblocks,16,3)
    def load(n):
        a = np.fromfile(os.path.join(sb['dir'], n + '.u8'), np.uint8).reshape(H, W, 1)
        return texio.img2d_to_blocks(a)                                # (nblocks,16,1)
    vis, ndl, sky = load('vis'), load('ndl'), load('sky')
    vs = float(params.get('vis_sharpen', 0))
    if vs > 0:   # S-curve on sun coverage: shadow edges ~1.5x steeper (edge position kept), texel size is Valve's
        v = vis.astype(np.float32) / 255
        vis = np.clip(np.round((v + (v * v * (3 - 2 * v) - v) * vs) * 255), 0, 255).astype(np.uint8)
    rb = int(params.get('sky_blur', 0))
    if rb > 0:   # sky visibility is traced with few rays -> speckle; coverage-aware box blur (radius rb texels)
        a = np.fromfile(os.path.join(sb['dir'], 'sky.u8'), np.uint8).reshape(H, W).astype(np.float32)
        c = (np.fromfile(os.path.join(sb['dir'], 'cov.u8'), np.uint8).reshape(H, W) > 0).astype(np.float32)
        def box(img):
            k = 2 * rb + 1
            p_ = np.pad(img, rb, mode='edge').cumsum(0).cumsum(1)
            p_ = np.pad(p_, ((1, 0), (1, 0)))
            return p_[k:, k:] - p_[:-k, k:] - p_[k:, :-k] + p_[:-k, :-k]
        sm = box(a * c) / np.maximum(box(c), 1e-3)
        sm = np.where(c > 0, sm, a)
        sky = texio.img2d_to_blocks(np.clip(sm, 0, 255).astype(np.uint8).reshape(H, W, 1))
        log('sky visibility blurred, radius', rb)
    out = np.empty_like(px); share = np.empty(px.shape[:2] + (1,), np.float32)
    step = 1 << 18
    for i in range(0, len(px), step):
        d, s = sunlight.convert(px[i:i + step].astype(np.float32), vis[i:i + step] / 255.0, ndl[i:i + step] / 255.0,
                                sky[i:i + step] / 255.0, params)
        out[i:i + step] = d.astype(np.float16); share[i:i + step] = s
    for mpath, ov in CFG.get('lightmap_regions', {}).get(name, []):   # other lighting settings inside a region
        mk = texio.img2d_to_blocks(np.fromfile(mpath, np.uint8).reshape(H, W, 1))[..., 0] > 0
        rp = dict(params, **ov)
        idx = np.nonzero(mk.any(1))[0]   # blocks that touch the region
        for i in range(0, len(idx), step):
            j = idx[i:i + step]
            d, s = sunlight.convert(px[j].astype(np.float32), vis[j] / 255.0, ndl[j] / 255.0, sky[j] / 255.0, rp)
            m = mk[j][..., None]
            out[j] = np.where(m, d.astype(np.float16), out[j]); share[j] = np.where(m, s, share[j])
        log('lightmap region', os.path.basename(mpath), int(mk.sum()), 'texels', ov)
    for mpath, mul in CFG.get('lightmap_masks', {}).get(name, []):   # local colour fixes (single objects)
        mk = texio.img2d_to_blocks(np.fromfile(mpath, np.uint8).reshape(H, W, 1))[..., 0] > 0
        out[mk] = (out[mk].astype(np.float32) * np.array(mul, np.float32)).astype(np.float16)
        log('lightmap mask', os.path.basename(mpath), int(mk.sum()), 'texels x', mul)
    dc = texio.rebuild(raw, tex, texio.encode_all_blocks(out, pool))
    lraw = mp[lm + 'directional_irradiance_sh2_lum.vtex_c'].read()
    ltex = Texture(lraw)
    bgra = np.frombuffer(texture2ddecoder.decode_bc1(lraw[ltex.pixel_off:], W, H), np.uint8).reshape(H, W, 4)
    enc = bgra[..., [2, 1, 0]]
    share_img = texio.blocks_to_2d(share, W, H)
    L = sunlight.sun_vector(sb['az'], sb['el'])
    new = sunlight.mix_direction(enc, share_img, L, params)
    lum = lraw[:ltex.pixel_off] + sunlight.bc1_encode(new)
    assert len(lum) == len(lraw)
    return dc, lum


def probes_debug(raw, pool):
    """debug: colour each of the 6 probe-atlas slice groups differently (find which group is which direction)"""
    tex = Texture(raw)
    px = texio.decode_all_blocks(raw, tex, pool)
    per = ((tex.width + 3) // 4) * ((tex.height + 3) // 4)
    grp = tex.depth // 6
    cols = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)]   # red green blue yellow magenta cyan
    out = np.empty_like(px)
    for g in range(6):
        out[g * grp * per:(g + 1) * grp * per] = np.array(cols[g], np.float16) * np.float16(0.6)
    return texio.rebuild(raw, tex, texio.encode_all_blocks(out, pool))


def replace_data_block(raw, new_data, block='DATA'):
    """Return a resource file with one block (DATA by default) replaced (other blocks kept, offsets re-laid out)."""
    r = Resource(raw)
    names = [b[0] for b in r.blocks]
    if names[-1] == block:
        t, off, size = r.blocks[-1]
        out = bytearray(raw[:off]) + new_data
        boff = struct.unpack_from('<I', raw, 8)[0]
        pos = 8 + boff + 12 * (len(r.blocks) - 1)
        struct.pack_into('<I', out, pos + 8, len(new_data))
        struct.pack_into('<I', out, 0, len(out))
        return bytes(out)
    # general case: rebuild header, block table and blocks
    header_ver, ver = struct.unpack_from('<HH', raw, 4)
    blocks = [(t, new_data if t == block else raw[o:o + s]) for t, o, s in r.blocks]
    n = len(blocks)
    table_start = 16
    pos = table_start + 12 * n
    layout = []
    for i, (t, data) in enumerate(blocks):
        if i > 0:
            pos = (pos + 15) // 16 * 16
        layout.append(pos)
        pos += len(data)
    out = bytearray(pos)
    struct.pack_into('<IHHII', out, 0, pos, header_ver, ver, 8, n)
    for i, (t, data) in enumerate(blocks):
        e = table_start + 12 * i
        out[e:e + 4] = t.encode()
        struct.pack_into('<II', out, e + 4, layout[i] - (e + 4), len(data))
        out[layout[i]:layout[i] + len(data)] = data
    return bytes(out)


def blank_particle(raw):
    """Same particle system, but it never emits or draws anything."""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    for key in ('m_Emitters', 'm_Renderers', 'm_Children', 'm_Initializers', 'm_Operators', 'm_ForceGenerators', 'm_Constraints'):
        if root.get(key) is not None:
            root.set(key, kv3t.A(kv3t.ARRAY, 0, []))
    root.set('m_nMaxParticles', kv3t.S(kv3t.INT32, 0, 0))
    root.set('m_nInitialParticles', kv3t.S(kv3t.INT32, 0, 0))
    return replace_data_block(raw, kv3t.write(guid, root))


def graded_lut(dim, contrast, saturation, cool_shadows, warm_highlights, shadow_lift=0.0, highlight_rolloff=0.0):
    """32^3 RGBA8 colour-correction table (index [b][g][r]): S-curve contrast, saturation, split toning."""
    i = np.arange(dim) / (dim - 1)
    b, g, r = np.meshgrid(i, i, i, indexing='ij')
    c = np.stack([r, g, b], -1)
    c = c + shadow_lift * c * (1 - c) ** 2          # open up darks/mids, highlights untouched
    c = c - highlight_rolloff * np.clip(c - 0.55, 0, None) ** 2   # soften very bright surfaces (white marble)
    sm = c * c * (3 - 2 * c)
    c = c + (sm - c) * contrast
    lum = (c * np.array([0.2126, 0.7152, 0.0722])).sum(-1, keepdims=True)
    c = lum + (c - lum) * saturation
    c = c + (1 - lum) * np.array([-0.5, 0.0, 1.0]) * cool_shadows + lum * np.array([1.0, 0.5, -0.5]) * warm_highlights
    out = np.empty(c.shape[:-1] + (4,), np.uint8)
    out[..., :3] = np.clip(np.round(np.clip(c, 0, 1) * 255), 0, 255)
    out[..., 3] = 255
    return out.tobytes()


def edit_vpost(raw, changes, lut=None):
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    if lut:
        dim = root.get('m_nColorCorrectionVolumeDim').v
        old = root.get('m_colorCorrectionVolumeData')
        root.set('m_colorCorrectionVolumeData', kv3t.S(old.t, old.flag, graded_lut(dim, **lut)))
        root.set('m_bHasColorCorrection', kv3t.S(kv3t.BOOLEAN_TRUE, 0, True))
    for path, val in changes.items():
        grp, key = path.split('.')
        g = root.get(grp)
        old = g.get(key)
        g.set(key, kv3t.S(old.t if old is not None and old.t in (kv3t.FLOAT, kv3t.DOUBLE) else kv3t.FLOAT, old.flag if old else 0, float(val)))
    return replace_data_block(raw, kv3t.write(guid, root))


GLOW_PARAM = re.compile(r'SelfIllumScale|EmissiveLevel|LayerSelfIllumScale|SelfIllumBrightness', re.I)


def dim_material(raw, factor):
    """Multiply every glow strength parameter of a compiled material; returns None if nothing glows."""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    fp = root.get('m_floatParams')
    changed = False
    for item in (fp.items if fp is not None else []):
        name = item.get('m_name').v
        val = item.get('m_flValue')
        if GLOW_PARAM.search(name) and val.v > 0:
            item.set('m_flValue', kv3t.S(val.t, val.flag, float(val.v) * factor))
            changed = True
    return replace_data_block(raw, kv3t.write(guid, root)) if changed else None


def set_material_params(raw, params):
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    for item in root.get('m_floatParams').items:
        name = item.get('m_name').v
        if name in params:
            val = item.get('m_flValue')
            item.set('m_flValue', kv3t.S(val.t, val.flag, float(params[name])))
    return replace_data_block(raw, kv3t.write(guid, root))


FOG_CLASSES = {
    'env_volumetric_fog_volume': {'FogStrength': 0.0},
    'env_volumetric_fog_controller': {'FogStrength': 0.0},
    'env_gradient_fog': {'fogstrength': 0.0, 'fogmaxopacity': 0.0},
    'env_cubemap_fog': {},
}


def disable_fog_entities(raw):
    """Turn off every fog entity in an entity lump (strength 0 + StartDisabled)."""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    n = 0
    for e in root.get('m_entityKeyValues').items:
        kv = e.get('keyValues3Data')
        if kv is None:
            continue
        vals = kv.get('values') or kv
        cls = vals.get('classname')
        if cls is None or cls.v not in FOG_CLASSES:
            continue
        for key, v in FOG_CLASSES[cls.v].items():
            old = vals.get(key)
            if old is not None:
                vals.set(key, kv3t.S(old.t if old.t in (kv3t.FLOAT, kv3t.DOUBLE) else kv3t.DOUBLE, old.flag, v))
        vals.set('StartDisabled', kv3t.S(kv3t.BOOLEAN_TRUE, 0, True))
        n += 1
    log('fog entities disabled:', n)
    return replace_data_block(raw, kv3t.write(guid, root))


def tint_material(raw, mult):
    """Multiply the albedo tint (g_vColorTint1) of a compiled material, adding the parameter if missing."""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    vp = root.get('m_vectorParams')
    if vp is None or not vp.items:
        return None
    target = None
    for item in vp.items:
        if item.get('m_name').v == 'g_vColorTint1':
            target = item
    if target is None:
        # deep-copy an existing vector param entry and turn it into g_vColorTint1 = white
        g2, target = kv3t.read(kv3t.write(guid, vp.items[0], compress=False))
        target.set('m_name', kv3t.S(kv3t.STRING, 0, 'g_vColorTint1'))
        val = target.get('m_value')
        val.items = [1.0, 1.0, 1.0, 0.0]
        vp.items.append(target)
    val = target.get('m_value')
    mm = mult if isinstance(mult, (tuple, list)) else (mult, mult, mult)
    val.items = [float(x) * k for x, k in zip(val.items[:3], mm)] + list(val.items[3:])
    return replace_data_block(raw, kv3t.write(guid, root))


def set_world_tints(raw, tints):
    """worldnode (.vwnod_c): set m_vTintColor of chosen draw calls of aggregate meshes. tints = {model suffix: {draw: rgb}}"""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    n = 0
    for ag in root.get('m_aggregateSceneObjects').items:
        model = ag.get('m_renderableModel').v
        for suffix, draws in tints.items():
            if not model.endswith(suffix):
                continue
            for m in ag.get('m_aggregateMeshes').items:
                d = m.get('m_nDrawCallIndex').v
                if d in draws:
                    t = m.get('m_vTintColor'); t.items = [int(x) for x in draws[d]] + list(t.items[3:]); n += 1
    return (replace_data_block(raw, kv3t.write(guid, root)) if n else None), n


def recolor_world_tints(raw, pairs):
    """worldnode (.vwnod_c): every aggregate draw whose m_vTintColor is exactly a stock rgb gets the new rgb"""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    n = 0
    for ag in root.get('m_aggregateSceneObjects').items:
        for m in ag.get('m_aggregateMeshes').items:
            t = m.get('m_vTintColor')
            for old, new in pairs:
                if tuple(int(x) for x in t.items[:3]) == tuple(old):
                    t.items = [int(x) for x in new] + list(t.items[3:]); n += 1
                    break
    return (replace_data_block(raw, kv3t.write(guid, root)) if n else None), n


def add_rerl_ref(raw, name):
    """append an external reference (resource name) to a compiled resource's RERL block"""
    import murmur
    r = Resource(raw)
    _, off, size = r.block('RERL')
    blk = raw[off:off + size]
    eoff, cnt = struct.unpack_from('<ii', blk, 0)
    ents = []
    for i in range(cnt):
        e = 8 + i * 16 if eoff == 8 else eoff + i * 16
        rid, noff = struct.unpack_from('<Qq', blk, e)
        p = e + 8 + noff; q = blk.index(b'\0', p)
        ents.append((rid, blk[p:q]))
    if any(n == name.encode() for _, n in ents):
        return raw
    ents.append((murmur.resource_id(name), name.encode()))
    n = len(ents); out = bytearray(struct.pack('<ii', 8, n)); names = b''
    name_pos = []
    base = 8 + 16 * n
    for rid, nm in ents:
        name_pos.append(base + len(names)); names += nm + b'\0'
    for i, (rid, nm) in enumerate(ents):
        e = 8 + 16 * i
        out += struct.pack('<Qq', rid, name_pos[i] - (e + 8))
    out += names
    return replace_data_block(raw, bytes(out), 'RERL')


def material_copy(raw, new_name, vectors):
    """copy of a compiled material under a new name with some vector params changed (layer tints etc.)"""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    mn = root.get('m_materialName'); root.set('m_materialName', kv3t.S(mn.t, mn.flag, new_name))
    for item in root.get('m_vectorParams').items:
        nm = item.get('m_name').v
        if nm in vectors:
            val = item.get('m_value'); val.items = [float(x) for x in vectors[nm][:3]] + list(val.items[3:])
    return replace_data_block(raw, kv3t.write(guid, root))


def set_mesh_material(raw, draws, new_mat):
    """map-local mesh: point chosen draw calls (MDAT m_drawCalls[i].m_material) at another material"""
    r = Resource(raw)
    _, off, size = r.block('MDAT')
    guid, root = kv3t.read(raw[off:off + size])
    n = 0
    for so in root.get('m_sceneObjects').items:
        for i, dc in enumerate(so.get('m_drawCalls').items):
            if i in draws:
                m = dc.get('m_material'); dc.set('m_material', kv3t.S(m.t, m.flag, new_mat)); n += 1
    return add_rerl_ref(replace_data_block(raw, kv3t.write(guid, root), 'MDAT'), new_mat), n


def set_mesh_tints(raw, draws):
    """map-local mesh (.vmdl_c): multiply colour of chosen draw calls via MDAT m_drawCalls[i].m_vTintColor. draws = {i: rgb}"""
    r = Resource(raw)
    _, off, size = r.block('MDAT')
    guid, root = kv3t.read(raw[off:off + size])
    n = 0
    for so in root.get('m_sceneObjects').items:
        for i, dc in enumerate(so.get('m_drawCalls').items):
            if i in draws:
                t = dc.get('m_vTintColor'); t.items = [float(x) for x in draws[i]]; n += 1
    return replace_data_block(raw, kv3t.write(guid, root), 'MDAT'), n


def set_vector_param(raw, name, values):
    """Set an existing vector parameter (first 3 components) of a compiled material; None if it doesn't have it."""
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    vp = root.get('m_vectorParams')
    if vp is None:
        return None
    for item in vp.items:
        if item.get('m_name').v == name:
            val = item.get('m_value')
            val.items = [float(x) for x in values[:3]] + list(val.items[3:])
            return replace_data_block(raw, kv3t.write(guid, root))
    return None


def S(t, v, flag=0):
    return kv3t.S(t, flag, v)


def edit_entities(raw, cfg):
    r = Resource(raw)
    _, off, size = r.block('DATA')
    guid, root = kv3t.read(raw[off:off + size])
    ents = root.get('m_entityKeyValues')
    added = 0
    for e in list(ents.items):
        kv = e.get('keyValues3Data')
        if kv is None:
            continue
        vals = kv.get('values') or kv
        cls = vals.get('classname')
        if cls is not None and cls.v == 'env_sky' and cfg.get('debug_sky_tint'):
            vals.set('tint_color', kv3t.A(kv3t.ARRAY_TYPED, 0, [255, 0, 0], kv3t.UINT32, 0))
            log('DEBUG: env_sky tinted red')
        if cls is None or cls.v != 'light_environment':
            continue
        # deep copy by round-tripping this entity through the writer
        g2, clone = kv3t.read(kv3t.write(guid, e, compress=False))
        cv = clone.get('keyValues3Data')
        cv = cv.get('values') or cv
        sun = cfg['sun']
        # same KV3 value types the original light_environment uses
        cv.set('brightness', S(kv3t.DOUBLE, float(sun['brightness'])))
        # the map's sun has brightness_legacy = NaN; set every intensity field consistently
        cv.set('brightness_legacy', S(kv3t.STRING, '%g' % (2.0 ** float(sun['brightness']))))
        cv.set('brightness_lumens', S(kv3t.STRING, '%g' % sun.get('lumens', 100000)))
        cv.set('brightnessscale', S(kv3t.DOUBLE, 1.0))
        cv.set('color', kv3t.A(kv3t.ARRAY_TYPED, 0, [int(x) for x in sun['color']], kv3t.UINT32, 0))
        cv.set('castshadows', S(kv3t.INT64_ONE, 1))
        cv.set('directlight', S(kv3t.INT32, 2))
        cv.set('angles', kv3t.A(kv3t.ARRAY_TYPED, 0, [float(sun['pitch']), float(sun['yaw']), 0.0], kv3t.DOUBLE, 0))
        cv.set('skycolor', kv3t.A(kv3t.ARRAY_TYPED, 0, [int(x) for x in sun['skycolor']], kv3t.UINT32, 0))
        cv.set('skyintensity', S(kv3t.DOUBLE, float(sun['skyintensity'])))
        mode = cfg.get('sun_mode', 'clone')
        if mode == 'replace':
            # edit the original (networked) light in place: only affects offline/local servers
            e.items[:] = clone.items
            added += 1
            continue
        cv.set('clientSideEntity', S(kv3t.STRING, '1'))
        cv.set('targetname', S(kv3t.STRING, 'daylock_sun'))
        cv.set('hammerUniqueId', S(kv3t.STRING, 'daylock:1'))
        if mode == 'clone_only':
            ents.items.remove(e)
        ents.items.append(clone)
        added += 1
    log('entities: sun mode', cfg.get('sun_mode', 'clone'), 'suns', added)
    return replace_data_block(raw, kv3t.write(guid, root))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work')
    ap.add_argument('--map', default='dl_midtown')
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--only', default='lightmap,probes,fog,cubemap,ents,sky,particles')
    ap.add_argument('--cache', action='store_true', help='reuse converted textures from a previous run')
    ap.add_argument('--debug-sky-tint', action='store_true')
    ap.add_argument('--fog-entities-off', action='store_true')
    ap.add_argument('--mat-debug', default=None, help='material=donor,... (debug: swap materials with visible donors)')
    ap.add_argument('--sky-fog-mip-scale', type=float, default=None)
    ap.add_argument('--fog-classes', default=None, help='comma list of fog classes to disable (test)')
    ap.add_argument('--sun-color', default=None, help='r,g,b')
    ap.add_argument('--sun-brightness', type=float, default=None)
    ap.add_argument('--probe-debug', action='store_true')
    ap.add_argument('--no-sun', action='store_true', help='old look: no ray-traced sun')
    ap.add_argument('--extra-world-tints', default=None, help='json {model: {draw: rgb}} merged into CFG world_tints (previews)')
    ap.add_argument('--cubemap-scale', type=float, default=None, help='override CFG cubemap scale (reflection brightness)')
    ap.add_argument('--sun-params', default=None, help='k=v,... overrides for sunlight params (forces lightmap rebuild)')
    ap.add_argument('--sun-mode', default=None, choices=['none', 'clone', 'replace', 'clone_only'])
    ap.add_argument('--look', default='day', choices=sorted(LOOKS), help='lighting look (see LOOKS)')
    ap.add_argument('--debug-sky-dirs', action='store_true', help='painted sky shows directions (red +x, green +y, blue up)')
    a = ap.parse_args()
    only = set(a.only.split(','))
    tag = a.look
    apply_variant(a.look)
    if a.debug_sky_dirs: CFG['debug_sky_dirs'] = True
    if a.sun_mode: CFG['sun_mode'] = a.sun_mode
    CFG.setdefault('sun_mode', 'none')
    if a.debug_sky_tint: CFG['debug_sky_tint'] = True
    if a.probe_debug: CFG['probe_debug'] = True
    if a.no_sun: CFG['use_sun'] = False
    if a.sun_params:
        ov = {k: float(v) for k, v in (kv.split('=') for kv in a.sun_params.split(','))}
        CFG['lightmap_sun'] = dict(CFG['lightmap_sun'], **ov); CFG['probes_sun'] = dict(CFG['probes_sun'], **ov)
        CFG['sun_force'] = True
    if a.extra_world_tints:
        wt = {m: dict(d) for m, d in CFG.get('world_tints', {}).items()}
        for m, d in json.load(open(a.extra_world_tints)).items():
            wt.setdefault(m, {}).update({int(k): v for k, v in d.items()})
        CFG['world_tints'] = wt
    if a.cubemap_scale is not None: CFG['cubemap'] = dict(CFG['cubemap'], scale=a.cubemap_scale)
    if a.fog_entities_off: CFG['fog_entities_off'] = True
    if a.mat_debug:
        for pair in a.mat_debug.split(','):
            m, donor = pair.split('=')
            CFG['material_replace'][m] = (donor, {})
    if a.sky_fog_mip_scale is not None: CFG['sky_fog_mip_scale'] = [a.sky_fog_mip_scale] * 3
    if a.fog_classes:
        CFG['fog_entities_off'] = True
        keep = set(a.fog_classes.split(','))
        for k in list(FOG_CLASSES):
            if k not in keep: del FOG_CLASSES[k]
    if a.sun_color: CFG['sun']['color'] = [int(x) for x in a.sun_color.split(',')]
    if a.sun_brightness is not None: CFG['sun']['brightness'] = a.sun_brightness
    name = a.map
    if name == 'dl_hideout':  # interior map: a bit more daylight fill, and no fog at all (local-only map)
        for k in ('lightmap', 'probes'):
            CFG[k] = dict(CFG[k], fill_gain=0.62, floor=0.07)
        # training area / rooms: keep more of the bake's own light pools + warm lamps so interiors aren't flat
        hide = dict(lamp_in=0.45, fill_ref=0.30, fill_gain=0.65)
        hide = {k: v for k, v in hide.items() if not (a.sun_params and k + '=' in a.sun_params)}   # --sun-params wins
        CFG['lightmap_sun'] = dict(CFG['lightmap_sun'], **hide); CFG['probes_sun'] = dict(CFG['probes_sun'], **hide)
        CFG['fog'] = dict(CFG['fog'], scale=0.0)
        CFG['fog_entities_off'] = True
        CFG['material_params'] = dict(CFG['material_params'], **{'models/base/blockout/blockout_glow_01.vmat_c': {'g_flOpacityScale1': 0.0}})
    apply_variant(a.look, name)
    map_path = os.path.join(GAME, 'maps', name + '.vpk')
    jobs = tex_jobs(name)
    sfx = '' if tag == 'day' else '_' + tag   # each look keeps its own cache + output ('day' = the original paths)
    stage_shared = os.path.join(a.work, 'stage' + sfx)
    stage = stage_shared if name == 'dl_midtown' else os.path.join(a.work, 'stage_' + name + sfx)
    outdir = os.path.join(a.work, 'out' + sfx)
    os.makedirs(stage, exist_ok=True); os.makedirs(stage_shared, exist_ok=True); os.makedirs(outdir, exist_ok=True)
    mp = vpk.open(map_path)
    map_sig = (os.path.getsize(map_path), os.stat(map_path).st_mtime_ns)
    replaced = {}
    from multiprocessing import Pool
    pool = Pool(max(1, min(8, (os.cpu_count() or 4) - 2)))
    try:
        sb = CFG.get('sun_bake', {}).get(name) if CFG.get('use_sun', True) else None
        if sb and 'lightmap' in only:
            lumpath = 'maps/%s/lightmaps/directional_irradiance_sh2_lum.vtex_c' % name
            cdc, clum = os.path.join(stage, 'sun', jobs['lightmap']), os.path.join(stage, 'sun', lumpath)
            key = cache_key(CFG['lightmap_sun'], sb, CFG.get('lightmap_masks'), CFG.get('lightmap_regions'), map_sig,
                            code=('sunlight.py', 'daylight.py'), funcs=(convert_lightmap_sun,), dirs=(sb['dir'],))
            if CFG.get('sun_force') or not cache_ok(a.cache, (cdc, clum), key):
                log('converting lightmap with baked sun', sb)
                dc, lum = convert_lightmap_sun(mp, name, CFG['lightmap_sun'], sb, pool)
                for pth, data in ((cdc, dc), (clum, lum)):
                    os.makedirs(os.path.dirname(pth), exist_ok=True); open(pth, 'wb').write(data)
                cache_mark(cdc, key)
            replaced[jobs['lightmap']] = open(cdc, 'rb').read(); replaced[lumpath] = open(clum, 'rb').read()
        for job, path in jobs.items():
            if job == 'lightmap' and sb:
                continue
            cache = os.path.join(stage, path)
            if job == 'probes' and sb and job in only and not CFG.get('probe_debug'):
                pc = os.path.join(stage, 'sun', path)
                key = cache_key(CFG['probes_sun'], CFG['probes'], sb, map_sig,
                                code=('probes_sun.py', 'sunlight.py', 'daylight.py'), dirs=(sb['dir'],))
                if CFG.get('sun_force') or not cache_ok(a.cache, (pc,), key):
                    import probes_sun
                    data, n, mv = probes_sun.convert(mp[path].read(), mp, name, CFG['probes_sun'], sb, os.path.join(a.work, 'sun_probes'), pool, CFG['probes'])
                    os.makedirs(os.path.dirname(pc), exist_ok=True); open(pc, 'wb').write(data)
                    cache_mark(pc, key)
                    log('probes: baked sun for', n, 'probes, mean sun visibility', round(mv, 3))
                replaced[path] = open(pc, 'rb').read(); continue
            if job == 'probes' and CFG.get('probe_debug') and job in only:
                replaced[path] = probes_debug(mp[path].read(), pool); log('probes: DEBUG colours'); continue
            key = cache_key(CFG[job], map_sig, code=('daylight.py',), funcs=(convert_texture,))
            if job in only and not cache_ok(a.cache, (cache,), key):
                log('converting', job, path)
                data = convert_texture(mp[path].read(), CFG[job], pool)
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                open(cache, 'wb').write(data)
                cache_mark(cache, key)
            if os.path.exists(cache) and job in only:
                replaced[path] = open(cache, 'rb').read()
    finally:
        pool.close()
    if 'ents' in only and (CFG['sun_mode'] != 'none' or CFG.get('debug_sky_tint')):
        p = 'maps/%s/entities/default_ents.vents_c' % name
        replaced[p] = edit_entities(mp[p].read(), CFG)
    if CFG.get('fog_entities_off'):
        p = 'maps/%s/entities/default_ents.vents_c' % name
        replaced[p] = disable_fog_entities(replaced.get(p) or mp[p].read())
    pk = vpk.open(PAK)
    if 'sky' in only and CFG['sky'].startswith('stock:'):
        import build_sky
        smat = CFG['sky'].split(':', 1)[1]
        tp = build_sky.tex_path(pk, smat)
        cache = os.path.join(stage_shared, 'sky_stock.vtex_c')
        key = cache_key(smat, CFG.get('sky_fog_mip_scale'), CFG.get('sky_fog_mip_max', 128), (os.path.getsize(PAK), os.stat(PAK).st_mtime_ns),
                        code=('build_sky.py',))
        if not cache_ok(a.cache, (cache,), key):   # same fog-haze fix as the Daylock sky: darker blurry mips
            sraw = pk[tp].read(); stex = Texture(sraw)
            open(cache, 'wb').write(build_sky.encode_cube(sraw, stex, build_sky.cube_mip0(sraw, stex),
                                                          CFG.get('sky_fog_mip_scale'), CFG.get('sky_fog_mip_max', 128)))
            cache_mark(cache, key)
        replaced[tp] = open(cache, 'rb').read()
        sky = pk[smat].read()
        for sk in SKY_NAMES:
            replaced['materials/skybox/%s.vmat_c' % sk] = sky
        log('sky -> stock', smat)
    elif 'sky' in only and CFG['sky'] == 'clear':   # painted clear sky (Dusk), in the quarry texture slot
        import build_sky
        qraw = pk[build_sky.tex_path(pk, build_sky.QUARRY_MAT)].read(); qtex = Texture(qraw)
        cp = dict(build_sky.CLEAR, **CFG.get('clear_sky', {}))
        sb = CFG['sun_bake'].get('dl_midtown', {})
        cp.setdefault('sun_az', sb.get('az', 180)); cp.setdefault('sun_el', sb.get('el', 25))
        cache = os.path.join(stage_shared, 'sky_clear.vtex_c')
        key = cache_key(cp, CFG.get('debug_sky_dirs'), CFG.get('sky_fog_mip_scale'), CFG.get('sky_fog_mip_max', 128),
                        (os.path.getsize(PAK), os.stat(PAK).st_mtime_ns), code=('build_sky.py',))
        if not cache_ok(a.cache, (cache,), key):
            faces = build_sky.clear_sky(qtex.width, cp, debug_dirs=CFG.get('debug_sky_dirs', False))
            # fog mips: same sky without the sun disc and with a weak glow (no sun haze on buildings in front of it)
            fog_faces = None if CFG.get('debug_sky_dirs') else build_sky.clear_sky(
                qtex.width, dict(cp, sun_radius=-1.0, glow_level=cp['glow_level'] * 0.3, halo_level=cp['halo_level'] * 0.5))
            open(cache, 'wb').write(build_sky.encode_cube(qraw, qtex, faces, CFG.get('sky_fog_mip_scale'), CFG.get('sky_fog_mip_max', 128),
                                                          fog_faces=fog_faces))
            cache_mark(cache, key)
            log('sky: painted clear sky', 'DEBUG DIRECTIONS' if CFG.get('debug_sky_dirs') else '')
        replaced[build_sky.tex_path(pk, build_sky.QUARRY_MAT)] = open(cache, 'rb').read()
        sky = pk[CFG['sky_material']].read()
        for sk in SKY_NAMES:
            replaced['materials/skybox/%s.vmat_c' % sk] = sky
    elif 'sky' in only:
        import build_sky
        cache = os.path.join(stage_shared, 'sky_cube.vtex_c')
        key = cache_key(CFG.get('sky_fog_mip_scale'), CFG.get('sky_fog_mip_max', 128), (os.path.getsize(PAK), os.stat(PAK).st_mtime_ns),
                        code=('build_sky.py',))
        if not cache_ok(a.cache, (cache,), key):
            qraw, qtex, faces, k = build_sky.compose(pk)
            open(cache, 'wb').write(build_sky.encode_cube(qraw, qtex, faces, CFG.get('sky_fog_mip_scale'), CFG.get('sky_fog_mip_max', 128)))
            cache_mark(cache, key)
            log('sky: composed cloudy sky, quarry scale', round(float(k), 3))
        replaced[build_sky.tex_path(pk, build_sky.QUARRY_MAT)] = open(cache, 'rb').read()
        sky = pk[CFG['sky_material']].read()
        for sk in SKY_NAMES:
            replaced['materials/skybox/%s.vmat_c' % sk] = sky
        log('sky ->', CFG['sky_material'])
    if 'particles' in only:
        for p in CFG['blank_particles']:
            src = mp if p in mp else pk
            if p in src:
                replaced[p] = blank_particle(src[p].read())
        null = pk['models/null.vmdl_c'].read()
        for p in CFG['null_models']:
            replaced[p] = null
        for p in mp:
            if p.endswith('.vmdl_c') and re.search(CFG['null_world_models'], p):
                replaced[p] = null; log('hid world mesh', p)
        for new_mat, spec in CFG.get('material_copies', {}).items():
            src_mat = spec['from'] + '_c'
            replaced[new_mat + '_c'] = material_copy((mp if src_mat in mp else pk)[src_mat].read(), new_mat, spec.get('vectors', {}))
            for model, draws in spec['draws'].items():
                mpth = 'maps/%s/worldnodes/%s_c' % (name, model)
                if mpth in mp:
                    replaced[mpth], n = set_mesh_material(replaced.get(mpth) or mp[mpth].read(), set(draws), new_mat)
                    log('material copy', new_mat, 'on', n, 'draws of', model)
        for model, draws in CFG.get('mesh_tints', {}).items():
            mpth = 'maps/%s/worldnodes/%s_c' % (name, model)
            if mpth in mp:
                replaced[mpth], n = set_mesh_tints(replaced.get(mpth) or mp[mpth].read(), draws)
                log('mesh tint on', n, 'draws of', model)
        if CFG.get('world_tints') and name == 'dl_midtown':   # draw indices are Midtown's
            wn = 'maps/%s/worldnodes/n0.vwnod_c' % name
            if wn in mp:
                out, n = set_world_tints(replaced.get(wn) or mp[wn].read(), CFG['world_tints'])
                if out is not None:
                    replaced[wn] = out
                log('world tint on', n, 'draws')
        if CFG.get('world_tint_recolor') and name == 'dl_midtown':
            wn = 'maps/%s/worldnodes/n0.vwnod_c' % name
            if wn in mp:
                out, n = recolor_world_tints(replaced.get(wn) or mp[wn].read(), CFG['world_tint_recolor'])
                if out is not None:
                    replaced[wn] = out
                log('world tint recolour on', n, 'draws')
        n_tint = 0
        for m in sorted(scan_emissive.map_materials(mp, pk)):
            for rx, mult in CFG.get('albedo_tint', []):
                if re.search(rx, m):
                    src = mp if m in mp else pk
                    base = replaced.get(m) or src[m].read()
                    out = tint_material(base, mult)
                    if out is not None:
                        replaced[m] = out; n_tint += 1
                    break
        for m, mult in CFG.get('albedo_tint_exact', {}).items():
            src = mp if m in mp else pk
            if m in src:
                out = tint_material(replaced.get(m) or src[m].read(), mult)
                if out is not None:
                    replaced[m] = out; n_tint += 1
        for m, csb in CFG.get('albedo_csb', {}).items():
            src = mp if m in mp else pk
            if m in src:
                out = set_vector_param(replaced.get(m) or src[m].read(), 'g_vAlbedoContrastSaturationBrightness1', csb)
                if out is not None:
                    replaced[m] = out; n_tint += 1
        log('albedo-tinted', n_tint, 'materials')
        if CFG.get('texture_grades'):
            import texgrade
            for tp, g in CFG['texture_grades'].items():
                cache = os.path.join(stage_shared, 'graded', tp)
                key = cache_key(g, (os.path.getsize(PAK), os.stat(PAK).st_mtime_ns), code=('texgrade.py',))
                if not cache_ok(a.cache, (cache,), key):
                    data = texgrade.grade_texture(pk[tp].read(), **g)
                    os.makedirs(os.path.dirname(cache), exist_ok=True); open(cache, 'wb').write(data); cache_mark(cache, key)
                replaced[tp] = open(cache, 'rb').read()
            log('graded', len(CFG['texture_grades']), 'textures')
        for m, (donor, params) in CFG.get('material_replace', {}).items():
            replaced[m] = set_material_params(pk[donor].read(), params)
            log('replaced material', m, 'with invisible', donor)
        for m, params in CFG['material_params'].items():
            src = mp if m in mp else pk
            if m in src:
                replaced[m] = set_material_params(src[m].read(), params)

        n_dim = 0
        for m in sorted(scan_emissive.map_materials(mp, pk)):
            f = next(f for rx, f in CFG['emissive_rules'] if re.search(rx, m))
            if f == 1.0:
                continue
            src = mp if m in mp else pk
            try:
                out = dim_material(src[m].read(), f)
            except (KeyError, Exception):
                continue
            if out is not None:
                replaced[m] = out; n_dim += 1
        log('dimmed glow on', n_dim, 'materials')
        for p in CFG['vpost']['files']:
            replaced[p] = edit_vpost(pk[p].read(), CFG['vpost']['set'], CFG['vpost'].get('lut'))
        log('blanked', len(CFG['blank_particles']), 'particle systems,', len(CFG['null_models']), 'storm models')
    files = {p: from_vpk(mp, p) for p in mp}
    files.update(replaced)
    out = os.path.join(outdir, name + '.vpk')
    n = write_vpk(out + '.tmp', files)
    os.replace(out + '.tmp', out)
    src_hash = hashlib.md5(open(map_path, 'rb').read(1 << 20)).hexdigest() + '_%d' % os.path.getsize(map_path)
    json.dump(dict(source_map_signature=src_hash, built=time.ctime(), look=a.look, replaced=sorted(replaced), cfg=CFG),
              open(os.path.join(outdir, 'build_info.json' if name == 'dl_midtown' else 'build_info_%s.json' % name), 'w'), indent=1, default=str)
    log('wrote', out, n, 'files', os.path.getsize(out) // (1 << 20), 'MB; replaced:', len(replaced))
    if a.install:
        dst = os.path.join(GAME, 'addons', 'maps')
        os.makedirs(dst, exist_ok=True)
        shutil.copyfile(out, os.path.join(dst, name + '.vpk'))
        log('installed to', dst)


if __name__ == '__main__':
    main()
