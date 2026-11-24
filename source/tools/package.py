"""Pack built maps into a release zip: pak99_dir.vpk (holding maps/dl_midtown.vpk + maps/dl_hideout.vpk) + README.txt.

usage: python tools/package.py --version 1.2 [--note "Built for the 2026-12-01 patch."] [--page URL]
                               [--maps work/out] [--out work/release]
Prints the zip's size and SHA-256 (needed for the Mod Manager source, see tools/dmm_source.py).
"""
import argparse
import hashlib
import os
import sys
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'daymod'))
from vpkwrite import write_vpk  # noqa: E402

MAPS = ('dl_midtown', 'dl_hideout')


def file_entry(path):
    n, crc = os.path.getsize(path), 0
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(64 << 20), b''):
            crc = zlib.crc32(b, crc)
    return n, crc & 0xFFFFFFFF, (lambda p=path: open(p, 'rb').read())


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(64 << 20), b''):
            h.update(b)
    return h.hexdigest()


def package(version, maps_dir, out_dir, note='', page=''):
    os.makedirs(out_dir, exist_ok=True)
    pak = os.path.join(out_dir, 'pak99_dir.vpk')
    entries = {}
    for m in MAPS:
        p = os.path.join(maps_dir, m + '.vpk')
        if not os.path.isfile(p):
            raise SystemExit('missing ' + p + ' (run build_all.ps1 first)')
        entries['maps/%s.vpk' % m] = file_entry(p)
    write_vpk(pak, entries)
    import vpk   # check the pak holds exactly the input maps
    pk = vpk.open(pak)
    for name, (n, crc, _) in entries.items():
        meta = pk.get_file_meta(name)
        if meta['file_length'] != n or meta['crc32'] != crc:
            raise SystemExit('pak check failed for ' + name)
    readme = open(os.path.join(ROOT, 'tools', 'release_readme.txt'), encoding='utf-8').read()
    readme = readme.replace('{VERSION}', version).replace('{NOTE}', note).replace(
        '{PAGE}', page or '(see the mod page)').replace('\n', '\r\n')
    z = os.path.join(out_dir, 'Daylock_v%s.zip' % version)
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(pak, 'pak99_dir.vpk')
        zf.writestr('README.txt', readme)
    os.remove(pak)
    return z, os.path.getsize(z), sha256(z)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--version', required=True)
    ap.add_argument('--note', default='', help='one line at the end of README.txt')
    ap.add_argument('--page', default='', help='install page URL for README.txt')
    ap.add_argument('--maps', default=os.path.join(ROOT, 'work', 'out'), help='folder with dl_midtown.vpk + dl_hideout.vpk')
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'release'))
    a = ap.parse_args()
    z, size, digest = package(a.version, a.maps, a.out, a.note, a.page)
    print(z)
    print('size  ', size)
    print('sha256', digest)
