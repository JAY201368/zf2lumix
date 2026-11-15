"""Package the transparent master artwork for macOS and Windows."""
from pathlib import Path

from PIL import Image


def build_icons():
    assets = Path(__file__).resolve().parent / 'assets'
    with Image.open(assets / 'icon.png') as source:
        master = source.convert('RGBA').resize((1024, 1024), Image.Resampling.LANCZOS)
    master.save(assets / 'icon.icns', format='ICNS')
    master.save(assets / 'icon.ico', format='ICO',
                sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])


if __name__ == '__main__':
    build_icons()
