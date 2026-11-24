"""Source 2 resource ids (RERL): MurmurHash64B, seed 0xEDABCDEF, over the lowercase resource path."""
M64 = 0xFFFFFFFFFFFFFFFF


def murmur64a(data: bytes, seed=0xEDABCDEF):
    m, r = 0xc6a4a7935bd1e995, 47
    h = (seed ^ (len(data) * m)) & M64
    nblocks = len(data) // 8
    for i in range(nblocks):
        k = int.from_bytes(data[i * 8:i * 8 + 8], 'little')
        k = (k * m) & M64; k ^= k >> r; k = (k * m) & M64
        h ^= k; h = (h * m) & M64
    tail = data[nblocks * 8:]
    if tail:
        h ^= int.from_bytes(tail, 'little'); h = (h * m) & M64
    h ^= h >> r; h = (h * m) & M64; h ^= h >> r
    return h


def resource_id(path: str):
    return murmur64a(path.lower().encode())


def murmur64b(data: bytes, seed=0xEDABCDEF):
    m, r, M = 0x5bd1e995, 24, 0xFFFFFFFF
    h1 = (seed ^ len(data)) & M; h2 = (seed >> 32) & M
    i, n = 0, len(data)
    while n >= 8:
        k1 = int.from_bytes(data[i:i + 4], 'little'); k1 = (k1 * m) & M; k1 ^= k1 >> r; k1 = (k1 * m) & M; h1 = (h1 * m) & M; h1 ^= k1
        k2 = int.from_bytes(data[i + 4:i + 8], 'little'); k2 = (k2 * m) & M; k2 ^= k2 >> r; k2 = (k2 * m) & M; h2 = (h2 * m) & M; h2 ^= k2
        i += 8; n -= 8
    if n >= 4:
        k1 = int.from_bytes(data[i:i + 4], 'little'); k1 = (k1 * m) & M; k1 ^= k1 >> r; k1 = (k1 * m) & M; h1 = (h1 * m) & M; h1 ^= k1
        i += 4; n -= 4
    if n > 0:
        h2 ^= int.from_bytes(data[i:i + n], 'little'); h2 = (h2 * m) & M
    h1 ^= h2 >> 18; h1 = (h1 * m) & M; h2 ^= h1 >> 22; h2 = (h2 * m) & M
    h1 ^= h2 >> 17; h1 = (h1 * m) & M; h2 ^= h1 >> 19; h2 = (h2 * m) & M
    return (h1 << 32) | h2


def resource_id(path: str):   # verified against RERL ids: MurmurHash64B, seed 0xEDABCDEF, lowercase path incl. extension
    return murmur64b(path.lower().encode())
