#!/usr/bin/env python3
"""Turn a portrait into the ASCII art shown on the profile card.

Best input: a PNG with a transparent background (a "cutout"), so only the
person is drawn. A normal photo also works, but the background is drawn too.

    python scripts/make_ascii.py assets/portrait-cutout.png
    python today.py --offline        # redraw the two SVG cards

Writes ascii_dark.txt (bright areas = heavy characters, for the dark card)
and ascii_light.txt (dark areas = heavy characters, for the light card).
"""
import argparse
from PIL import Image, ImageOps, ImageFilter

RAMP = " .:-=+*#%@"                # light -> heavy
CELL_ASPECT = 0.5                # a monospace cell is about twice as tall as wide
FLOOR = 0.12                     # minimum ink inside the subject, keeps the silhouette


def to_ascii(path, cols, heavy_is_bright, gamma):
    src = Image.open(path).convert("RGBA")
    alpha = src.getchannel("A")
    grey = ImageOps.autocontrast(src.convert("L"), cutoff=1)
    grey = grey.filter(ImageFilter.UnsharpMask(radius=4, percent=140))
    rows = round(cols * src.height / src.width * CELL_ASPECT)
    grey = grey.resize((cols, rows), Image.LANCZOS)
    alpha = alpha.resize((cols, rows), Image.LANCZOS)
    lines = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            if alpha.getpixel((x, y)) < 110:
                line += " "
                continue
            v = grey.getpixel((x, y)) / 255
            ink = (v if heavy_is_bright else 1 - v) ** gamma
            ink = FLOOR + (1 - FLOOR) * ink
            line += RAMP[min(len(RAMP) - 1, int(ink * len(RAMP)))]
        lines.append(line.rstrip())
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    p.add_argument("--cols", type=int, default=112, help="characters per line (default 112)")
    p.add_argument("--gamma-dark", type=float, default=1.7, help="dark card: <1 = more ink, >1 = less ink")
    p.add_argument("--gamma-light", type=float, default=1.1, help="light card: <1 = more ink, >1 = less ink")
    a = p.parse_args()
    open("ascii_dark.txt", "w").write(to_ascii(a.image, a.cols, True, a.gamma_dark))
    open("ascii_light.txt", "w").write(to_ascii(a.image, a.cols, False, a.gamma_light))
    print("wrote ascii_dark.txt and ascii_light.txt")
