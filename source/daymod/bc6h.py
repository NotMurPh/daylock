"""Vectorised BC6H (unsigned, UF16) decoder + single-region encoder in numpy.

decode(blocks_bytes, nblocks) -> float32 array (nblocks, 16, 3) of linear HDR values
encode(rgb float32 (nblocks,16,3)) -> bytes
"""
import numpy as np

# --- mode descriptions -------------------------------------------------------
# (mode_bits_value, n_mode_bits, layout, precision, delta(r,g,b), transformed, regions)
_RAW = {
    1: (0b00, 2, "gy4 by4 bz4 rw9:0 gw9:0 bw9:0 rx4:0 gz4 gy3:0 gx4:0 bz0 gz3:0 bx4:0 bz1 by3:0 ry4:0 bz2 rz4:0 bz3", 10, (5, 5, 5), True, 2),
    2: (0b01, 2, "gy5 gz4 gz5 rw6:0 bz0 bz1 by4 gw6:0 by5 bz2 gy4 bw6:0 bz3 bz5 bz4 rx5:0 gy3:0 gx5:0 gz3:0 bx5:0 by3:0 ry5:0 rz5:0", 7, (6, 6, 6), True, 2),
    3: (0b00010, 5, "rw9:0 gw9:0 bw9:0 rx4:0 rw10 gy3:0 gx3:0 gw10 bz0 gz3:0 bx3:0 bw10 bz1 by3:0 ry4:0 bz2 rz4:0 bz3", 11, (5, 4, 4), True, 2),
    4: (0b00110, 5, "rw9:0 gw9:0 bw9:0 rx3:0 rw10 gz4 gy3:0 gx4:0 gw10 gz3:0 bx3:0 bw10 bz1 by3:0 ry3:0 bz0 bz2 rz3:0 gy4 bz3", 11, (4, 5, 4), True, 2),
    5: (0b01010, 5, "rw9:0 gw9:0 bw9:0 rx3:0 rw10 by4 gy3:0 gx3:0 gw10 bz0 gz3:0 bx4:0 bw10 by3:0 ry3:0 bz1 bz2 rz3:0 bz4 bz3", 11, (4, 4, 5), True, 2),
    6: (0b01110, 5, "rw8:0 by4 gw8:0 gy4 bw8:0 bz4 rx4:0 gz4 gy3:0 gx4:0 bz0 gz3:0 bx4:0 bz1 by3:0 ry4:0 bz2 rz4:0 bz3", 9, (5, 5, 5), True, 2),
    7: (0b10010, 5, "rw7:0 gz4 by4 gw7:0 bz2 gy4 bw7:0 bz3 bz4 rx5:0 gy3:0 gx4:0 bz0 gz3:0 bx4:0 bz1 by3:0 ry5:0 rz5:0", 8, (6, 5, 5), True, 2),
    8: (0b10110, 5, "rw7:0 bz0 by4 gw7:0 gy5 gy4 bw7:0 gz5 bz4 rx4:0 gz4 gy3:0 gx5:0 gz3:0 bx4:0 bz1 by3:0 ry4:0 bz2 rz4:0 bz3", 8, (5, 6, 5), True, 2),
    9: (0b11010, 5, "rw7:0 bz1 by4 gw7:0 by5 gy4 bw7:0 bz5 bz4 rx4:0 gz4 gy3:0 gx4:0 bz0 gz3:0 bx5:0 by3:0 ry4:0 bz2 rz4:0 bz3", 8, (5, 5, 6), True, 2),
    10: (0b11110, 5, "rw5:0 gz4 bz0 bz1 by4 gw5:0 gy5 by5 bz2 gy4 bw5:0 gz5 bz3 bz5 bz4 rx5:0 gy3:0 gx5:0 gz3:0 bx5:0 by3:0 ry5:0 rz5:0", 6, (6, 6, 6), False, 2),
    11: (0b00011, 5, "rw9:0 gw9:0 bw9:0 rx9:0 gx9:0 bx9:0", 10, (10, 10, 10), False, 1),
    12: (0b00111, 5, "rw9:0 gw9:0 bw9:0 rx8:0 rw10 gx8:0 gw10 bx8:0 bw10", 11, (9, 9, 9), True, 1),
    13: (0b01011, 5, "rw9:0 gw9:0 bw9:0 rx7:0 rw11 rw10 gx7:0 gw11 gw10 bx7:0 bw11 bw10", 12, (8, 8, 8), True, 1),
    14: (0b01111, 5, "rw9:0 gw9:0 bw9:0 rx3:0 rw15 rw14 rw13 rw12 rw11 rw10 gx3:0 gw15 gw14 gw13 gw12 gw11 gw10 bx3:0 bw15 bw14 bw13 bw12 bw11 bw10", 16, (4, 4, 4), True, 1),
}

_FIELDS = {c + e: (ci, ei) for ci, c in enumerate('rgb') for ei, e in enumerate('wxyz')}


def _parse_layout(s, start):
    out = []  # (bitpos, channel, endpoint, bit)
    pos = start
    for tok in s.split():
        f = tok[:2]
        rng = tok[2:]
        if ':' in rng:
            hi, lo = map(int, rng.split(':'))
            bits = range(lo, hi + 1)
        else:
            bits = [int(rng)]
        for b in bits:
            out.append((pos, _FIELDS[f][0], _FIELDS[f][1], b))
            pos += 1
    return out, pos


MODES = {}
for m, (val, nb, lay, prec, delta, tr, reg) in _RAW.items():
    entries, end = _parse_layout(lay, nb)
    assert end == (82 if reg == 2 else 65) - (5 if reg == 2 else 0), (m, end)
    MODES[m] = dict(val=val, nb=nb, entries=entries, prec=prec, delta=delta, tr=tr, reg=reg)

PART2 = [0xCCCC, 0x8888, 0xEEEE, 0xECC8, 0xC880, 0xFEEC, 0xFEC8, 0xEC80, 0xC800, 0xFFEC, 0xFE80,
         0xE800, 0xFFE8, 0xFF00, 0xFFF0, 0xF000, 0xF710, 0x008E, 0x7100, 0x08CE, 0x008C, 0x7310,
         0x3100, 0x8CCE, 0x088C, 0x3110, 0x6666, 0x366C, 0x17E8, 0x0FF0, 0x718E, 0x399C]
ANCHOR2 = [15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15,
           15, 2, 8, 2, 2, 8, 8, 15, 2, 8, 2, 2, 8, 8, 2, 2]
PART_TAB = np.array([[(p >> i) & 1 for i in range(16)] for p in PART2], dtype=np.int64)
W3 = np.array([0, 9, 18, 27, 37, 46, 55, 64], dtype=np.int64)
W4 = np.array([0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64], dtype=np.int64)


def _bits(lo, hi, pos, n=1):
    """extract n bits at position pos from 128-bit (lo,hi) uint64 arrays"""
    out = np.zeros(lo.shape, dtype=np.int64)
    for k in range(n):
        p = pos + k
        if p < 64:
            b = (lo >> np.uint64(p)) & np.uint64(1)
        else:
            b = (hi >> np.uint64(p - 64)) & np.uint64(1)
        out |= b.astype(np.int64) << k
    return out


def _unq(c, prec):
    if prec >= 15:
        return c
    maxv = (1 << prec) - 1
    r = ((c << 16) + 0x8000) >> prec
    r = np.where(c == 0, 0, r)
    r = np.where(c == maxv, 0xFFFF, r)
    return r


def _sext(v, bits):
    s = 1 << (bits - 1)
    return (v ^ s) - s


def half_bits_to_float(h):
    return h.astype(np.uint16).view(np.float16).astype(np.float32)


def decode(buf, nblocks=None):
    a = np.frombuffer(buf, dtype=np.uint64)
    if nblocks is None:
        nblocks = len(a) // 2
    lo = a[0:2 * nblocks:2]
    hi = a[1:2 * nblocks:2]
    out_h = np.zeros((nblocks, 16, 3), dtype=np.int64)
    m2 = (lo & np.uint64(3)).astype(np.int64)
    m5 = (lo & np.uint64(31)).astype(np.int64)
    mode_of = np.full(nblocks, -1, dtype=np.int64)
    mode_of[m2 == 0] = 1
    mode_of[m2 == 1] = 2
    for m, d in MODES.items():
        if d['nb'] == 5:
            mode_of[(m2 >= 2) & (m5 == d['val'])] = m
    stats = {}
    for m, d in MODES.items():
        idx = np.nonzero(mode_of == m)[0]
        stats[m] = len(idx)
        if len(idx) == 0:
            continue
        l, h = lo[idx], hi[idx]
        n = len(idx)
        ep = np.zeros((n, 3, 4), dtype=np.int64)  # channel, endpoint(w,x,y,z)
        for pos, ch, e, b in d['entries']:
            ep[:, ch, e] |= _bits(l, h, pos) << b
        prec = d['prec']
        mask = (1 << prec) - 1
        nend = 4 if d['reg'] == 2 else 2
        if d['tr']:
            for ch in range(3):
                for e in range(1, nend):
                    ep[:, ch, e] = (ep[:, ch, 0] + _sext(ep[:, ch, e], d['delta'][ch])) & mask
        ep = _unq(ep[:, :, :nend], prec)
        if d['reg'] == 2:
            part = _bits(l, h, 77, 5)
            sub = PART_TAB[part]  # (n,16)
            anch = np.array(ANCHOR2)[part]
            ind = np.zeros((n, 16), dtype=np.int64)
            pos = np.full(n, 82, dtype=np.int64)
            # variable bit positions: pixel 0 and anchor2 have 2 bits
            for px in range(16):
                nb = np.where((px == 0) | (anch == px), 2, 3)
                # gather bits per block (positions vary)
                v = np.zeros(n, dtype=np.int64)
                for k in range(3):
                    p = pos + k
                    bit_lo = (l >> np.minimum(p, 63).astype(np.uint64)) & np.uint64(1)
                    bit_hi = (h >> np.maximum(p - 64, 0).astype(np.uint64)) & np.uint64(1)
                    bit = np.where(p < 64, bit_lo, bit_hi).astype(np.int64)
                    v |= np.where(k < nb, bit << k, 0)
                ind[:, px] = v
                pos += nb
            w = W3[ind]  # (n,16)
            e0 = np.where(sub[:, :, None] == 0, ep[:, None, :, 0].transpose(0, 1, 2), ep[:, None, :, 2])
            e1 = np.where(sub[:, :, None] == 0, ep[:, None, :, 1], ep[:, None, :, 3])
        else:
            ind = np.zeros((n, 16), dtype=np.int64)
            pos = 65
            for px in range(16):
                nb = 3 if px == 0 else 4
                ind[:, px] = _bits(l, h, pos, nb)
                pos += nb
            w = W4[ind]
            e0 = np.broadcast_to(ep[:, None, :, 0], (n, 16, 3))
            e1 = np.broadcast_to(ep[:, None, :, 1], (n, 16, 3))
        val = ((64 - w[:, :, None]) * e0 + w[:, :, None] * e1 + 32) >> 6
        out_h[idx] = (val * 31) >> 6
    return half_bits_to_float(out_h), stats


# --- encoder (single region modes 11..14) -------------------------------------
def _float_to_ubits(x):
    """float -> 'unquantized' 16-bit domain value (inverse of (u*31)>>6)"""
    x = np.clip(x, 0, 65504).astype(np.float16).view(np.uint16).astype(np.int64)
    # invert finish_unquantize: h = (u*31)>>6  -> u ~= h*64/31
    return np.minimum((x * 64 + 30) // 31, 0xFFFF)


def _quant(u, prec):
    """16-bit unquantized -> prec-bit endpoint (best-effort inverse of _unq)"""
    if prec >= 16:
        return u
    q = (u * ((1 << prec) - 1) + 0x7FFF) // 0xFFFF
    return np.clip(q, 0, (1 << prec) - 1)


def _put(lo, hi, pos, val, nbits):
    for k in range(nbits):
        p = pos + k
        b = ((val >> k) & 1).astype(np.uint64)
        if p < 64:
            lo |= b << np.uint64(p)
        else:
            hi |= b << np.uint64(p - 64)


def encode(rgb):
    """rgb: float32 (n,16,3) -> bytes of n BC6H blocks"""
    n = rgb.shape[0]
    u = _float_to_ubits(rgb).astype(np.float64)  # (n,16,3) in 0..65535 domain (log-ish)
    mean = u.mean(axis=1, keepdims=True)
    c = u - mean
    cov = np.einsum('npi,npj->nij', c, c)
    # principal axis by power iteration
    v = np.ones((n, 3)) / np.sqrt(3)
    for _ in range(8):
        v = np.einsum('nij,nj->ni', cov, v)
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    t = np.einsum('npi,ni->np', c, v)
    tmin, tmax = t.min(axis=1), t.max(axis=1)
    A = mean[:, 0, :] + tmin[:, None] * v
    B = mean[:, 0, :] + tmax[:, None] * v
    A = np.clip(np.rint(A), 0, 65535).astype(np.int64)
    B = np.clip(np.rint(B), 0, 65535).astype(np.int64)

    best_err = np.full(n, np.inf)
    best = None
    lo_all = np.zeros(n, dtype=np.uint64)
    hi_all = np.zeros(n, dtype=np.uint64)
    target = u
    for m in (11, 12, 13, 14):
        d = MODES[m]
        prec = d['prec']
        qa, qb = _quant(A, prec), _quant(B, prec)
        ok = np.ones(n, dtype=bool)
        if d['tr']:
            dl = qb - qa
            lim = 1 << (d['delta'][0] - 1)
            ok = np.all((dl >= -lim) & (dl < lim), axis=1)
        ua, ub = _unq(qa, prec), _unq(qb, prec)
        pal = ((64 - W4[None, :, None]) * ua[:, None, :] + W4[None, :, None] * ub[:, None, :] + 32) >> 6  # (n,16,3)
        ind = np.empty((n, 16), dtype=np.int64); err = np.empty(n)
        palf = pal.astype(np.float32); tf = target.astype(np.float32)
        for s0 in range(0, n, 4096):
            diff = tf[s0:s0 + 4096, :, None, :] - palf[s0:s0 + 4096, None, :, :]  # (b,16px,16pal,3)
            dist = (diff * diff).sum(-1)
            ib = dist.argmin(-1)
            ind[s0:s0 + 4096] = ib
            err[s0:s0 + 4096] = np.take_along_axis(dist, ib[:, :, None], 2)[:, :, 0].sum(1)
        err = np.where(ok, err, np.inf)
        better = err < best_err
        if not better.any():
            continue
        # anchor fix: pixel0 index must be < 8 -> swap endpoints
        swap = ind[:, 0] >= 8
        qa2 = np.where(swap[:, None], qb, qa)
        qb2 = np.where(swap[:, None], qa, qb)
        ind2 = np.where(swap[:, None], 15 - ind, ind)
        lo = np.zeros(n, dtype=np.uint64)
        hi = np.zeros(n, dtype=np.uint64)
        _put(lo, hi, 0, np.full(n, d['val'], dtype=np.int64), 5)
        ep = np.zeros((n, 3, 2), dtype=np.int64)
        ep[:, :, 0] = qa2
        if d['tr']:
            ep[:, :, 1] = (qb2 - qa2) & ((1 << d['delta'][0]) - 1)
        else:
            ep[:, :, 1] = qb2
        for pos, ch, e, b in d['entries']:
            _put(lo, hi, pos, (ep[:, ch, e] >> b) & 1, 1)
        pos = 65
        for px in range(16):
            nb = 3 if px == 0 else 4
            _put(lo, hi, pos, ind2[:, px], nb)
            pos += nb
        lo_all = np.where(better, lo, lo_all)
        hi_all = np.where(better, hi, hi_all)
        best_err = np.where(better, err, best_err)
    out = np.empty(2 * n, dtype=np.uint64)
    out[0::2] = lo_all
    out[1::2] = hi_all
    return out.tobytes()


# --- helpers for 2D images -----------------------------------------------------
def blocks_to_image(px, bw, bh):
    """(bw*bh,16,C) -> (bh*4, bw*4, C)"""
    C = px.shape[-1]
    return px.reshape(bh, bw, 4, 4, C).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, C)


def image_to_blocks(img):
    H, W, C = img.shape
    return img.reshape(H // 4, 4, W // 4, 4, C).transpose(0, 2, 1, 3, 4).reshape(-1, 16, C)
