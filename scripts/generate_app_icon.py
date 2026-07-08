from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ICON_PATH = ROOT / "assets" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def rounded_rectangle(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_icon(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    rounded_rectangle(
        shadow_draw,
        tuple(round(value * scale) for value in (20, 24, 236, 240)),
        round(54 * scale),
        (0, 0, 0, 80),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, round(8 * scale))))
    image.alpha_composite(shadow)

    draw = ImageDraw.Draw(image)
    rounded_rectangle(
        draw,
        tuple(round(value * scale) for value in (18, 16, 238, 236)),
        round(54 * scale),
        (4, 118, 103, 255),
    )
    rounded_rectangle(
        draw,
        tuple(round(value * scale) for value in (30, 28, 226, 224)),
        round(44 * scale),
        (11, 163, 137, 255),
    )

    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    rounded_rectangle(
        highlight_draw,
        tuple(round(value * scale) for value in (42, 34, 214, 116)),
        round(34 * scale),
        (255, 255, 255, 42),
    )
    image.alpha_composite(highlight)

    draw = ImageDraw.Draw(image)
    center_x = round(128 * scale)
    center_y = round(132 * scale)
    bar_width = max(2, round(14 * scale))
    gap = max(3, round(11 * scale))
    heights = [50, 78, 108, 78, 50]
    for index, height in enumerate(heights):
        x = center_x + round((index - 2) * (bar_width + gap))
        top = center_y - round(height * scale / 2)
        bottom = center_y + round(height * scale / 2)
        draw.rounded_rectangle(
            (x - bar_width // 2, top, x + bar_width // 2, bottom),
            radius=max(1, round(7 * scale)),
            fill=(246, 255, 252, 255),
        )

    # Bridge arc and endpoint: visible at 32px+, harmless at tray size.
    if size >= 32:
        arc_box = tuple(round(value * scale) for value in (62, 76, 194, 206))
        draw.arc(arc_box, start=205, end=335, fill=(190, 250, 237, 255), width=max(2, round(10 * scale)))
        radius = max(3, round(14 * scale))
        dot_x = round(198 * scale)
        dot_y = round(168 * scale)
        draw.ellipse(
            (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
            fill=(255, 210, 84, 255),
        )

    # Subtle diagonal shine gives the icon shape without hurting small sizes.
    shine = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shine_draw = ImageDraw.Draw(shine)
    points = [
        (round(46 * scale), round(30 * scale)),
        (round(95 * scale), round(30 * scale)),
        (round(222 * scale), round(158 * scale)),
        (round(222 * scale), round(207 * scale)),
    ]
    shine_draw.polygon(points, fill=(255, 255, 255, 22))
    image.alpha_composite(shine)

    if size <= 24:
        # Tiny tray sizes need sharper contrast than the larger icon.
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=140, threshold=1))

    return image


def main() -> None:
    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    images = [draw_icon(size) for size in SIZES]
    images[-1].save(ICON_PATH, sizes=[(size, size) for size in SIZES], append_images=images[:-1])
    print(ICON_PATH)


if __name__ == "__main__":
    main()
