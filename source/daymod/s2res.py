"""Minimal reader/writer for Source 2 compiled resources (vtex_c etc.)."""
import struct

FMT = {0: 'UNKNOWN', 1: 'DXT1', 2: 'DXT5', 3: 'I8', 4: 'RGBA8888', 5: 'R16', 6: 'RG1616',
       7: 'RGBA16161616', 8: 'R16F', 9: 'RG1616F', 10: 'RGBA16161616F', 11: 'R32F',
       12: 'RG3232F', 13: 'RGB323232F', 14: 'RGBA32323232F', 15: 'JPEG_RGBA8888',
       16: 'PNG_RGBA8888', 17: 'JPEG_DXT5', 18: 'PNG_DXT5', 19: 'BC6H', 20: 'BC7',
       21: 'ATI2N', 22: 'IA88', 23: 'ETC2', 24: 'ETC2_EAC', 25: 'R11_EAC', 26: 'RG11_EAC',
       27: 'ATI1N', 28: 'BGRA8888'}

# bytes per 4x4 block for block formats, bytes per pixel for others
BLOCK = {'DXT1': 8, 'DXT5': 16, 'BC6H': 16, 'BC7': 16, 'ATI2N': 16, 'ATI1N': 8}
BPP = {'I8': 1, 'RGBA8888': 4, 'BGRA8888': 4, 'R16': 2, 'RG1616': 4, 'RGBA16161616': 8,
       'R16F': 2, 'RG1616F': 4, 'RGBA16161616F': 8, 'R32F': 4, 'RG3232F': 8,
       'RGB323232F': 12, 'RGBA32323232F': 16, 'IA88': 2}

EXTRA = {1: 'FALLBACK_BITS', 2: 'SHEET', 3: 'FILL_TO_POWER_OF_TWO', 4: 'COMPRESSED_MIP_SIZE',
         5: 'CUBEMAP_RADIANCE_SH', 6: 'METADATA'}


class Resource:
    def __init__(self, data: bytes):
        self.raw = data
        self.file_size, self.header_ver, self.ver = struct.unpack_from('<IHH', data, 0)
        boff, bcount = struct.unpack_from('<II', data, 8)
        pos = 8 + boff
        self.blocks = []
        for i in range(bcount):
            t = data[pos:pos + 4].decode('ascii')
            off, size = struct.unpack_from('<II', data, pos + 4)
            self.blocks.append([t, pos + 4 + off, size])
            pos += 12

    def block(self, t):
        for b in self.blocks:
            if b[0] == t:
                return b
        return None


class Texture:
    def __init__(self, data: bytes):
        self.res = Resource(data)
        t, off, size = self.res.block('DATA')
        self.data_off, self.data_size = off, size
        d = data
        (self.version, self.flags) = struct.unpack_from('<HH', d, off)
        self.reflectivity = struct.unpack_from('<4f', d, off + 4)
        self.width, self.height, self.depth = struct.unpack_from('<HHH', d, off + 20)
        self.format_id, self.mips = struct.unpack_from('<BB', d, off + 26)
        self.format = FMT.get(self.format_id, str(self.format_id))
        self.picmip0 = struct.unpack_from('<I', d, off + 28)[0]
        eoff_pos = off + 32
        eoff, ecount = struct.unpack_from('<II', d, eoff_pos)
        p = eoff_pos + eoff
        self.extra = []
        for i in range(ecount):
            et, eo, es = struct.unpack_from('<III', d, p)
            self.extra.append((EXTRA.get(et, et), p + 4 + eo, es))
            p += 12
        self.pixel_off = off + size  # pixel data starts right after DATA block
        self.raw = data
        self.compressed_mips = None
        for name, eo, es in self.extra:
            if name == 'COMPRESSED_MIP_SIZE':
                a, b, c = struct.unpack_from('<III', d, eo)  # isCompressed, mipsOffset, mipsCount
                cnt = c
                arr = struct.unpack_from('<%di' % cnt, d, eo + 8 + b)
                self.compressed_mips = (a, arr)

    @property
    def is_cube(self):
        return bool(self.flags & 0x0004)  # CUBE_TEXTURE

    def mip_size(self, level):
        w = max(1, self.width >> level)
        h = max(1, self.height >> level)
        dep = max(1, self.depth >> level) if not (self.flags & 0x0004) else self.depth
        faces = 6 if self.is_cube else 1
        if self.format in BLOCK:
            bw, bh = (w + 3) // 4, (h + 3) // 4
            s = bw * bh * BLOCK[self.format]
        else:
            s = w * h * BPP[self.format]
        return s * dep * faces

    def describe(self):
        lines = [f'ver={self.version} flags=0x{self.flags:04x} {self.width}x{self.height}x{self.depth} '
                 f'{self.format} mips={self.mips} filesize={self.res.file_size} rawlen={len(self.raw)} '
                 f'pixel_off={self.pixel_off}',
                 f'blocks={[(b[0], b[1], b[2]) for b in self.res.blocks]}',
                 f'extra={self.extra}', f'compressed_mips={self.compressed_mips}',
                 f'sum mips={sum(self.mip_size(i) for i in range(self.mips))} '
                 f'avail={len(self.raw) - self.pixel_off}']
        return '\n'.join(lines)


def rerl(data):
    """External resource names referenced by a compiled resource (RERL block)."""
    r = Resource(data)
    b = r.block('RERL')
    if not b:
        return []
    _, off, size = b
    roff, cnt = struct.unpack_from('<II', data, off)
    p = off + roff
    out = []
    for i in range(cnt):
        e = p + i * 16
        noff = struct.unpack_from('<I', data, e + 8)[0]
        s = e + 8 + noff
        out.append(data[s:data.index(b'\0', s)].decode())
    return out
