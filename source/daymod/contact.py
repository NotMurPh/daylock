"""contact.py <folder> <out.jpg> [cols] : grid of all PNG screenshots in a folder, labelled."""
import glob, os, sys
from PIL import Image, ImageDraw
fs = sorted(glob.glob(os.path.join(sys.argv[1], '*.png')))
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 3
W, H = 640, 360
rows = (len(fs) + cols - 1) // cols
sheet = Image.new('RGB', (W * cols, H * rows), 'black')
d = ImageDraw.Draw(sheet)
for i, f in enumerate(fs):
    im = Image.open(f).convert('RGB').resize((W, H))
    x, y = (i % cols) * W, (i // cols) * H
    sheet.paste(im, (x, y))
    d.text((x + 6, y + 6), os.path.basename(f), fill='yellow')
sheet.save(sys.argv[2], quality=88)
