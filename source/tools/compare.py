"""Side-by-side sheet of two screenshot folders (same file names), e.g. night vs day or old vs new build.

usage: python tools/compare.py <folder A> <folder B> <out.jpg> [--labels "Night" "Day"] [--width 960]
"""
import argparse
import glob
import os

from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument('a')
ap.add_argument('b')
ap.add_argument('out')
ap.add_argument('--labels', nargs=2, default=None)
ap.add_argument('--width', type=int, default=960, help='width of each image in the sheet')
args = ap.parse_args()
la, lb = args.labels or (os.path.basename(os.path.normpath(args.a)), os.path.basename(os.path.normpath(args.b)))

names = sorted(n for n in (os.path.basename(p) for p in glob.glob(os.path.join(args.a, '*.png')))
               if os.path.exists(os.path.join(args.b, n)))
if not names:
    raise SystemExit('no file names in common')
W = args.width
rows = []
for n in names:
    ims = [Image.open(os.path.join(d, n)).convert('RGB') for d in (args.a, args.b)]
    ims = [im.resize((W, round(im.height * W / im.width))) for im in ims]
    row = Image.new('RGB', (2 * W, max(im.height for im in ims)))
    row.paste(ims[0], (0, 0))
    row.paste(ims[1], (W, 0))
    d = ImageDraw.Draw(row)
    d.text((10, 10), '%s  %s' % (la, n), fill='yellow')
    d.text((W + 10, 10), '%s  %s' % (lb, n), fill='yellow')
    rows.append(row)
sheet = Image.new('RGB', (2 * W, sum(r.height for r in rows)))
y = 0
for r in rows:
    sheet.paste(r, (0, y))
    y += r.height
sheet.save(args.out, quality=85)
print(len(names), 'pairs ->', args.out)
