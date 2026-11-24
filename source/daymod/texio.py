"""Decode / re-encode BC6H textures (2D, 3D volumes, cube arrays) keeping the original vtex_c header."""
import os
import numpy as np
from multiprocessing import Pool
from s2res import Texture
import bc6h

CHUNK = 32768  # blocks per work item


def _dec(buf):
    return bc6h.decode(buf)[0].astype(np.float16)


def _enc(px):
    return bc6h.encode(px.astype(np.float32))


def _pool():
    return Pool(max(1, min(8, (os.cpu_count() or 4) - 2)))


def decode_all_blocks(raw, tex, pool=None):
    """returns (nblocks,16,3) float16 for the whole pixel payload (all mips, slices, faces)"""
    data = raw[tex.pixel_off:]
    n = len(data) // 16
    parts = [data[i * 16:min(n, i + CHUNK) * 16] for i in range(0, n, CHUNK)]
    own = pool is None
    pool = pool or _pool()
    try:
        out = list(pool.imap(_dec, parts, chunksize=1))
    finally:
        if own:
            pool.close()
    return np.concatenate(out)


def encode_all_blocks(px, pool=None):

    own = pool is None
    pool = pool or _pool()
    try:
        out = list(pool.imap(_enc, (px[i:i + CHUNK] for i in range(0, len(px), CHUNK)), chunksize=1))
    finally:
        if own:
            pool.close()
    return b''.join(out)


def rebuild(raw, tex, new_payload):
    assert len(new_payload) == len(raw) - tex.pixel_off
    return raw[:tex.pixel_off] + new_payload


def blocks_to_2d(px, W, H):
    return bc6h.blocks_to_image(px, W // 4, H // 4)


def img2d_to_blocks(img):
    return bc6h.image_to_blocks(img)
