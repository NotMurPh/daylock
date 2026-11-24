"""extract_geom.py <map> <out_dir> : dump world meshes (raw meshopt buffers + layout + transforms) for the Go sun baker.

out_dir/geom.bin       raw MVTX / MIDX block bytes, concatenated
out_dir/geom.json      manifest: buffers, draws (with instances, material, lightmap flag, cast flag), lightmap info
"""
import json, os, re, sys
import vpk
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2res import Resource
import kv3

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\citadel'
# materials that should not block sunlight
NO_CAST = re.compile(r'glass|water(?!front)|/fx/|sky|tools/|toolsnodraw|light_?beam|fog|decal|overlay|smoke|cloud|godray|glow|'
                     r'shadow_?blocker|volumetric|particle|translucent|_unlit|projected', re.I)
IDENT = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0]


def flat(t):
    if t and isinstance(t[0], list):
        return [float(x) for row in t for x in row]
    return [float(x) for x in t]


def main(name, out):
    os.makedirs(out, exist_ok=True)
    mp = vpk.open(os.path.join(GAME, 'maps', name + '.vpk'))
    pre = 'maps/%s/worldnodes/' % name
    wr = mp['maps/%s/world.vwrld_c' % name].read()
    r = Resource(wr); _, o, s = r.block('DATA'); world = kv3.read(wr[o:o + s])
    li = world['m_worldLightingInfo']
    nodes = [p for p in mp if p.startswith(pre) and p.endswith('.vwnod_c')]
    # model -> list of (drawcall index or None for all, transform, lodmask)
    users = {}
    for npath in nodes:
        raw = mp[npath].read(); r = Resource(raw); _, o, s = r.block('DATA'); d = kv3.read(raw[o:o + s])
        for so in d['m_sceneObjects']:
            users.setdefault(so['m_renderableModel'], []).append((None, flat(so['m_vTransform']), 0))
        for ag in d['m_aggregateSceneObjects']:
            frags = ag['m_fragmentTransforms']; fi = 0
            for m in ag['m_aggregateMeshes']:
                t = IDENT
                if m['m_bHasTransform']:
                    t = flat(frags[fi]) if fi < len(frags) else IDENT; fi += 1
                users.setdefault(ag['m_renderableModel'], []).append((m['m_nDrawCallIndex'], t, m['m_nLODGroupMask']))
    blob = open(os.path.join(out, 'geom.bin'), 'wb'); pos = 0
    meshes = []; nd = 0
    for model, uses in users.items():
        p = model + '_c'
        if p not in mp:
            continue
        raw = mp[p].read(); r = Resource(raw)
        _, o, s = r.block('CTRL'); ctrl = kv3.read(raw[o:o + s])
        _, o, s = r.block('MDAT'); mdat = kv3.read(raw[o:o + s])
        dblocks = [b for b in r.blocks if b[0] in ('MVTX', 'MIDX')]
        em = ctrl['embedded_meshes'][0]
        bufs = {}

        def put(bi):
            nonlocal pos
            if bi not in bufs:
                b = dblocks[bi]
                blob.write(raw[b[1]:b[1] + b[2]]); bufs[bi] = (pos, b[2]); pos += b[2]
            return bufs[bi]
        vbs = []
        for vb in em['m_vertexBuffers']:
            off, size = put(vb['m_nBlockIndex'])
            fields = {}
            for f in vb['m_inputLayoutFields']:
                key = '%s%d' % (f['m_pSemanticName'].upper(), f['m_nSemanticIndex'])
                fields[key] = [f['m_Format'], f['m_nOffset']]
            vbs.append(dict(off=off, size=size, count=vb['m_nElementCount'], stride=vb['m_nElementSizeInBytes'],
                            meshopt=bool(vb['m_bMeshoptCompressed']), zstd=bool(vb['m_bCompressedZSTD']), fields=fields))
        ibs = []
        for ib in em['m_indexBuffers']:
            off, size = put(ib['m_nBlockIndex'])
            ibs.append(dict(off=off, size=size, count=ib['m_nElementCount'], isize=ib['m_nElementSizeInBytes'],
                            meshopt=bool(ib['m_bMeshoptCompressed']), seq=bool(ib['m_bMeshoptIndexSequence'])))
        draws = []
        dcs = mdat['m_sceneObjects'][0]['m_drawCalls']
        for i, dc in enumerate(dcs):
            inst = [t for (di, t, lm) in uses if (di is None or di == i) and lm in (0, 1)]
            if not inst:
                continue
            mat = dc['m_material'] or ''
            draws.append(dict(vbs=[v['m_hBuffer'] for v in dc['m_vertexBuffers']], ib=dc['m_indexBuffer']['m_hBuffer'],
                              base=dc['m_nBaseVertex'], start=dc['m_nStartIndex'], n=dc['m_nIndexCount'],
                              prim=dc['m_nPrimitiveType'], lm=bool(dc.get('m_bHasBakedLightingFromLightMap')),
                              cast=not NO_CAST.search(mat), mat=mat, inst=inst))
            nd += 1
        meshes.append(dict(model=model, vbs=vbs, ibs=ibs, draws=draws))
    blob.close()
    json.dump(dict(map=name, lm_uv_scale=li['m_vLightmapUvScale'], lightmaps=li['m_lightMaps'], meshes=meshes),
              open(os.path.join(out, 'geom.json'), 'w'))
    print('models', len(meshes), 'draws', nd, 'blob MB', pos >> 20)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
