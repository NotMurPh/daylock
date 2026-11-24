import sys, json
from s2res import Resource
import kv3
d = open(sys.argv[1], 'rb').read()
r = Resource(d); t, o, s = r.block('DATA')
lump = kv3.read(d[o:o + s])
ents = kv3.entities(lump)
json.dump(ents, open(sys.argv[2], 'w'), indent=1, default=str)
print(len(ents), 'entities', list(lump.keys()))
import collections
print(collections.Counter(e.get('classname') for e in ents).most_common(80))
