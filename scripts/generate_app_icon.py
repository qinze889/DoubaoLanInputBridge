from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ICON_STYLE = "ink-bamboo-wave"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _box(values: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
    return tuple(round(value * scale) for value in values)


def _draw_master(render_size: int = 1024) -> Image.Image:
    scale = render_size / 256
    image = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))

    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(_box((18, 22, 238, 242), scale), radius=round(49 * scale), fill=(0, 0, 0, 88))
    shadow = shadow.filter(ImageFilter.GaussianBlur(round(7 * scale)))
    image.alpha_composite(shadow)

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        _box((18, 16, 238, 236), scale),
        radius=round(49 * scale),
        fill=(16, 36, 31, 255),
        outline=(48, 104, 91, 255),
        width=max(2, round(5 * scale)),
    )
    draw.rounded_rectangle(
        _box((29, 27, 227, 225), scale),
        radius=round(39 * scale),
        outline=(36, 77, 68, 255),
        width=max(1, round(2 * scale)),
    )

    # Two bindings turn the waveform into a compact bamboo-slip manuscript mark.
    binding_color = (81, 211, 181, 255)
    draw.rounded_rectangle(_box((64, 106, 192, 114), scale), radius=round(4 * scale), fill=binding_color)
    draw.rounded_rectangle(_box((64, 160, 192, 168), scale), radius=round(4 * scale), fill=binding_color)

    ivory = (244, 241, 224, 255)
    centers = (78, 103, 128, 153, 178)
    heights = (72, 108, 142, 108, 72)
    bar_width = 14
    center_y = 137
    for center_x, height in zip(centers, heights, strict=True):
        top = center_y - height // 2
        bottom = center_y + height // 2
        draw.rounded_rectangle(
            _box((center_x - bar_width // 2, top, center_x + bar_width // 2, bottom), scale),
            radius=round(7 * scale),
            fill=ivory,
        )

    # A small seal links the app mark to the History banner without adding text at tray sizes.
    draw.rounded_rectangle(
        _box((184, 43, 218, 77), scale),
        radius=round(6 * scale),
        fill=(126, 47, 38, 255),
        outline=(239, 145, 127, 255),
        width=max(1, round(2 * scale)),
    )
    seal_ink = (255, 214, 204, 255)
    seal_width = max(1, round(2 * scale))
    draw.rectangle(_box((193, 52, 209, 68), scale), outline=seal_ink, width=seal_width)
    draw.line(_box((201, 52, 201, 68), scale), fill=seal_ink, width=seal_width)
    draw.line(_box((193, 60, 209, 60), scale), fill=seal_ink, width=seal_width)
    return image


def draw_icon(size: int) -> Image.Image:
    if size < 16:
        raise ValueError("icon size must be at least 16")
    image = _draw_master()
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 32:
        image = image.filter(ImageFilter.UnsharpMask(radius=0.8, percent=150, threshold=1))
    return image


def write_icon_assets(root: Path = ROOT) -> list[Path]:
    root = Path(root)
    assets_dir = root / "assets"
    public_dir = root / "desktop" / "public"
    tauri_dir = root / "desktop" / "src-tauri" / "icons"
    for directory in (assets_dir, public_dir, tauri_dir):
        directory.mkdir(parents=True, exist_ok=True)

    outputs = [
        assets_dir / "app.ico",
        assets_dir / "app-icon-master.png",
        public_dir / "app-icon.png",
        tauri_dir / "32x32.png",
        tauri_dir / "64x64.png",
        tauri_dir / "128x128.png",
        tauri_dir / "128x128@2x.png",
        tauri_dir / "icon.png",
        tauri_dir / "icon.ico",
    ]

    draw_icon(1024).save(outputs[1], format="PNG")
    draw_icon(128).save(outputs[2], format="PNG")
    draw_icon(32).save(outputs[3], format="PNG")
    draw_icon(64).save(outputs[4], format="PNG")
    draw_icon(128).save(outputs[5], format="PNG")
    draw_icon(256).save(outputs[6], format="PNG")
    draw_icon(512).save(outputs[7], format="PNG")
    for path in (outputs[0], outputs[8]):
        draw_icon(256).save(path, format="ICO", sizes=[(size, size) for size in ICO_SIZES])
    return outputs


def main() -> None:
    for path in write_icon_assets():
        print(path)


if __name__ == "__main__":
    main()
