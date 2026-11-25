#!/usr/bin/env python3
"""Generate NUA POS native app icons with only the Python standard library.

Run from any directory: python scripts/generate_app_icons.py
This is intentionally explicit in each platform build workflow. Do not run
it during Vercel backend installation or use remote asset generation.
"""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
BURGUNDY = (60, 11, 33, 255)
IVORY = (246, 240, 229, 255)
VIOLET = (139, 92, 246, 255)
TRANSPARENT = (0, 0, 0, 0)

# A portable pixel-grid wordmark avoids system-font/license dependencies in
# release CI. NUA stays legible on a 48px launcher, with POS on its own line.
GLYPHS = {
    "N": ("10001", "11001", "10101", "10101", "10011", "10001", "10001"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
}


def png(width, height, pixels):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(
            ">I", zlib.crc32(kind + content) & 0xFFFFFFFF)
    rows = b"".join(b"\0" + pixels[y * width * 4:(y + 1) * width * 4]
                    for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows, level=9)) + chunk(b"IEND", b""))


def render(size, adaptive=False):
    canvas = bytearray(bytes(TRANSPARENT if adaptive else BURGUNDY) * (size * size))
    def block(x, y, w, h, color):
        left, top = max(0, round(x)), max(0, round(y))
        right, bottom = min(size, round(x + w)), min(size, round(y + h))
        if right <= left or bottom <= top:
            return
        line = bytes(color) * (right - left)
        for row in range(top, bottom):
            offset = (row * size + left) * 4
            canvas[offset:offset + len(line)] = line

    # Adaptive Android icons reserve an extended transparent safe area for
    # OEM circles/masks. The native background colour is set in values XML.
    factor = 0.70 if adaptive else 1.0
    def coord(x):
        return size * (0.5 + (x - 0.5) * factor)

    def word(word, y, cell_width, color):
        unit = size * cell_width * factor
        spacing = unit
        span = (5 * len(word) + len(word) - 1) * unit
        left = (size - span) / 2
        top = coord(y)
        for idx, char in enumerate(word):
            for row, bits in enumerate(GLYPHS[char]):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        block(left + idx * 6 * unit + col * unit,
                              top + row * unit, unit * 0.93, unit * 0.93, color)

    word("NUA", 0.255, 0.040, IVORY)
    block(coord(0.27), coord(0.59), size * 0.46 * factor, max(1, size * 0.008 * factor), VIOLET)
    word("POS", 0.67, 0.0235, IVORY)
    # A small intelligence point references NUA's distinctive intelligent A.
    center_x, center_y, radius = coord(0.81), coord(0.19), size * 0.034 * factor
    for y in range(max(0, int(center_y - radius)), min(size, int(center_y + radius + 2))):
        for x in range(max(0, int(center_x - radius)), min(size, int(center_x + radius + 2))):
            if (x + 0.5 - center_x) ** 2 + (y + 0.5 - center_y) ** 2 <= radius ** 2:
                offset = (y * size + x) * 4
                canvas[offset:offset + 4] = bytes(VIOLET)
    return png(size, size, canvas)


def icon_file(sizes):
    # ICO entries can store PNG-compressed images, including 256x256.
    images = [render(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    data = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    for size, image in zip(sizes, images):
        data += struct.pack("<BBBBHHII", 0 if size == 256 else size,
                            0 if size == 256 else size, 0, 0, 1, 32,
                            len(image), offset)
        offset += len(image)
    return bytes(data) + b"".join(images)


def write(relative, data):
    destination = ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print("NUA POS icon:", relative, len(data), "bytes")


def main():
    densities = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for density, size in densities.items():
        base = f"frontend/android/app/src/main/res/mipmap-{density}"
        write(f"{base}/ic_launcher.png", render(size))
        write(f"{base}/ic_launcher_round.png", render(size))
        write(f"{base}/ic_launcher_foreground.png", render(size, adaptive=True))
    write("frontend/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png", render(1024))
    write("apps/windows/build/icon.ico", icon_file([16, 24, 32, 48, 64, 128, 256]))
    write("apps/windows/build/icon.png", render(256))
    for size in (16, 32, 48):
        write(f"frontend/public/favicon-{size}x{size}.png", render(size))
    write("frontend/public/favicon.ico", icon_file([16, 32, 48]))
    write("frontend/public/android-chrome-192x192.png", render(192))
    write("frontend/public/android-chrome-512x512.png", render(512))
    write("frontend/public/apple-touch-icon-180x180.png", render(180))


if __name__ == "__main__":
    main()
