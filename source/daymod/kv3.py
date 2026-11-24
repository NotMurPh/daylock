"""Binary KV3 (v4/v5) reader, port of the relevant parts of ValveResourceFormat BinaryKV3.cs."""
import struct
from compression import zstd
try:
    import lz4.block
except ImportError:
    lz4 = None

NULL, BOOLEAN, INT64, UINT64, DOUBLE, STRING, BINARY_BLOB, ARRAY, OBJECT, ARRAY_TYPED, INT32, UINT32, \
    BOOLEAN_TRUE, BOOLEAN_FALSE, INT64_ZERO, INT64_ONE, DOUBLE_ZERO, DOUBLE_ONE, FLOAT, INT16, UINT16, \
    INT8, UINT8, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER, UINT32_ZERO, UINT32_ONE = range(1, 28)


class Lane:
    def __init__(self, data, start, end):
        self.d, self.p, self.end = data, start, end

    def take(self, fmt):
        s = struct.calcsize(fmt)
        v = struct.unpack_from('<' + fmt, self.d, self.p)
        self.p += s
        return v[0] if len(v) == 1 else v

    def take_n(self, fmt, n):
        s = struct.calcsize(fmt) * n
        v = list(struct.unpack_from('<%d%s' % (n, fmt), self.d, self.p))
        self.p += s
        return v


class Bufs:
    def __init__(self):
        self.b1 = self.b2 = self.b4 = self.b8 = None


def _align(o, a):
    return (o + a - 1) // a * a


def lz4_block_decompress(src, size):
    """pure python LZ4 block decompressor"""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255: break
        dst += src[i:i + lit]; i += lit
        if i >= n or len(dst) >= size:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:
            for k in range(ml):
                dst.append(dst[start + k])
    return bytes(dst[:size])


def _decompress(method, data, size):
    if method == 0:
        return data[:size]
    if method == 1:
        if lz4 is not None:
            return lz4.block.decompress(data, uncompressed_size=size)
        return lz4_block_decompress(data, size)
    if method == 2:
        return zstd.decompress(data)
    raise ValueError(method)


def read(block: bytes):
    magic = struct.unpack_from('<I', block, 0)[0]
    ver = magic & 0xFF
    assert magic & 0xFFFFFF00 == 0x4B563300 and ver >= 4, hex(magic)
    p = 4 + 16
    method, dict_id, frame = struct.unpack_from('<IHH', block, p); p += 8
    cb1, cb4, cb8, ctypes = struct.unpack_from('<4i', block, p); p += 16
    p += 4  # countObjects, countArrays u16
    unc_total, comp_total, nblobs, blob_bytes = struct.unpack_from('<4i', block, p); p += 16
    cb2, blk_sizes = struct.unpack_from('<2i', block, p); p += 8
    assert ver == 5, 'only v5 implemented'
    (ub1, cmb1, ub2, cmb2, c1b2, c2b2, c4b2, c8b2, _nodes, cobj2, _arrs, _elems) = struct.unpack_from('<12i', block, p)
    p += 48
    if method == 0: cmb1, cmb2 = ub1, ub2
    buf1 = _decompress(method, block[p:p + cmb1], ub1); p += cmb1
    buf2 = _decompress(method, block[p:p + cmb2], ub2); p += cmb2
    blob_stream_start = p

    # buffer 1 lanes (auxiliary + strings)
    a = Bufs(); o = 0
    if cb1: a.b1 = Lane(buf1, o, o + cb1); o += cb1
    if cb2: o = _align(o, 2); a.b2 = Lane(buf1, o, o + cb2 * 2); o += cb2 * 2
    if cb4: o = _align(o, 4); a.b4 = Lane(buf1, o, o + cb4 * 4); o += cb4 * 4
    if cb8: o = _align(o, 8); a.b8 = Lane(buf1, o, o + cb8 * 8); o += cb8 * 8
    nstr = a.b4.take('i')
    strings = []
    for _ in range(nstr):
        e = buf1.index(b'\0', a.b1.p)
        strings.append(buf1[a.b1.p:e].decode('utf8', 'replace'))
        a.b1.p = e + 1

    # buffer 2
    b = Bufs(); o = cobj2 * 4
    objlens = Lane(buf2, 0, o)
    if c1b2: b.b1 = Lane(buf2, o, o + c1b2); o += c1b2
    if c2b2: o = _align(o, 2); b.b2 = Lane(buf2, o, o + c2b2 * 2); o += c2b2 * 2
    if c4b2: o = _align(o, 4); b.b4 = Lane(buf2, o, o + c4b2 * 4); o += c4b2 * 4
    if c8b2: o = _align(o, 8); b.b8 = Lane(buf2, o, o + c8b2 * 8); o += c8b2 * 8
    types = Lane(buf2, o, o + ctypes)
    o += ctypes
    blobs = []
    if nblobs:
        lens = struct.unpack_from('<%di' % nblobs, buf2, o); o += 4 * nblobs
        assert struct.unpack_from('<I', buf2, o)[0] == 0xFFEEDD00
        o += 4
        if method == 2:
            raw = zstd.decompress(block[p:p + (comp_total - cmb1 - cmb2)])
            p += comp_total - cmb1 - cmb2
        elif method == 0:
            raw = block[p:p + blob_bytes]; p += blob_bytes
        else:  # lz4 framed blobs: u16 compressed sizes follow in buf2
            raw = bytearray()
            for L in lens:
                got = 0
                while got < L:
                    cs = struct.unpack_from('<H', buf2, o)[0]; o += 2
                    chunk = lz4_block_decompress(block[p:p + cs], min(frame, L - got)); p += cs
                    raw += chunk; got += len(chunk)
            raw = bytes(raw)
        q = 0
        for L in lens:
            blobs.append(raw[q:q + L]); q += L
    blob_iter = iter(blobs)

    def rtype():
        t = types.take('B'); flag = 0
        if t & 0x80:
            flag = types.take('B')
        if t & 0x40:
            types.take('B')
        return t & 0x3F, flag

    def gs(i):
        return strings[i] if 0 <= i < len(strings) else ''

    def value(t, lane):
        if t == NULL: return None
        if t == BOOLEAN_TRUE: return True
        if t == BOOLEAN_FALSE: return False
        if t in (INT64_ZERO, UINT32_ZERO): return 0
        if t in (INT64_ONE, UINT32_ONE): return 1
        if t == DOUBLE_ZERO: return 0.0
        if t == DOUBLE_ONE: return 1.0
        if t == BOOLEAN: return lane.b1.take('B') != 0
        if t == INT8: return lane.b1.take('b')
        if t == UINT8: return lane.b1.take('B')
        if t == INT16: return lane.b2.take('h')
        if t == UINT16: return lane.b2.take('H')
        if t == INT32: return lane.b4.take('i')
        if t == UINT32: return lane.b4.take('I')
        if t == FLOAT: return lane.b4.take('f')
        if t == INT64: return lane.b8.take('q')
        if t == UINT64: return lane.b8.take('Q')
        if t == DOUBLE: return lane.b8.take('d')
        if t == STRING: return gs(b.b4.take('i'))
        if t == BINARY_BLOB: return next(blob_iter)
        if t == ARRAY:
            n = b.b4.take('i')
            out = []
            for _ in range(n):
                st, _f = rtype(); out.append(value(st, b))
            return out
        if t in (ARRAY_TYPED, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER):
            n = b.b4.take('i') if t == ARRAY_TYPED else b.b1.take('B')
            st, _f = rtype()
            el = a if t == ARRAY_TYPE_AUXILIARY_BUFFER else b
            return [value(st, el) for _ in range(n)]
        if t == OBJECT:
            n = objlens.take('i')
            d = {}
            for _ in range(n):
                st, _f = rtype()
                name = gs(b.b4.take('i'))
                d[name] = value(st, b)
            return d
        raise ValueError('type %d' % t)

    rt, _ = rtype()
    return value(rt, b)


def entities(lump):
    out = []
    for e in lump.get('m_entityKeyValues', []):
        kv = e.get('keyValues3Data')
        if kv is None:
            continue
        ent = dict(kv.get('values', kv))
        ent['__connections'] = e.get('m_connections', [])
        out.append(ent)
    return out
