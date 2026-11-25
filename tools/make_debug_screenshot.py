#!/usr/bin/env python3
"""Draw a stand-in for a game screenshot with the `r_displayinfo` debug block in its corner.

    python tools/make_debug_screenshot.py out.png [width height]

For `7HillsLink.exe --screen-test out.png` on a PC without the game, and for the build,
which reads this picture with Windows' own text recognition inside the exe it just
made.

The block is the one a real 4.10 screen showed at GrimHEX, line for line, with every
number, id and server name replaced. It is drawn the way the game drew it there:
right-aligned in the top-right corner, a 12 px monospace face (7.2 px a letter, 13 px a
line), white, yellow and orange on a dark picture that is not flat, with a lit sign
running through the middle of the block. The text is the same size in pixels whatever
the size of the picture, as the game's debug text is as far as is known.
"""

from __future__ import annotations

import random
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
    ("Session: 00000000-0000-0000-0000-000000000000", "w"),
    ("ShardId: pub_euw1b_00000000_000", "w"),
    ("[100.0|100.0|99.9|99.8|98.8|91.3|25.2]", "y"),
    ("Phys: 0.0ms Stall: 0.0ms Event: 0.0ms", "w"),
    ("Server FPS 30.0 [29.1..30.7] - 33.3ms [32.5..34.3], Hitches: 0", "y"),
    ("Server: pub-euw1b-sc-alpha-0000-00000000-game-000, restarts 0, pop. [shard 100, srv 5]", "w"),
    ("Net: ping 34.0ms, loss 0.0% BwIn 251.935kbps, BwOut 81.967kbps", "w"),
    ("RL: entities: 18735, tick: 0.29ms, MTSync: 0.77ms", "w"),
    ("ServerTime: Sat Nov 21 00:09:31 2026", "w"),
    ("UniverseTime: Mon May  2 00:57:10 2991", "w"),
    ("Working Set (OS): 20.96 GiB Committed (OS): 44.46 GiB", "o"),
    ("Render: MT: 18.5ms RT: 4.0ms GPU: 18.4ms", "o"),
    ("Graphics Renderer : Vulkan (FSR AA)", "w"),
    ("GI: Off, Reflections: Half-Res, Hardware Tracing", "w"),
    ("VRAM(MB): 10756 / 15569", "w"),
    ("VRAM Demoted: 3113, OSBudget: 15569 MB", "o"),
    ("Current player location : GrimHEX  (LZ : GrimHEX)", "w"),
    ("Planet:OOC_Stanton_2c_Yela (working) (Load Complete)", "w"),
    ("CamPos Planet Zone: -500000.000000 300000.000000 -2000.000000", "w"),
]
COLOURS = {"w": (235, 235, 235), "y": (232, 214, 96), "o": (236, 150, 60)}
TEXT_PX, LINE_PX = 12, 13
# The game's face looks like Bitstream Vera Sans Mono: DejaVu Sans Mono is that face, and
# Lucida Console the closest one every Windows has (same width, plain zero).
FONTS = [r"C:\Windows\Fonts\DejaVuSansMono.ttf", r"C:\Windows\Fonts\lucon.ttf", r"C:\Windows\Fonts\consola.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]


def font(size: int):
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw(width: int = 2560, height: int = 1440) -> Image.Image:
    img = Image.new("RGB", (width, height), (10, 9, 9))
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    # Behind the text, as in the game: dark panels of uneven shade, a few lit edges, grain.
    for x in range(0, width, 97):
        shade = 10 + (x * 7) % 26
        d.rectangle([x, 0, x + 60, height], fill=(shade, shade - 2, shade - 3))
    for _ in range(40):
        x, y = rnd.randrange(width), rnd.randrange(height)
        d.line([x, y, x + rnd.randrange(40, 400), y + rnd.randrange(-30, 30)], fill=(rnd.randrange(30, 70),) * 3, width=1)
    d.polygon([(int(width * 0.60), 0), (int(width * 0.66), 0), (int(width * 0.92), int(height * 0.45)), (int(width * 0.86), int(height * 0.45))], fill=(70, 22, 18))
    # A lit sign through the middle of the block (lines 6 to 13), as a ship's name plate was on the real screen.
    top = 6 * LINE_PX
    sign = Image.new("RGBA", (640, 92), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sign)
    sd.rectangle([0, 14, 639, 78], fill=(40, 70, 90, 150), outline=(90, 150, 170, 200))
    sd.text((70, 26), "CARGO BAY 03 SERVICE", font=font(34), fill=(150, 200, 221, 235))
    sign = sign.rotate(8, expand=True, resample=Image.BICUBIC)
    img.paste(sign, (width - 700, top - 30), sign)
    tile = Image.frombytes("L", (256, 256), rnd.randbytes(256 * 256)).point(lambda v: v // 12)     # the same grain every time
    grain = Image.new("L", (width, height))
    for gx in range(0, width, 256):
        for gy in range(0, height, 256):
            grain.paste(tile, (gx, gy))
    img = Image.composite(Image.new("RGB", (width, height), (70, 70, 70)), img, grain)
    d = ImageDraw.Draw(img)
    f = font(TEXT_PX)
    y = 2
    for text, colour in BLOCK:
        w = d.textlength(text, font=f)
        d.text((width - 4 - w, y), text, font=f, fill=COLOURS[colour])
        y += LINE_PX
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
