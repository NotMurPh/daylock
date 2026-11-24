"""Write a Deadlock Mod Manager static mod source for a release zip hosted on GitHub Releases + GitHub Pages.

Writes <out>/dmm-source.json, <out>/catalog.json and <out>/mods/<listing>.json. Host <out> on GitHub Pages; people add
<site>dmm-source.json in the Mod Manager (Settings > Mods > Mod sources). Custom mod sources are only in the Mod
Manager's Nightly build for now (they came after 2.3.0).

usage: python tools/dmm_source.py --site https://you.github.io/daylock/ --repo https://github.com/you/daylock
                                  --version 1.2 --zip work/release/Daylock_v1.2.zip --out site
       (the zip must be uploaded as release asset Daylock_v<version>.zip under tag v<version>)
"""
import argparse
import hashlib
import json
import os
import time
import urllib.parse

DESCRIPTION = """Deadlock is always at night, so this makes it day. Midtown and the Hideout become a sunny afternoon: \
the sun is baked into the map lighting with real shadows from buildings, bridges and props, the sky is blue with \
clouds, and the night lamps, neon and window glow are turned down.

Visual only. Walls, cover (vent steam, plaza fog), items and spawns are the same as the normal map.

Runs about 7% faster than stock (467 vs 438 average FPS at 11 spots around Midtown), since the night storm and smog are gone.

If a Deadlock update changes Midtown or the Hideout, turn Daylock off until it's updated."""
TITLE = 'Daylock - Daytime Midtown & Hideout'
TAGS = ['daytime', 'lighting', 'map', 'midtown', 'hideout', 'performance']


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def links(site, source_id='daylock', listing='daylock'):
    """deadlock-mod-manager:// links that add the source / install the mod (for a web page; GitHub strips them)"""
    enc = lambda s: urllib.parse.quote(s, safe='')
    d = site + 'dmm-source.json'
    return (f'deadlock-mod-manager://sources/add?url={enc(d)}',
            f'deadlock-mod-manager://sources/install?url={enc(d)}&source={source_id}&listing={listing}')


def write_source(out, site, repo, version, zip_path, released=None, changelog='', title=TITLE, description=DESCRIPTION,
                 author='', tags=TAGS, images=(), name='Daylock', source_id='daylock', listing='daylock'):
    released = released or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    origin = site.rstrip('/').rsplit('/', 1)[0]   # https://<login>.github.io
    os.makedirs(os.path.join(out, 'mods'), exist_ok=True)
    dump = lambda obj, path: open(os.path.join(out, path), 'w', encoding='utf-8', newline='\n').write(
        json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    dump({
        'format': 'dmm-source', 'protocolVersion': '1.0', 'sourceId': source_id, 'name': name,
        'gameId': 'deadlock', 'homepageUrl': site,
        'catalog': {'kind': 'static', 'indexUrl': './catalog.json'},
        'networkOrigins': {
            'api': [origin],
            # GitHub release downloads redirect from github.com to these hosts
            'downloads': ['https://github.com', 'https://release-assets.githubusercontent.com',
                          'https://objects.githubusercontent.com'],
            'media': [origin],
        },
    }, 'dmm-source.json')
    dump({'snapshotId': f'{listing}-{version}', 'items': [{
        'id': listing, 'title': title, 'availability': 'available',
        'isNsfw': False, 'detailUrl': f'./mods/{listing}.json'}]}, 'catalog.json')
    zip_name = f'Daylock_v{version}.zip'
    dump({
        'id': listing, 'title': title, 'availability': 'available', 'isNsfw': False,
        'description': description, 'descriptionFormat': 'markdown', 'author': author,
        'tags': list(tags),
        'images': list(images),
        'homepageUrl': site, 'updatedAt': released,
        'release': {
            'id': f'v{version}', 'contentRevision': f'v{version}', 'version': version, 'publishedAt': released,
            'changelog': changelog,
            'artifacts': [{
                'id': f'{listing}-zip', 'filename': zip_name, 'format': 'zip',
                'download': {'url': f'{repo}/releases/download/v{version}/{zip_name}'},
                'size': os.path.getsize(zip_path), 'hashes': {'sha256': sha256(zip_path)},
            }],
            'installation': {'mode': 'manual'},
        },
    }, os.path.join('mods', f'{listing}.json'))
    return site + 'dmm-source.json'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--site', required=True, help='GitHub Pages URL ending in /')
    ap.add_argument('--repo', required=True, help='https://github.com/<you>/<repo>')
    ap.add_argument('--version', required=True)
    ap.add_argument('--zip', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--changelog', default='')
    ap.add_argument('--author', default='')
    ap.add_argument('--images', nargs='*', default=[], help='full image URLs for the store page')
    a = ap.parse_args()
    site = a.site if a.site.endswith('/') else a.site + '/'
    print('descriptor', write_source(a.out, site, a.repo.rstrip('/'), a.version, a.zip, changelog=a.changelog,
                                     author=a.author, images=a.images))
