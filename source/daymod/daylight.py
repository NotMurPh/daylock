"""Night -> day conversion of baked HDR lighting (per texel, linear RGB).

Every baked texel is split into the light sources that made it:
    N = a*SKY + c*LAMP + d*RED + residual
  SKY  : the blue night-sky ambient      (measured from the lightmap)
  LAMP : ordinary warm street/room lamps
  RED  : orange/red lights (fires, base lights)
  residual : anything else (green/cyan neon ...)
Then rebuilt for daytime:
    D = a*(sky_gain*DAY_SKY + bounce_gain*SUN_BOUNCE)          sky visibility -> daylight fill
      + lamp_gain(vis) * (c*LAMP + d*RED)                      lamps: off outdoors, dimmed indoors
      + neon_gain(vis) * residual
"""
import numpy as np

SKY = np.array([0.165, 0.50, 1.0], np.float32)
LAMP = np.array([1.0, 0.69, 0.47], np.float32)
RED = np.array([1.0, 0.28, 0.11], np.float32)
M = np.stack([SKY, LAMP, RED], 1)          # columns
MINV = np.linalg.inv(M).astype(np.float32)

DEFAULT = dict(
    day_sky=(0.80, 0.89, 1.00),     # colour of daylight sky fill
    sun_bounce=(1.00, 0.90, 0.76),  # warm light bounced from sunlit surfaces
    sky_gain=2.6,
    bounce_gain=1.6,
    vis_ref=0.05,                   # sky amount that counts as "fully outdoors"
    lamp_in=0.45, lamp_out=0.06,    # lamp strength kept indoors / outdoors
    lamp_desat=0.0,                 # 0 = keep lamp colour, 1 = neutral white
    neon_in=0.45, neon_out=0.15,
    sun_gain=0.0,                   # fake sunlight on surfaces open to the sky
    sun_color=(1.00, 0.91, 0.78),
    sun_lo=0.03, sun_hi=0.15,       # sky-openness range over which the fake sun fades in
    floor=0.004,                    # tiny ambient everywhere so nothing is pitch black
    max_out=64.0,
    scale=1.0,                      # overall multiplier on the result
)

V2 = dict(DEFAULT, sky_gain=2.4, bounce_gain=0.8, lamp_in=0.30, lamp_desat=0.5, neon_in=0.35,
          sun_gain=0.9)

# V3: shaded areas get a real daytime fill instead of dim lamp light
V3 = dict(V2, lamp_in=0.08, lamp_out=0.02, neon_in=0.10, neon_out=0.05,
          fill_gain=0.42, fill_ref=0.20, fill_color=(0.92, 0.95, 1.00), floor=0.03)

# V4: dim interiors lifted (faint night light still becomes usable daylight fill)
V4 = dict(V3, fill_gamma=0.6, floor=0.05)

# V5: stronger, sooner-saturating fill -> darker districts (docks, Hidden King base) closer to bright ones
V5 = dict(V4, fill_gain=0.55, fill_ref=0.10, floor=0.07)

# V6: balance districts - less sky/sun on wide-open areas (bright marble courtyards), same fill for shaded ones
V6 = dict(V5, sky_gain=2.0, sun_gain=0.6)

# V7: + soft brightness ceiling
V7 = dict(V6, knee=0.9, knee_gain=1.25)

# V8: districts closer together - more shade fill (covered docks / Hidden King base), less open-sky light
V8 = dict(V7, fill_gain=0.68, sky_gain=1.8)


def convert(rgb, p=DEFAULT):
    """rgb: float32 array (..., 3) of linear HDR night lighting -> day lighting (same shape)"""
    shp = rgb.shape
    x = np.asarray(rgb, np.float32).reshape(-1, 3)
    coef = x @ MINV.T                      # (n,3): a, c, d
    coef = np.clip(coef, 0, None)
    recon = coef @ M.T
    resid = np.clip(x - recon, 0, None)
    a, c, d = coef[:, 0:1], coef[:, 1:2], coef[:, 2:3]
    vis = np.clip(a / p['vis_ref'], 0, 1)
    vis = vis * vis * (3 - 2 * vis)        # smoothstep
    lamp_g = p['lamp_in'] + (p['lamp_out'] - p['lamp_in']) * vis
    neon_g = p['neon_in'] + (p['neon_out'] - p['neon_in']) * vis
    day = a * (p['sky_gain'] * np.array(p['day_sky'], np.float32) + p['bounce_gain'] * np.array(p['sun_bounce'], np.float32))
    lamp_col = LAMP * (1 - p['lamp_desat']) + np.float32(0.8) * p['lamp_desat']
    day += lamp_g * (c * lamp_col + d * RED)
    day += neon_g * resid
    if p.get('fill_gain', 0) > 0:
        # any light that reached this surface at night means it is reachable by daylight bounce:
        # turn it into a neutral, saturating daylight fill (no lamp pools, no black street canyons)
        energy = c + d + resid.sum(1, keepdims=True) / 3 + a
        f = 1 - np.exp(-np.power(energy / p['fill_ref'], p.get('fill_gamma', 1.0)))
        day += p['fill_gain'] * f * np.array(p['fill_color'], np.float32)
    if p['sun_gain'] > 0:
        t = np.clip((a - p['sun_lo']) / (p['sun_hi'] - p['sun_lo']), 0, 1)
        t = t * t * (3 - 2 * t)
        day += p['sun_gain'] * t * np.array(p['sun_color'], np.float32)
    day += p['floor'] * (x.sum(1, keepdims=True) > 0)
    if p.get('knee'):
        # soft ceiling: mids stay, very bright (wide-open courtyards) get compressed -> districts closer together
        k = p['knee']; g = p.get('knee_gain', 1.0)
        L = (day * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(1, keepdims=True) + 1e-6
        Lc = g * k * (1 - np.exp(-L / k))
        day = day * (Lc / L)
    return np.clip(day * p.get('scale', 1.0), 0, p['max_out']).reshape(shp)
