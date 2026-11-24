"""Write a single-file VPK v1 (all data embedded), streaming file contents from callables."""
import struct
import zlib
from collections import OrderedDict


def write_vpk(out_path, files):
    """files: dict path -> (length, crc32, reader) where reader() returns bytes; or path -> bytes"""
    norm = {}
    for p, v in files.items():
        if isinstance(v, (bytes, bytearray)):
            data = bytes(v)
            norm[p] = (len(data), zlib.crc32(data) & 0xFFFFFFFF, (lambda d=data: d))
        else:
            norm[p] = v
    tree = OrderedDict()
    for p in sorted(norm):
        d, _, fn = p.rpartition('/')
        name, dot, ext = fn.rpartition('.')
        if not dot:
            name, ext = fn, ''
        tree.setdefault(ext or ' ', OrderedDict()).setdefault(d or ' ', []).append((name, p))
    # compute offsets
    order = []
    off = 0
    entries = {}
    for ext, dirs in tree.items():
        for d, items in dirs.items():
            for name, p in items:
                ln, crc, _ = norm[p]
                entries[p] = (crc, off, ln)
                order.append(p)
                off += ln
    tb = bytearray()
    for ext, dirs in tree.items():
        tb += ext.encode() + b'\0'
        for d, items in dirs.items():
            tb += d.encode() + b'\0'
            for name, p in items:
                crc, o, ln = entries[p]
                tb += name.encode() + b'\0'
                tb += struct.pack('<IHHII', crc, 0, 0x7FFF, o, ln) + struct.pack('<H', 0xFFFF)
            tb += b'\0'
        tb += b'\0'
    tb += b'\0'
    with open(out_path, 'wb') as f:
        f.write(struct.pack('<III', 0x55AA1234, 1, len(tb)))
        f.write(tb)
        for p in order:
            data = norm[p][2]()
            assert len(data) == norm[p][0], p
            f.write(data)
    return len(order)


def from_vpk(pak, path):
    """lazy entry from a python-vpk VPK object"""
    e = pak[path]
    meta = pak.get_file_meta(path)
    ln = meta['preload_length'] + meta['file_length']
    return (ln, meta['crc32'], lambda: pak.get_file(path).read())
