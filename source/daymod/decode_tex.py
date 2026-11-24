"""Decode a BC6H/other vtex_c to a float16 .npy and write a tonemapped preview PNG.
usage: decode_tex.py in.vtex_c out_prefix
"""
import sys
import numpy as np
from PIL import Image
from s2res import Texture
import bc6h


def decode_bc6_2d(raw, off, W, H, chunk_rows=128):
    bw, bh = W // 4, H // 4
    out = np.zeros((H, W, 3), dtype=np.float16)
    for r0 in range(0, bh, chunk_rows):
        r1 = min(bh, r0 + chunk_rows)
        buf = raw[off + r0 * bw * 16: off + r1 * bw * 16]
        px, _ = bc6h.decode(buf)
        out[r0 * 4:r1 * 4] = bc6h.blocks_to_image(px, bw, r1 - r0)
    return out


def tonemap(img, exposure=1.0):
    x = img.astype(np.float32) * exposure
    x = x / (1 + x)
    return (np.clip(x, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


if __name__ == '__main__':
    raw = open(sys.argv[1], 'rb').read()
    t = Texture(raw)
    print(t.describe())
    assert t.format == 'BC6H' and t.depth == 1
    img = decode_bc6_2d(raw, t.pixel_off, t.width, t.height)
    np.save(sys.argv[2] + '.npy', img)
    small = img.reshape(t.height // 4, 4, t.width // 4, 4, 3).astype(np.float32).mean((1, 3))
    Image.fromarray(tonemap(small, float(sys.argv[3]) if len(sys.argv) > 3 else 2.0)).save(sys.argv[2] + '_preview.png')
    f = img.astype(np.float32).reshape(-1, 3)
    nz = f[f.sum(1) > 1e-4]
    print('nonzero frac', len(nz) / len(f), 'mean', nz.mean(0), 'p50', np.percentile(nz, 50, axis=0), 'p99', np.percentile(nz, 99, axis=0), 'max', nz.max(0))
