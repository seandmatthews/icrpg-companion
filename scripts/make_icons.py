"""Generate PWA icons without Pillow: dark table, paper index card, red heart.

Pure-stdlib PNG writer + a supersampled implicit-curve heart. Run once;
the PNGs are committed so this is not a build dependency.

    python scripts/make_icons.py
"""

import math
import os
import struct
import zlib

BG = (0x16, 0x16, 0x1A)
PAPER = (0xF5, 0xF0, 0xE6)
RED = (0xC2, 0x2F, 0x2F)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client", "public", "icons")


def write_png(path: str, size: int, rows: list[list[tuple[int, int, int]]]) -> None:
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBB", *px) for px in row) for row in rows)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)  # atomic: an interrupted run leaves no truncated "committed" icon


def inside_heart(x: float, y: float) -> bool:
    """Classic implicit heart: (x²+y²−1)³ − x²y³ ≤ 0 (y up)."""
    a = x * x + y * y - 1.0
    return a * a * a - x * x * y * y * y <= 0.0


def render(size: int, ss: int = 2) -> list[list[tuple[int, int, int]]]:
    big = size * ss
    rows: list[list[tuple[int, int, int]]] = []
    cx = cy = big / 2.0
    card_w, card_h = big * 0.72, big * 0.72
    ang = math.radians(-6)
    cos, sin = math.cos(ang), math.sin(ang)
    heart_scale = big * 0.145  # heart spans ~±1.2 units → ~0.35 of the tile
    for py in range(big):
        row = []
        # y down in raster; flip for the heart's y-up math
        fy = py - cy
        for px in range(big):
            fx = px - cx
            # rotate into card frame
            x = fx * cos + fy * sin
            y = -fx * sin + fy * cos
            if abs(x) < card_w / 2 and abs(y) < card_h / 2:
                color = PAPER
                if inside_heart(x / heart_scale, -y / heart_scale):
                    color = RED
            else:
                color = BG
            row.append(color)
        rows.append(row)
    # box-downsample ss×ss
    out: list[list[tuple[int, int, int]]] = []
    for oy in range(size):
        orow = []
        for ox in range(size):
            r = g = b = 0
            for dy in range(ss):
                for dx in range(ss):
                    p = rows[oy * ss + dy][ox * ss + dx]
                    r += p[0]; g += p[1]; b += p[2]
            n = ss * ss
            orow.append((r // n, g // n, b // n))
        out.append(orow)
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        write_png(os.path.join(OUT, name), size, render(size))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
