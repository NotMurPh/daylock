"""Compose the Daylock sky: real cumulus clouds (light_test_quarry HDRI) above the horizon,
blended into the clean Hosek-Wilkie clear-sky haze at/below the horizon (hides the quarry ground).
Output: a replacement for the quarry cubemap texture (same header/size/mips), used via the quarry material.
"""
import numpy as np
from s2res import Texture, rerl
import bc6h

QUARRY_MAT = 'materials/skybox/light_test_quarry.vmat_c'
HOSEK_MAT = 'materials/skybox/skymodel_hosekwilkie_ref/skymodel_hosekwilkie_albedo_0_30_turbidity_02_0_elevation_45_0.vmat_c'
QUARRY_BIAS = 2.0 ** 0.9  # g_flBrightnessExposureBias of the quarry material

# which edge of each side face points to the zenith (worked out from the clear-sky model)
UP_EDGE = {0: 'left', 1: 'right', 2: 'bottom', 3: 'top'}

DEFAULT = dict(blend_lo=1.5, blend_hi=9.0, sun_cap=40.0, target_ratio=1.0, cloud_saturation=1.0)


def tex_path(pak, mat):
    return [r for r in rerl(pak[mat].read()) if r.endswith('.vtex')][0] + '_c'


def cube_mip0(raw, tex):
    bw = tex.width // 4
    fs = bw * bw * 16
    start = len(raw) - 6 * fs
    faces = []
    for f in range(6):
        px, _ = bc6h.decode(raw[start + f * fs:start + (f + 1) * fs])
        faces.append(bc6h.blocks_to_image(px, bw, bw).astype(np.float32))
    return faces


def elevation(face, n):
    c = (np.arange(n) + 0.5) / n * 2 - 1
    s, t = np.meshgrid(c, c)  # s: column (left->right), t: row (top->bottom)
    if face == 4:
        return np.degrees(np.arctan2(1.0, np.sqrt(s * s + t * t)))
    if face == 5:
        return -np.degrees(np.arctan2(1.0, np.sqrt(s * s + t * t)))
    up = {'left': -s, 'right': s, 'bottom': t, 'top': -t}[UP_EDGE[face]]
    across = t if UP_EDGE[face] in ('left', 'right') else s
    return np.degrees(np.arctan2(up, np.sqrt(1 + across * across)))


def upsample(img, n):
    m = img.shape[0]
    if m == n:
        return img
    idx = (np.arange(n) + 0.5) * m / n - 0.5
    i0 = np.clip(np.floor(idx).astype(int), 0, m - 1); i1 = np.clip(i0 + 1, 0, m - 1); f = (idx - i0)[:, None]
    rows = img[i0] * (1 - f[:, :, None]) + img[i1] * f[:, :, None]
    cols = rows[:, i0] * (1 - f[None, :, :].transpose(0, 1, 2).reshape(1, n, 1)) + rows[:, i1] * f.reshape(1, n, 1)
    return cols


def compose(pak, p=DEFAULT, style='anime'):
    qraw = pak[tex_path(pak, QUARRY_MAT)].read(); qtex = Texture(qraw)
    if style == 'anime':
        Q = [np.minimum(q, 30) for q in cube_mip0(qraw, qtex)]
        E = [elevation(f, qtex.width) for f in range(6)]
        return qraw, qtex, stylize(Q, E), 1.0
    hraw = pak[tex_path(pak, HOSEK_MAT)].read(); htex = Texture(hraw)
    Q = cube_mip0(qraw, qtex); H = cube_mip0(hraw, htex)
    n = qtex.width
    H = [upsample(h, n) for h in H]
    E = [elevation(f, n) for f in range(6)]
    # brightness match: quarry sky (shown with +0.9 stops) vs clear-sky model, over 15..60 deg elevation
    qs = np.concatenate([Q[f][(E[f] > 15) & (E[f] < 60)].mean(1) for f in range(6)])
    hs = np.concatenate([H[f][(E[f] > 15) & (E[f] < 60)].mean(1) for f in range(6)])
    k = p['target_ratio'] * np.median(hs) / (np.median(qs) * QUARRY_BIAS)
    out = []
    for f in range(6):
        q = np.minimum(Q[f] * k, p['sun_cap'] / QUARRY_BIAS)
        if p['cloud_saturation'] != 1.0:
            g = q.mean(-1, keepdims=True); q = g + (q - g) * p['cloud_saturation']
        h = H[f] / QUARRY_BIAS
        t = np.clip((E[f] - p['blend_lo']) / (p['blend_hi'] - p['blend_lo']), 0, 1)[..., None]
        t = t * t * (3 - 2 * t)
        out.append((q * t + h * (1 - t)).astype(np.float32))
    return qraw, qtex, out, k


def _blur(img, r):
    """separable box blur (r passes of 3-tap) along both axes"""
    x = img
    for _ in range(r):
        x = (np.roll(x, 1, 0) + x + np.roll(x, -1, 0)) / 3
        x = (np.roll(x, 1, 1) + x + np.roll(x, -1, 1)) / 3
    return x


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


ANIME = dict(
    zenith=(0.03, 0.17, 0.78), mid=(0.12, 0.42, 0.95), horizon=(0.55, 0.78, 1.00),   # sky gradient (linear rgb)
    cloud_light=(1.00, 0.98, 0.93), cloud_mid=(0.70, 0.75, 0.93), cloud_shadow=(0.42, 0.47, 0.75),
    rim=(1.00, 0.90, 0.72),
    sky_level=0.50,          # radiance of the sky gradient (shown through the sky material)
    cloud_level=0.85,        # radiance of the lit cloud tops
    mask_lo=0.10, mask_hi=0.22,   # cloudiness -> mask (crisp anime edges)
    band1=0.55, band2=0.80, band_soft=0.04,
    horizon_lo=1.0, horizon_hi=7.0,  # clouds only above the horizon
)


def stylize(faces, elev, p=ANIME):
    """Turn photo clouds into cel-shaded anime clouds over a clean gradient sky (works per cube face)."""
    out = []
    for f, img in enumerate(faces):
        e = elev[f]
        lum = img.mean(-1)
        sat = (img.max(-1) - img.min(-1)) / (img.max(-1) + 1e-4)
        # cloudiness: bright and grey vs blue sky
        cloud = np.clip((1 - sat / 0.55), 0, 1) * np.clip(lum / (np.percentile(lum, 70) + 1e-4), 0, 2)
        cloud = _blur(cloud, 4)
        mask = _smoothstep(p['mask_lo'], p['mask_hi'], cloud * 0.5) * _smoothstep(p['horizon_lo'], p['horizon_hi'], e)
        # shading inside the cloud: relative brightness of the photo cloud, smoothed then cel-banded
        sh = _blur(np.clip(lum / (np.percentile(lum[mask > 0.5], 95) + 1e-4) if (mask > 0.5).any() else lum, 0, 1.2), 7)
        b1 = _smoothstep(p['band1'] - p['band_soft'], p['band1'] + p['band_soft'], sh)
        b2 = _smoothstep(p['band2'] - p['band_soft'], p['band2'] + p['band_soft'], sh)
        cs, cm, cl = (np.array(p[k], np.float32) for k in ('cloud_shadow', 'cloud_mid', 'cloud_light'))
        ccol = cs * (1 - b1[..., None]) + cm * (b1 - b2)[..., None] + cl * b2[..., None]
        # warm rim where the cloud edge meets the sky
        edge = np.clip(mask * (1 - _blur(mask, 2)) * 4, 0, 1)[..., None]
        ccol = ccol * (1 - 0.5 * edge) + np.array(p['rim'], np.float32) * 0.5 * edge
        # clean gradient sky by elevation
        t1 = _smoothstep(0, 25, e)[..., None]; t2 = _smoothstep(20, 80, e)[..., None]
        z, m, h = (np.array(p[k], np.float32) for k in ('zenith', 'mid', 'horizon'))
        sky = h * (1 - t1) + m * t1
        sky = sky * (1 - t2) + z * t2
        res = sky * p['sky_level'] * (1 - mask[..., None]) + ccol * p['cloud_level'] * mask[..., None]
        out.append(res.astype(np.float32))
    return out


def downsample(img):
    if img.shape[0] == 1:
        return img
    return 0.25 * (img[0::2, 0::2] + img[1::2, 0::2] + img[0::2, 1::2] + img[1::2, 1::2])


def encode_cube(qraw, qtex, faces, low_mip_scale=None, low_mip_max=128, fog_faces=None):
    """Re-encode all mips (smallest first, 6 faces per mip) into the quarry texture's layout.
    fog_faces: sky used for the blurry mips (<= low_mip_max) that the cubemap fog samples - e.g. the clear sky
    without its sun disc, so distant buildings in front of the sun don't get a white sun haze painted on them."""
    def mips(top):
        ch = [top]
        for _ in range(qtex.mips - 1):
            ch.append([downsample(f) for f in ch[-1]])
        return ch
    chain = mips(faces)
    fog_chain = mips(fog_faces) if fog_faces is not None else chain
    payload = []
    for level in reversed(range(qtex.mips)):
        for k, f in enumerate(chain[level]):
            img = f
            if img.shape[0] <= low_mip_max:
                img = fog_chain[level][k]
            if low_mip_scale is not None and img.shape[0] <= low_mip_max:
                img = img * np.array(low_mip_scale, np.float32)   # only the blurry mips the cubemap fog samples
            if img.shape[0] < 4:  # pad tiny mips to one 4x4 block
                img = np.repeat(np.repeat(img, 4 // img.shape[0], 0), 4 // img.shape[1], 1)
            payload.append(bc6h.encode(bc6h.image_to_blocks(img)))
    data = b''.join(payload)
    assert len(data) == len(qraw) - qtex.pixel_off, (len(data), len(qraw) - qtex.pixel_off)
    return qraw[:qtex.pixel_off] + data


def panorama(faces, w=1024):
    """quick equirect-ish preview: elevation -10..90 deg on y, azimuth via face strip (for eyeballing only)"""
    n = faces[0].shape[0]
    strip = np.concatenate([faces[3], np.rot90(faces[1], 1), faces[2][::-1, ::-1], np.rot90(faces[0], -1)], 1)
    return strip


# ---- painted clear sky (Dusk look) --------------------------------------------------------------------------
# World direction of every cube texel. Side faces: elevation axis from UP_EDGE (verified against the clear-sky
# model); FACE_AXES gives each side face's outward normal and the world axis its 'across' coordinate runs along
# (worked out in game with debug_dirs: red = +x, green = +y, blue = up).
FACE_AXES = {0: ((1, 0, 0), (0, 1, 0)), 1: ((-1, 0, 0), (0, -1, 0)), 2: ((0, 1, 0), (-1, 0, 0)), 3: ((0, -1, 0), (1, 0, 0))}
TOP_AXES = ((1, 0, 0), (0, 1, 0))   # top face: world axes along its columns (s) and rows (t)


def directions(face, n):
    c = (np.arange(n) + 0.5) / n * 2 - 1
    s, t = np.meshgrid(c, c)
    if face in (4, 5):
        ax, ay = (np.array(v, np.float32) for v in TOP_AXES)
        z = 1.0 if face == 4 else -1.0
        d = s[..., None] * ax + t[..., None] * ay + np.array([0, 0, z], np.float32)
    else:
        nrm, acr = (np.array(v, np.float32) for v in FACE_AXES[face])
        up = {'left': -s, 'right': s, 'bottom': t, 'top': -t}[UP_EDGE[face]]
        across = t if UP_EDGE[face] in ('left', 'right') else s
        d = nrm + up[..., None] * np.array([0, 0, 1], np.float32) + across[..., None] * acr
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


CLEAR = dict(   # linear radiance as shown through the quarry material; tuned against screenshots/ref_dusk
    zenith=(0.092, 0.122, 0.165), horizon=(0.195, 0.172, 0.150), sun_glow=(0.15, 0.09, 0.02), below=(0.12, 0.11, 0.10),
    level=1.0, horizon_power=3.0, glow_width=18.0, glow_level=0.45, halo_width=60.0, halo_level=0.12,
    sun_radius=4.8, sun_level=2.6, sun_color=(1.00, 0.95, 0.85),
)


def clear_sky(n, p=CLEAR, debug_dirs=False):
    """Clear hazy sky: blue-grey zenith, pale warm haze at the horizon, warm glow and a big soft-edged sun disc."""
    a, e = np.radians(p['sun_az']), np.radians(p['sun_el'])
    L = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)], np.float32)
    out = []
    for f in range(6):
        d = directions(f, n)
        if debug_dirs:
            x, y = d[..., 0:1], d[..., 1:2]   # +x red, +y green, -x blue, -y yellow
            col = (np.clip(x, 0, 1) * np.array([1, 0, 0], np.float32) + np.clip(y, 0, 1) * np.array([0, 1, 0], np.float32)
                   + np.clip(-x, 0, 1) * np.array([0, 0, 1], np.float32) + np.clip(-y, 0, 1) * np.array([1, 1, 0], np.float32))
            out.append((col ** 2 * 0.35).astype(np.float32)); continue
        z = np.clip(d[..., 2:3], -1, 1)
        h = np.clip(z, 0, 1)
        t = 1 - np.power(1 - h, p['horizon_power'])          # 0 at the horizon -> 1 at the zenith
        sky = np.array(p['horizon'], np.float32) * (1 - t) + np.array(p['zenith'], np.float32) * t
        sky = np.where(z < 0, np.array(p['below'], np.float32), sky)
        ang = np.degrees(np.arccos(np.clip(d @ L, -1, 1)))[..., None]
        glow = p['glow_level'] * np.exp(-(ang / p['glow_width']) ** 2) + p['halo_level'] * np.exp(-(ang / p['halo_width']) ** 2)
        sky = sky + glow * np.array(p['sun_glow'], np.float32) * (1 - 0.5 * t)
        disc = np.clip((p['sun_radius'] - ang) / 0.6 + 0.5, 0, 1)   # soft 0.6 deg edge
        sky = sky * (1 - disc) + disc * p['sun_level'] * np.array(p['sun_color'], np.float32)
        out.append((sky * p['level']).astype(np.float32))
    return out
