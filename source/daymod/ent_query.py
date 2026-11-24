import sys, json, collections
ents = json.load(open(sys.argv[1]))
cls = sys.argv[2].split(',')
maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 3
c = collections.Counter(e.get('classname') for e in ents)
for k, v in sorted(c.items()):
    if any(x in k for x in ['light', 'sky', 'fog', 'post', 'cubemap', 'sun', 'env_', 'tonemap', 'logic', 'relay', 'pulse']): print(v, k)
for cl in cls:
    sel = [e for e in ents if e.get('classname') == cl]
    print('=====', cl, len(sel))
    for e in sel[:maxn]:
        print(json.dumps({k: v for k, v in e.items()}, default=str)[:3000])
