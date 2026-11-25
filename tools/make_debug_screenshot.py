#!/usr/bin/env python3
"""Draw a stand-in for a game screenshot with the `r_displayinfo` debug block in its corner.

    python tools/make_debug_screenshot.py out.png [width height]

For `7HillsLink.exe --screen-test out.png` on a PC without the game, and for the build,
which reads this picture with Windows' own text recognition inside the exe it just
made. The block is the one a real 4.10 screen showed at GrimHEX (numbers replaced),
right-aligned in the top-right corner in small light text on a dark, uneven
background, about the size it has at 2560×1440.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BLOCK = [
    ("CamDir:    4    0 -112 FOV: 84 Focal: 0.10 FStop: 64.0", "w"),
    ("Zone: ObjectContainer-000 Pos: 1.00m -2.00m -3.00m", "w"),
    ("Zone: OOC_Stanton_2c_Yela Pos: -500.0000km 300.0000km -2000.00m", "w"),
    ("Zone: SolarSystem_926344131032 Pos: -19000000.0000km -2600000.0000km -2000.00m", "w"),
    ("Zone: Root Pos: -19000000.0000km -2600000.0000km -2000.00m", "w"),
    ("FPS 53.2 [51..54], - 18.8ms [18.5ms]", "y"),
    ("Server FPS 30.0 [29.1..30.7] - 33.3ms [32.5..34.3], Hitches: 0", "y"),
    ("Net: ping 34.0ms, loss 0.0% BwIn 251.9kbps, BwOut 81.9kbps", "w"),
    ("Working Set (OS): 20.96 GiB Committed (OS): 44.46 GiB", "o"),
    ("Graphics Renderer : Vulkan (FSR AA)", "w"),
    ("Current player location : GrimHEX (LZ : GrimHEX)", "w"),
    ("Planet:OOC_Stanton_2c_Yela (working) (Load Complete)", "w"),
    ("CamPos Planet Zone: -500000.000000 300000.000000 -2000.000000", "w"),
    ("Entities: 31089, PS: 0, QdBatches: 0, LB: 0", "w"),
]
COLOURS = {"w": (235, 235, 235), "y": (232, 214, 96), "o": (236, 150, 60)}
FONTS = [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]


def font(size: int):
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw(width: int = 2560, height: int = 1440) -> Image.Image:
    img = Image.new("RGB", (width, height), (14, 12, 12))
    d = ImageDraw.Draw(img)
    # Something behind the text, as in the game: dark panels, a red girder, a lit doorway.
    for i in range(0, width, 97):
        shade = 14 + (i * 7) % 22
        d.rectangle([i, 0, i + 60, height], fill=(shade, shade - 2, shade - 3))
    d.polygon([(int(width * 0.60), 0), (int(width * 0.66), 0), (int(width * 0.92), int(height * 0.45)), (int(width * 0.86), int(height * 0.45))], fill=(92, 26, 22))
    d.rectangle([int(width * 0.78), int(height * 0.05), int(width * 0.84), int(height * 0.16)], fill=(70, 96, 120))
    # The game writes the block right-aligned with a 13 px line pitch at 1440p.
    size = max(10, round(height * 12 / 1440))
    pitch = max(11, round(height * 12.8 / 1440))
    f = font(size)
    y = round(height * 0.004)
    for text, colour in BLOCK:
        w = d.textlength(text, font=f)
        d.text((width - 4 - w, y), text, font=f, fill=COLOURS[colour])
        y += pitch
    return img


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    size = (int(argv[1]), int(argv[2])) if len(argv) >= 3 else (2560, 1440)
    draw(*size).save(argv[0])
    print(f"wrote {argv[0]} ({size[0]}x{size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
