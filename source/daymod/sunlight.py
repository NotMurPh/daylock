"""Daylight with a real (ray-traced) sun.

Per lightmap texel the Go baker (daymod/sunbake) gives:
    vis  : fraction of the sun disc visible   (0..1)
    ndl  : max(N.L, 0) with the vertex normal  (0..1)
    sky  : cosine-weighted sky visibility      (0..1)
Day lighting = warm sun * vis * ndl  +  cool sky * sky  +  saturating fill from the night bake (interiors)
             + a little of the original lamps indoors.
The directional lightmap (sh2_lum, DXT1) stores the dominant light direction per texel as
0.5 + 0.5 * v with v = (-dir.y, dir.z, -dir.x); the sun's share of the light pulls it toward the sun.
"""
import numpy as np
import daylight

V9 = dict(
    sun_gain=1.8, sun_color=(1.00, 0.89, 0.73),
    sky_gain=0.72, sky_color=(0.66, 0.81, 1.00),
    fill_gain=0.6, fill_ref=0.10, fill_gamma=0.6, fill_color=(1.00, 0.91, 0.80), fill_open_cut=1.8, fill_open_min=0.25,
    lamp_in=0.08, lamp_out=0.02, vis_ref=0.05, neon_in=0.10, neon_out=0.05,
    floor=0.05, scale=1.0, max_out=64.0,
    dir_strength=0.80,       # length of the encoded direction vector for pure sunlight
)

LUMW = np.array([0.2126, 0.7152, 0.0722], np.float32)


def convert(night, vis, ndl, sky, p=V9, fill_sky=None, fill_mul=None):
    """night (...,3) linear HDR night lighting; vis/ndl/sky (...,1) in 0..1.
    returns (day (...,3), sun_share (...,1))"""
    shp = night.shape
    x = np.asarray(night, np.float32).reshape(-1, 3)
    vis = vis.reshape(-1, 1); ndl = ndl.reshape(-1, 1); sky = sky.reshape(-1, 1)
    coef = np.clip(x @ daylight.MINV.T, 0, None)
    recon = coef @ daylight.M.T
    resid = np.clip(x - recon, 0, None)
    a, c, d = coef[:, 0:1], coef[:, 1:2], coef[:, 2:3]
    v = np.clip(a / p['vis_ref'], 0, 1); v = v * v * (3 - 2 * v)
    lamp_g = p['lamp_in'] + (p['lamp_out'] - p['lamp_in']) * v
    neon_g = p['neon_in'] + (p['neon_out'] - p['neon_in']) * v
    sun = p['sun_gain'] * vis * ndl * np.array(p['sun_color'], np.float32)
    rest = p['sky_gain'] * np.power(sky, p.get('sky_gamma', 1.0)) * np.array(p['sky_color'], np.float32)   # gamma>1: occluded spots darker (AO-like)
    rest += lamp_g * (c * daylight.LAMP + d * daylight.RED) + neon_g * resid
    energy = c + d + resid.sum(1, keepdims=True) / 3 + a
    f = 1 - np.exp(-np.power(energy / p['fill_ref'], p['fill_gamma']))
    # interiors keep a strong fill; open areas rely on real sky light so shade stays readable
    fs = sky if fill_sky is None else fill_sky.reshape(-1, 1)
    fw = np.clip(1 - p.get('fill_open_cut', 0.0) * fs, p.get('fill_open_min', 0.0), 1)
    if fill_mul is not None:   # probes: keep the night light's direction (which side of an object faced the light)
        fw = fw * fill_mul.reshape(-1, 1)
    rest += p['fill_gain'] * f * fw * np.array(p['fill_color'], np.float32)
    rest += p['floor'] * (x.sum(1, keepdims=True) > 0)
    day = np.clip((sun + rest) * p['scale'], 0, p['max_out'])
    ls = (sun @ LUMW)[:, None]; lr = (rest @ LUMW)[:, None]
    share = ls / (ls + lr + 1e-6)
    return day.reshape(shp), share.reshape(shp[:-1] + (1,))


def sun_vector(az, el):
    a, e = np.radians(az), np.radians(el)
    return np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)], np.float32)


def mix_direction(enc_rgb_u8, share, L, p=V9):
    """enc_rgb_u8 (...,3) original sh2_lum texels; share (...,1) sun share of the day light; L sun direction"""
    v_old = enc_rgb_u8.astype(np.float32) / 255 * 2 - 1
    v_rest = 0.6 * v_old + np.array([0, 0.25, 0], np.float32)       # daylight fill comes more from above
    v_sun = p['dir_strength'] * np.array([-L[1], L[2], -L[0]], np.float32)
    v = share * v_sun + (1 - share) * v_rest
    return np.clip(np.round((v * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)


def bc1_encode(img):
    """img (H,W,3) uint8 -> DXT1 bytes (no alpha), simple bounding-box endpoints"""
    H, W, _ = img.shape
    blocks = img.reshape(H // 4, 4, W // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    return b''.join(_bc1_blocks(blocks[i:i + 262144].astype(np.int32)) for i in range(0, len(blocks), 262144))


def _bc1_blocks(blk):
    lo = blk.min(1); hi = blk.max(1)

    def to565(c):
        return ((c[:, 0] * 31 + 127) // 255 << 11) | ((c[:, 1] * 63 + 127) // 255 << 5) | ((c[:, 2] * 31 + 127) // 255)

    def from565(v):
        r = (v >> 11) & 31; g = (v >> 5) & 63; b = v & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], 1)
    c0 = to565(hi); c1 = to565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    e0 = from565(c0).astype(np.float32); e1 = from565(c1).astype(np.float32)
    pal = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], 1)          # (n,4,3)
    dist = ((blk[:, :, None, :].astype(np.float32) - pal[:, None, :, :]) ** 2).sum(-1)  # (n,16,4)
    idx = dist.argmin(-1).astype(np.uint32)
    same = c0 == c1
    idx[same] = 0
    bits = np.zeros(len(idx), np.uint32)
    for i in range(16):
        bits |= idx[:, i] << (2 * i)
    out = np.zeros((len(idx), 8), np.uint8)
    out[:, 0] = c0 & 255; out[:, 1] = c0 >> 8; out[:, 2] = c1 & 255; out[:, 3] = c1 >> 8
    for k in range(4):
        out[:, 4 + k] = (bits >> (8 * k)) & 255
    return out.tobytes()
