"""Typed binary KV3 v5 reader + writer (round-trip safe).

Nodes:
  Scalar: S(t, flag, value)              t = KV3 node type id
  Array:  A(t, flag, items, sub_t, sub_flag)   t in (ARRAY, ARRAY_TYPED, ARRAY_TYPE_BYTE_LENGTH);
          for typed arrays items are plain python values of type sub_t, for ARRAY items are nodes
  Object: O(flag, [(name, node), ...])
"""
import struct
from compression import zstd
from kv3 import lz4_block_decompress, _align, Lane, Bufs, \
    NULL, BOOLEAN, INT64, UINT64, DOUBLE, STRING, BINARY_BLOB, ARRAY, OBJECT, ARRAY_TYPED, INT32, UINT32, \
    BOOLEAN_TRUE, BOOLEAN_FALSE, INT64_ZERO, INT64_ONE, DOUBLE_ZERO, DOUBLE_ONE, FLOAT, INT16, UINT16, \
    INT8, UINT8, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER, UINT32_ZERO, UINT32_ONE


class S:
    __slots__ = ('t', 'flag', 'v')
    def __init__(self, t, flag, v): self.t, self.flag, self.v = t, flag, v
    def __repr__(self): return f'S({self.t},{self.flag},{self.v!r})'


class A:
    __slots__ = ('t', 'flag', 'items', 'st', 'sflag')
    def __init__(self, t, flag, items, st=None, sflag=0): self.t, self.flag, self.items, self.st, self.sflag = t, flag, items, st, sflag
    def __repr__(self): return f'A({self.t},{self.items!r})'


class O:
    __slots__ = ('flag', 'items')
    def __init__(self, flag, items): self.flag, self.items = flag, items
    def get(self, k, d=None):
        for n, v in self.items:
            if n == k: return v
        return d
    def set(self, k, node):
        for i, (n, v) in enumerate(self.items):
            if n == k:
                self.items[i] = (k, node); return
        self.items.append((k, node))
    def __repr__(self): return f'O({self.items!r})'


LANE1 = {BOOLEAN: 'B', INT8: 'b', UINT8: 'B'}
LANE2 = {INT16: 'h', UINT16: 'H'}
LANE4 = {INT32: 'i', UINT32: 'I', FLOAT: 'f'}
LANE8 = {INT64: 'q', UINT64: 'Q', DOUBLE: 'd'}
CONST = {NULL: None, BOOLEAN_TRUE: True, BOOLEAN_FALSE: False, INT64_ZERO: 0, INT64_ONE: 1,
         DOUBLE_ZERO: 0.0, DOUBLE_ONE: 1.0, UINT32_ZERO: 0, UINT32_ONE: 1}


def _dec(method, data, size):
    if method == 0: return data[:size]
    if method == 1: return lz4_block_decompress(data, size)
    return zstd.decompress(data)


def _read_v4(block):
    """KV3 v4: one buffer holding lanes, strings and types (materials use this)."""
    guid = block[4:20]
    p = 20
    method, dict_id, frame = struct.unpack_from('<IHH', block, p); p += 8
    cb1, cb4, cb8, ctypes = struct.unpack_from('<4i', block, p); p += 16
    p += 4
    unc_total, comp_total, nblobs, blob_bytes = struct.unpack_from('<4i', block, p); p += 16
    cb2, blk_sizes = struct.unpack_from('<2i', block, p); p += 8
    if method == 0:
        buf = block[p:p + unc_total]; p += unc_total
    elif method == 2:
        buf = zstd.decompress(block[p:p + comp_total]); p += comp_total
    else:
        buf = lz4_block_decompress(block[p:p + comp_total], unc_total); p += comp_total
    b = Bufs(); o = 0
    if cb1: b.b1 = Lane(buf, o, o + cb1); o += cb1
    if cb2: o = _align(o, 2); b.b2 = Lane(buf, o, o + cb2 * 2); o += cb2 * 2
    if cb4: o = _align(o, 4); b.b4 = Lane(buf, o, o + cb4 * 4); o += cb4 * 4
    if cb8: o = _align(o, 8); b.b8 = Lane(buf, o, o + cb8 * 8); o += cb8 * 8
    else: o = _align(o, 8)
    nstr = b.b4.take('i')
    sstart = o; strings = []
    for _ in range(nstr):
        e = buf.index(b'\0', o); strings.append(buf[o:e].decode('utf8')); o = e + 1
    tlen = ctypes - (o - sstart)
    types = Lane(buf, o, o + tlen); o += tlen
    blobs = []
    if nblobs:
        lens = struct.unpack_from('<%di' % nblobs, buf, o)
        raw = buf[unc_total:] if method == 2 else block[p:p + blob_bytes]
        k = 0
        for L in lens: blobs.append(raw[k:k + L]); k += L
    return guid, b, b, b.b4, strings, types, iter(blobs)


def read(block):
    magic = struct.unpack_from('<I', block, 0)[0]
    if magic == 0x4B563304:
        guid, a, b, objlens, strings, types, bi = _read_v4(block)
        return guid, _parse(a, b, objlens, strings, types, bi)
    assert magic == 0x4B563305, hex(magic)
    guid = block[4:20]
    p = 20
    method, dict_id, frame = struct.unpack_from('<IHH', block, p); p += 8
    cb1, cb4, cb8, ctypes = struct.unpack_from('<4i', block, p); p += 16
    p += 4
    unc_total, comp_total, nblobs, blob_bytes = struct.unpack_from('<4i', block, p); p += 16
    cb2, blk_sizes = struct.unpack_from('<2i', block, p); p += 8
    (ub1, cmb1, ub2, cmb2, c1b2, c2b2, c4b2, c8b2, _n, cobj2, _a, _e) = struct.unpack_from('<12i', block, p); p += 48
    if method == 0: cmb1, cmb2 = ub1, ub2  # Valve stores 0 as compressed size when uncompressed
    buf1 = _dec(method, block[p:p + cmb1], ub1); p += cmb1
    buf2 = _dec(method, block[p:p + cmb2], ub2); p += cmb2
    a = Bufs(); o = 0
    if cb1: a.b1 = Lane(buf1, o, o + cb1); o += cb1
    if cb2: o = _align(o, 2); a.b2 = Lane(buf1, o, o + cb2 * 2); o += cb2 * 2
    if cb4: o = _align(o, 4); a.b4 = Lane(buf1, o, o + cb4 * 4); o += cb4 * 4
    if cb8: o = _align(o, 8); a.b8 = Lane(buf1, o, o + cb8 * 8); o += cb8 * 8
    nstr = a.b4.take('i')
    strings = []
    for _ in range(nstr):
        e = buf1.index(b'\0', a.b1.p); strings.append(buf1[a.b1.p:e].decode('utf8')); a.b1.p = e + 1
    b = Bufs(); o = cobj2 * 4
    objlens = Lane(buf2, 0, o)
    if c1b2: b.b1 = Lane(buf2, o, o + c1b2); o += c1b2
    if c2b2: o = _align(o, 2); b.b2 = Lane(buf2, o, o + c2b2 * 2); o += c2b2 * 2
    if c4b2: o = _align(o, 4); b.b4 = Lane(buf2, o, o + c4b2 * 4); o += c4b2 * 4
    if c8b2: o = _align(o, 8); b.b8 = Lane(buf2, o, o + c8b2 * 8); o += c8b2 * 8
    types = Lane(buf2, o, o + ctypes); o += ctypes
    blobs = []
    if nblobs:
        lens = struct.unpack_from('<%di' % nblobs, buf2, o); o += 4 * nblobs + 4
        if method == 2:
            raw = zstd.decompress(block[p:p + comp_total - cmb1 - cmb2])
        elif method == 0:
            raw = block[p:p + blob_bytes]
        else:
            raw = bytearray(); q = p
            for L in lens:
                got = 0
                while got < L:
                    cs = struct.unpack_from('<H', buf2, o)[0]; o += 2
                    ch = lz4_block_decompress(block[q:q + cs], min(frame, L - got)); q += cs
                    raw += ch; got += len(ch)
            raw = bytes(raw)
        k = 0
        for L in lens: blobs.append(raw[k:k + L]); k += L
    bi = iter(blobs)
    return guid, _parse(a, b, objlens, strings, types, bi)


def _parse(a, b, objlens, strings, types, bi):
    def rtype():
        t = types.take('B'); flag = 0
        if t & 0x80: flag = types.take('B')
        if t & 0x40: types.take('B')
        return t & 0x3F, flag

    def gs(i): return strings[i] if 0 <= i < len(strings) else ''

    def scalar(t, lane):
        if t in CONST: return CONST[t]
        if t in LANE1: return lane.b1.take(LANE1[t])
        if t in LANE2: return lane.b2.take(LANE2[t])
        if t in LANE4: return lane.b4.take(LANE4[t])
        if t in LANE8: return lane.b8.take(LANE8[t])
        if t == STRING: return gs(b.b4.take('i'))
        if t == BINARY_BLOB: return next(bi)
        raise ValueError(t)

    def node(t, flag):
        if t == OBJECT:
            n = objlens.take('i'); items = []
            for _ in range(n):
                st, sf = rtype(); name = gs(b.b4.take('i')); items.append((name, node(st, sf)))
            return O(flag, items)
        if t == ARRAY:
            n = b.b4.take('i'); items = []
            for _ in range(n):
                st, sf = rtype(); items.append(node(st, sf))
            return A(ARRAY, flag, items)
        if t in (ARRAY_TYPED, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER):
            n = b.b4.take('i') if t == ARRAY_TYPED else b.b1.take('B')
            st, sf = rtype()
            lane = a if t == ARRAY_TYPE_AUXILIARY_BUFFER else b
            if st in (OBJECT, ARRAY, ARRAY_TYPED, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER):
                items = [node(st, sf) for _ in range(n)]
            else:
                items = [scalar(st, lane) for _ in range(n)]
            # normalise aux arrays to plain typed arrays on write
            return A(ARRAY_TYPED if t == ARRAY_TYPE_AUXILIARY_BUFFER else t, flag, items,
                     ARRAY_TYPED if st == ARRAY_TYPE_AUXILIARY_BUFFER else st, sf)
        return S(t, flag, scalar(t, b))

    rt, rf = rtype()
    return node(rt, rf)


class _W:
    def __init__(self):
        self.strings = []; self.sidx = {}
        self.objlens = []; self.b1 = bytearray(); self.b2 = bytearray(); self.b4 = bytearray(); self.b8 = bytearray()
        self.types = bytearray(); self.blobs = []
        self.nobj = 0; self.narr = 0; self.nelem = 0; self.nnodes = 0

    def s(self, txt):
        if txt not in self.sidx:
            self.sidx[txt] = len(self.strings); self.strings.append(txt)
        return self.sidx[txt]

    def ty(self, t, flag):
        if flag:
            self.types += bytes([t | 0x80, flag])
        else:
            self.types.append(t)

    def scalar(self, t, v):
        if t in CONST: return
        if t in LANE1: self.b1 += struct.pack('<' + LANE1[t], int(v)); return
        if t in LANE2: self.b2 += struct.pack('<' + LANE2[t], v); return
        if t in LANE4: self.b4 += struct.pack('<' + LANE4[t], v); return
        if t in LANE8: self.b8 += struct.pack('<' + LANE8[t], v); return
        if t == STRING: self.b4 += struct.pack('<i', self.s(v) if v != '' else -1) if False else struct.pack('<i', self.s(v)); return
        if t == BINARY_BLOB: self.blobs.append(v); return
        raise ValueError(t)

    def node(self, n):
        self.nnodes += 1
        if isinstance(n, O):
            self.ty(OBJECT, n.flag)
            self.objlens.append(len(n.items)); self.nobj += 1
            for name, child in n.items:
                self.member(name, child)
        elif isinstance(n, A):
            self.ty(n.t, n.flag); self.narr += 1; self.nelem += len(n.items)
            if n.t == ARRAY:
                self.b4 += struct.pack('<i', len(n.items))
                for c in n.items: self.node(c)
            else:
                if n.t == ARRAY_TYPED: self.b4 += struct.pack('<i', len(n.items))
                else: self.b1.append(len(n.items))
                self.ty(n.st, n.sflag)
                for c in n.items:
                    if isinstance(c, (O, A, S)): self.node_body(c)
                    else: self.scalar(n.st, c)
        else:
            self.ty(n.t, n.flag); self.scalar(n.t, n.v)

    def node_body(self, n):
        # element of a typed array of containers: type already written once
        if isinstance(n, O):
            self.objlens.append(len(n.items)); self.nobj += 1
            for name, child in n.items: self.member(name, child)
        elif isinstance(n, A):
            # element of a typed array whose element type is itself an array: the outer type byte was
            # written once; the inner array writes its length and (if typed) its own element type
            self.narr += 1; self.nelem += len(n.items)
            if n.t == ARRAY:
                self.b4 += struct.pack('<i', len(n.items))
                for c in n.items: self.node(c)
            else:
                if n.t == ARRAY_TYPED: self.b4 += struct.pack('<i', len(n.items))
                else: self.b1.append(len(n.items))
                self.ty(n.st, n.sflag)
                for c in n.items:
                    if isinstance(c, (O, A, S)): self.node_body(c)
                    else: self.scalar(n.st, c)
        else:
            self.scalar(n.t, n.v)

    def member(self, name, child):
        # order matters: type first (types stream), then name index in b4, then value
        if isinstance(child, O):
            self.ty(OBJECT, child.flag); self.b4 += struct.pack('<i', self.s(name))
            self.objlens.append(len(child.items)); self.nobj += 1; self.nnodes += 1
            for n2, c2 in child.items: self.member(n2, c2)
        elif isinstance(child, A):
            self.ty(child.t, child.flag); self.b4 += struct.pack('<i', self.s(name))
            self.narr += 1; self.nelem += len(child.items); self.nnodes += 1
            if child.t == ARRAY:
                self.b4 += struct.pack('<i', len(child.items))
                for c in child.items: self.node(c)
            else:
                if child.t == ARRAY_TYPED: self.b4 += struct.pack('<i', len(child.items))
                else: self.b1.append(len(child.items))
                self.ty(child.st, child.sflag)
                for c in child.items:
                    if isinstance(c, (O, A, S)): self.node_body(c)
                    else: self.scalar(child.st, c)
        else:
            self.ty(child.t, child.flag); self.b4 += struct.pack('<i', self.s(name)); self.nnodes += 1
            self.scalar(child.t, child.v)


def _pad(buf, a):
    while len(buf) % a: buf.append(0)


def write(guid, root, compress=True):
    w = _W()
    w.node(root)
    # buffer1: strings in b1, string count in b4
    sb = bytearray()
    for s in w.strings: sb += s.encode('utf8') + b'\0'
    buf1 = bytearray(sb)
    _pad(buf1, 4)
    buf1 += struct.pack('<i', len(w.strings))
    # buffer2
    buf2 = bytearray()
    for n in w.objlens: buf2 += struct.pack('<i', n)
    buf2 += w.b1
    if w.b2: _pad(buf2, 2); buf2 += w.b2
    if w.b4: _pad(buf2, 4); buf2 += w.b4
    if w.b8: _pad(buf2, 8); buf2 += w.b8
    buf2 += w.types
    if w.blobs:
        for bl in w.blobs: buf2 += struct.pack('<i', len(bl))
    buf2 += struct.pack('<I', 0xFFEEDD00)
    blob_raw = b''.join(w.blobs)
    if compress:
        method = 2
        c1 = zstd.compress(bytes(buf1)); c2 = zstd.compress(bytes(buf2))
        cblob = zstd.compress(blob_raw) if w.blobs else b''
    else:
        method = 0; c1, c2, cblob = bytes(buf1), bytes(buf2), blob_raw
    hdr = struct.pack('<I', 0x4B563305) + guid
    hdr += struct.pack('<IHH', method, 0, 0)
    hdr += struct.pack('<4i', len(sb), 1, 0, len(w.types))
    hdr += struct.pack('<HH', min(w.nobj, 0xFFFF), min(w.narr, 0xFFFF))
    hdr += struct.pack('<4i', len(buf1) + len(buf2), len(c1) + len(c2) + len(cblob), len(w.blobs), len(blob_raw))
    hdr += struct.pack('<2i', 0, 0)  # countBytes2 (buffer1), block compressed sizes
    hdr += struct.pack('<12i', len(buf1), len(c1), len(buf2), len(c2), len(w.b1), len(w.b2) // 2,
                       len(w.b4) // 4, len(w.b8) // 8, w.nnodes, len(w.objlens), w.narr, w.nelem)
    out = hdr + c1 + c2
    if w.blobs:
        out += cblob + struct.pack('<I', 0xFFEEDD00)
    return out


def to_py(n):
    if isinstance(n, O): return {k: to_py(v) for k, v in n.items}
    if isinstance(n, A): return [to_py(x) if isinstance(x, (O, A, S)) else x for x in n.items]
    return n.v
