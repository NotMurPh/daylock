"""Colour-grade a BC7 colour texture (vtex_c, uncompressed mip chain stored smallest mip first):
decode mip 0, apply saturation/gain in display space, rebuild every mip and re-encode."""
import numpy as np
import etcpak, texture2ddecoder
from PIL import Image
from s2res import Texture


def grade_rgb(rgb, sat=1.0, gain=1.0):
    f = rgb.astype(np.float32)
    lum = f @ np.array([0.299, 0.587, 0.114], np.float32)
    f = lum[..., None] + (f - lum[..., None]) * sat
    return np.clip(f * gain, 0, 255).astype(np.uint8)


def decode_mip0(raw):
    t = Texture(raw)
    assert t.format == 'BC7' and not (t.compressed_mips and t.compressed_mips[0]), (t.format, t.compressed_mips)
    W, H = t.width, t.height
    m0 = raw[t.pixel_off:][-(W * H):]          # BC7: 1 byte / pixel; mip 0 is last
    bgra = np.frombuffer(texture2ddecoder.decode_bc7(m0, W, H), np.uint8).reshape(H, W, 4)
    return t, bgra[..., [2, 1, 0, 3]].copy()    # -> RGBA


def grade_texture(raw, sat=1.0, gain=1.0):
    t, rgba = decode_mip0(raw)
    rgba[..., :3] = grade_rgb(rgba[..., :3], sat, gain)
    W, H = t.width, t.height
    # colour and alpha are resized separately: alpha is a data mask here (0 on painted panels), and PIL's RGBA
    # resize premultiplies by alpha, which turned those panels black in every smaller mip
    rgb_im, a_im = Image.fromarray(rgba[..., :3], 'RGB'), Image.fromarray(rgba[..., 3], 'L')
    mips = []
    for i in range(t.mips):
        w, h = max(4, W >> i), max(4, H >> i)
        if i == 0:
            m = rgba
        else:
            m = np.dstack([np.asarray(rgb_im.resize((w, h), Image.LANCZOS)), np.asarray(a_im.resize((w, h), Image.LANCZOS))])
        mips.append(etcpak.compress_bc7(np.ascontiguousarray(m).tobytes(), w, h))
    payload = b''.join(reversed(mips))
    assert len(payload) == len(raw) - t.pixel_off, (len(payload), len(raw) - t.pixel_off)
    return raw[:t.pixel_off] + payload
