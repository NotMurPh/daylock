"""pick_spots.py: choose open camera spots (clear line of sight) looking at given map entities / points."""
import subprocess, sys, os, math
import numpy as np, vpk
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2res import Resource
import kv3
HERE = os.path.dirname(os.path.abspath(__file__))
BAKE = os.path.join(HERE, 'sunbake', 'sunbake.exe')
GEOM = os.path.join(HERE, '..', 'work', 'geom_midtown')
TMP = os.path.join(HERE, '..', 'work', 'spots')


def ents(name='dl_midtown'):
    import gamepath
    mp = vpk.open(os.path.join(gamepath.citadel(), 'maps', '%s.vpk' % name))
    out = []
    for p in mp:
        if p.startswith('maps/%s/entities/' % name) and p.endswith('.vents_c'):
            raw = mp[p].read(); r = Resource(raw); _, o, s = r.block('DATA')
            out += kv3.entities(kv3.read(raw[o:o + s]))
    return out


def pick(targets, dist=330, up=170, side=14):
    """targets: list of (label, (x,y,z)) -> list of (label, setpos/setang command) for those with a clear view"""
    os.makedirs(TMP, exist_ok=True)
    pairs, meta = [], []
    for li, (lab, t) in enumerate(targets):
        t = np.array(t, np.float32) + [0, 0, 30]
        for k in range(24):
            a = 2 * math.pi * k / 24
            d = np.array([math.cos(a), math.sin(a), 0], np.float32)
            cam = t + d * dist + [0, 0, up]
            boom = cam + d * 130 + [0, 0, 50]
            for p in (cam, boom):
                pairs.append(np.concatenate([p, t]))
            meta.append((li, k, cam))
    f_in, f_out = os.path.join(TMP, 'pairs.f32'), os.path.join(TMP, 'los.bin')
    np.array(pairs, np.float32).tofile(f_in)
    subprocess.run([BAKE, 'los', '-geom', GEOM, '-in', f_in, '-out', f_out], check=True, capture_output=True)
    ok = np.fromfile(f_out, np.uint8).reshape(-1, 2).all(1)
    res, done = [], set()
    for (li, k, cam), good in zip(meta, ok):
        if good and li not in done:
            done.add(li)
            lab, t = targets[li]
            dx, dy, dz = t[0] - cam[0], t[1] - cam[1], t[2] + 30 - cam[2]
            yaw = math.degrees(math.atan2(dy, dx)) + side
            pitch = -math.degrees(math.atan2(dz, math.hypot(dx, dy)))
            res.append((lab, 'setpos %d %d %d; setang %d %d 0' % (cam[0], cam[1], cam[2], pitch, yaw)))
    return res


if __name__ == '__main__':
    E = ents()
    tg = []
    for sub, n in (('citadel_breakable_prop_wooden_crate', 3), ('citadel_breakable_prop_tough_crate', 3), ('citadel_breakable_item_container', 2)):
        cand = [e for e in E if e.get('subclass_name') == sub]
        tg += [('y_%s_%d' % ('_'.join(sub.split('_')[-2:]), i), e['origin']) for i, e in enumerate(cand[:40])]
    st = [e for e in E if 'street_steam_02' in str(e.get('effect_name', ''))]
    tg += [('y_vent_%d' % i, e['origin']) for i, e in enumerate(st[:30])]
    tg += [('y_veil_big', (2670, 7520, 840)), ('y_veil_big', (2670, 7300, 800)), ('y_veil_big', (2600, 7700, 860)), ('y_veil_small', (8656, -4236, 560)), ('y_plaza_fog', (-2700, 2500, 120))]
    got = pick(tg)
    keep, cnt = [], {}
    for lab, cmd in got:
        kind = lab.rsplit('_', 1)[0]
        if cnt.get(kind, 0) < (2 if 'veil' not in kind and 'plaza' not in kind else 1):
            cnt[kind] = cnt.get(kind, 0) + 1; keep.append((lab, cmd))
    for lab, cmd in keep:
        print("  '%s' = '%s'" % (lab, cmd))
