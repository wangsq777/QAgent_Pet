#!/usr/bin/env python3
"""Generate desktop application icons from the project logo."""

from pathlib import Path

from PIL import Image


DESKTOP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = DESKTOP_DIR.parent
SOURCE = PROJECT_DIR / "logo.png"
OUTPUT_DIR = DESKTOP_DIR / "assets"


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Product logo not found: {SOURCE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE) as source:
        icon = source.convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)

    icon.save(OUTPUT_DIR / "icon.png", format="PNG", optimize=True)
    icon.save(
        OUTPUT_DIR / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    icon.save(
        OUTPUT_DIR / "icon.icns",
        format="ICNS",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )

    print(f"Generated product icons in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
