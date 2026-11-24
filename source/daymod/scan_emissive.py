"""Find world materials (used by the Midtown map) that glow: self-illum / emissive parameters."""
import sys, json, collections
import vpk
from s2res import Resource, rerl
import kv3t

PAK = r'C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\citadel\pak01_dir.vpk'
MAP = r'C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\citadel\maps\dl_midtown.vpk'


def mat_params(raw):
    r = Resource(raw)
    _, o, s = r.block('DATA')
    py = kv3t.to_py(kv3t.read(raw[o:o + s])[1])
    return py


def map_materials(mp, pak):
    """materials referenced by every model the map uses (map-local models + pak models they reference)."""
    mats = set(); models = set()
    for p in mp:
        if p.endswith('.vmdl_c'):
            for r in rerl(mp[p].read()):
                if r.endswith('.vmat'): mats.add(r + '_c')
                if r.endswith('.vmdl'): models.add(r + '_c')
        if p.endswith('.vwrld_c') or p.endswith('.vents_c') or p.endswith('.vmesh_c'):
            for r in rerl(mp[p].read()):
                if r.endswith('.vmat'): mats.add(r + '_c')
                if r.endswith('.vmdl'): models.add(r + '_c')
    for m in list(models):
        src = mp if m in mp else pak
        try:
            for r in rerl(src[m].read()):
                if r.endswith('.vmat'): mats.add(r + '_c')
        except KeyError:
            pass
    return mats


if __name__ == '__main__':
    pak = vpk.open(PAK); mp = vpk.open(MAP)
    mats = map_materials(mp, pak)
    print('materials used by map:', len(mats))
    names = collections.Counter(); hits = []
    for m in sorted(mats):
        src = mp if m in mp else pak
        try:
            py = mat_params(src[m].read())
        except Exception as e:
            continue
        ints = {p['m_name']: p['m_nValue'] for p in py.get('m_intParams', [])}
        flts = {p['m_name']: p['m_flValue'] for p in py.get('m_floatParams', [])}
        vecs = {p['m_name']: p['m_value'] for p in py.get('m_vectorParams', [])}
        keys = [k for k in list(ints) + list(flts) + list(vecs) if 'illum' in k.lower() or 'emiss' in k.lower() or 'glow' in k.lower()]
        if any(ints.get(k) for k in ints if k.startswith('F_') and ('ILLUM' in k or 'EMISS' in k)) or keys:
            hits.append(dict(mat=m, shader=py.get('m_shaderName'), ints={k: v for k, v in ints.items() if k in keys or k.startswith('F_')},
                             flts={k: v for k, v in flts.items() if k in keys}, vecs={k: v for k, v in vecs.items() if k in keys}))
            for k in keys: names[k] += 1
    print('glowing materials:', len(hits))
    print(names.most_common(30))
    json.dump(hits, open(sys.argv[1], 'w'), indent=1)
