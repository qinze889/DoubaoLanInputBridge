import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_app_icon.py"


def load_icon_generator():
    spec = importlib.util.spec_from_file_location("icon_generator_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_icon_uses_ink_ivory_and_vermilion_without_legacy_yellow_gloss():
    generator = load_icon_generator()
    image = generator.draw_icon(256)
    pixels = list(image.get_flattened_data())

    assert any(red > 110 and green < 85 and blue < 75 and alpha > 200 for red, green, blue, alpha in pixels)
    assert any(red > 225 and green > 220 and blue > 200 and alpha > 200 for red, green, blue, alpha in pixels)
    assert (255, 210, 84, 255) not in pixels
    assert generator.ICON_STYLE == "ink-bamboo-wave"


def test_icon_generator_writes_web_tauri_and_windows_assets(tmp_path):
    generator = load_icon_generator()

    outputs = generator.write_icon_assets(tmp_path)

    expected = {
        tmp_path / "assets" / "app.ico",
        tmp_path / "assets" / "app-icon-master.png",
        tmp_path / "desktop" / "public" / "app-icon.png",
        tmp_path / "desktop" / "src-tauri" / "icons" / "32x32.png",
        tmp_path / "desktop" / "src-tauri" / "icons" / "64x64.png",
        tmp_path / "desktop" / "src-tauri" / "icons" / "128x128.png",
        tmp_path / "desktop" / "src-tauri" / "icons" / "128x128@2x.png",
        tmp_path / "desktop" / "src-tauri" / "icons" / "icon.png",
        tmp_path / "desktop" / "src-tauri" / "icons" / "icon.ico",
    }
    assert set(outputs) == expected
    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)
