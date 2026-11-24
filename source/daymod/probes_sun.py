"""Real-sun daylight for the light-probe atlas (lighting of props, trees, dynamic objects).

Atlas = 6 groups of slices (ambient cube faces, order +X -X +Y -Y +Z -Z), each group D/6 deep.
Every env_combined_light_probe_volume owns a box of probes at atlas offset (x, Y, Z).
Sun / sky visibility per probe is traced by sunbake (points mode).
"""
import os, subprocess
import numpy as np
from s2res import Resource, Texture
import kv3, texio, bc6h, daylight, sunlight

HERE = os.path.dirname(os.path.abspath(__file__))
FACES = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float32)
# how much open sky each face sees (up face full, sides half, down face only ground bounce)
SKY_W = np.array([0.5, 0.5, 0.5, 0.5, 1.0, 0.15], np.float32)
# fill direction: face fill *= (face night light / mean of the 6 faces) ** gamma, clipped
FILL_DIR_GAMMA, FILL_DIR_MIN, FILL_DIR_MAX = 0.6, 0.35, 1.6


def probe_volumes(mp, name):
    ents = []
    for p in mp:
        if p.startswith('maps/%s/entities/' % name) and p.endswith('.vents_c'):
            raw = mp[p].read(); r = Resource(raw); _, o, s = r.block('DATA')
            ents += kv3.entities(kv3.read(raw[o:o + s]))
    return [e for e in ents if e.get('classname') == 'env_combined_light_probe_volume']


def probe_points(vols):
    pts, idx = [], []
    for e in vols:
        nx, ny, nz = e['light_probe_size_x'], e['light_probe_size_y'], e['light_probe_size_z']
        ax, ay, az = e['light_probe_atlas_x'], e['light_probe_atlas_Y'], e['light_probe_atlas_Z']
        mn = np.array(e['box_mins'], np.float64); mx = np.array(e['box_maxs'], np.float64)
        org = np.array(e['origin'], np.float64)
        yaw = np.radians(float(e['angles'][1]))
        c, s = np.cos(yaw), np.sin(yaw)
        i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing='ij')
        loc = np.stack([mn[0] + (i + 0.5) * (mx[0] - mn[0]) / nx,
                        mn[1] + (j + 0.5) * (mx[1] - mn[1]) / ny,
                        mn[2] + (k + 0.5) * (mx[2] - mn[2]) / nz], -1).reshape(-1, 3)
        world = np.stack([org[0] + c * loc[:, 0] - s * loc[:, 1], org[1] + s * loc[:, 0] + c * loc[:, 1], org[2] + loc[:, 2]], -1)
        pts.append(world.astype(np.float32))
        idx.append(np.stack([(ax + i).ravel(), (ay + j).ravel(), (az + k).ravel()], -1))
    return np.concatenate(pts), np.concatenate(idx)


def convert(raw, mp, name, params, sb, work, pool, fallback):
    tex = Texture(raw)
    W, H, D = tex.width, tex.height, tex.depth
    bw, bh = W // 4, H // 4
    px = texio.decode_all_blocks(raw, tex, pool).astype(np.float32)
    per = bw * bh
    vol = np.stack([bc6h.blocks_to_image(px[z * per:(z + 1) * per], bw, bh) for z in range(D)])   # (D,H,W,3)
    G = D // 6
    # default: old conversion everywhere (padding / unused cells)
    out = daylight.convert(vol.reshape(-1, 3), fallback).reshape(vol.shape)
    pts, idx = probe_points(probe_volumes(mp, name))
    ok = (idx[:, 0] < W) & (idx[:, 1] < H) & (idx[:, 2] < G)
    pts, idx = pts[ok], idx[ok]
    os.makedirs(work, exist_ok=True)
    pf, rf = os.path.join(work, 'probe_pts_%s.f32' % name), os.path.join(work, 'probe_vis_%s.bin' % name)
    pts.tofile(pf)
    subprocess.run([os.path.join(HERE, 'sunbake', 'sunbake.exe'), 'points', '-geom', sb['geom'], '-in', pf, '-out', rf,
                    '-az', str(sb['az']), '-el', str(sb['el']), '-samples', '32', '-sky', '64', '-cone', '1.2'], check=True)
    res = np.fromfile(rf, np.uint8).reshape(-1, 2).astype(np.float32) / 255
    vis, sky = res[:, 0:1], res[:, 1:2]
    L = sunlight.sun_vector(sb['az'], sb['el'])
    # per-face share of the night light: the interior fill keeps that direction instead of lighting all 6 sides equally
    nl = np.stack([vol[f * G + idx[:, 2], idx[:, 1], idx[:, 0]] @ sunlight.LUMW for f in range(6)], 1)
    share = np.clip((nl / (nl.mean(1, keepdims=True) + 1e-5)) ** FILL_DIR_GAMMA, FILL_DIR_MIN, FILL_DIR_MAX)
    for f in range(6):
        night = vol[f * G + idx[:, 2], idx[:, 1], idx[:, 0]]
        ndl = np.full_like(vis, max(float(FACES[f] @ L), 0.0))
        bounce = 0.0
        if f == 5:   # down face: sunlit ground bounces light up
            bounce = 0.12 * params['sun_gain'] * vis
        day, _ = sunlight.convert(night, vis, ndl, sky * SKY_W[f] + bounce, params, fill_mul=share[:, f])
        out[f * G + idx[:, 2], idx[:, 1], idx[:, 0]] = day
    blocks = np.concatenate([bc6h.image_to_blocks(out[z]) for z in range(D)]).astype(np.float16)
    return texio.rebuild(raw, tex, texio.encode_all_blocks(blocks, pool)), len(pts), float(vis.mean())
