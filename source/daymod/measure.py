"""measure.py <png...> : mean luminance + saturation of the scene area (HUD corners excluded)."""
import sys
import numpy as np
from PIL import Image

for f in sys.argv[1:]:
    a = np.asarray(Image.open(f).convert('RGB'), np.float32) / 255
    h, w, _ = a.shape
    region = a[int(h * 0.08):int(h * 0.62), int(w * 0.18):int(w * 0.78)]
    lum = region @ np.array([0.2126, 0.7152, 0.0722])
    sat = (region.max(-1) - region.min(-1)).mean()
    print(f'{f.split(chr(92))[-1].split("/")[-1]:40s} lum {lum.mean():.3f}  p10 {np.percentile(lum, 10):.3f}  sat {sat:.3f}')
