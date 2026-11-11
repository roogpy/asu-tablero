"""Generate the PWA icons with the standard library only (no Pillow).

    python tools/make_icons.py

Writes icons/icon-192.png, icons/icon-512.png and icons/icon-maskable-512.png:
a rounded navy tile with a plane silhouette, 3x3 supersampled so the edges stay
smooth on an Android home screen.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "icons"

BACKGROUND = (11, 42, 67)  # deep navy, matches the app header
PLANE = (232, 242, 255)  # near white
SAMPLES = 3  # per axis

# Plane silhouette, nose up, in a 0..100 square.
PLANE_SHAPE = [
    (50, 6),
    (54, 14),
    (56, 32),
    (94, 58),
    (94, 67),
    (56, 55),
    (54, 78),
    (70, 89),
    (70, 95),
    (50, 89),
    (30, 95),
    (30, 89),
    (46, 78),
    (44, 55),
    (6, 67),
    (6, 58),
    (44, 32),
    (46, 14),
]


def inside_polygon(x: float, y: float, polygon) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < cross:
                inside = not inside
    return inside


def inside_rounded_square(x: float, y: float, size: float, radius: float) -> bool:
    if x < 0 or y < 0 or x > size or y > size:
        return False
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    dx = x - cx
    dy = y - cy
    return dx * dx + dy * dy <= radius * radius


def scaled(polygon, size: float, coverage: float):
    """Fit the 0..100 shape into `coverage` of a square of `size` pixels."""
    span = size * coverage
    offset = (size - span) / 2
    return [(offset + px * span / 100.0, offset + py * span / 100.0) for px, py in polygon]


def render(size: int, coverage: float, full_bleed: bool) -> bytes:
    plane = scaled(PLANE_SHAPE, size, coverage)
    radius = size * 0.22
    step = 1.0 / SAMPLES
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            hits_bg = 0
            hits_plane = 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    x = px + (sx + 0.5) * step
                    y = py + (sy + 0.5) * step
                    if full_bleed or inside_rounded_square(x, y, size, radius):
                        hits_bg += 1
                        if inside_polygon(x, y, plane):
                            hits_plane += 1
            total = SAMPLES * SAMPLES
            # Composite plane over background over white, by coverage.
            bg_weight = hits_bg / total
            plane_weight = hits_plane / total
            for channel in range(3):
                value = 255.0 * (1.0 - bg_weight)
                value += BACKGROUND[channel] * (bg_weight - plane_weight)
                value += PLANE[channel] * plane_weight
                row.append(max(0, min(255, int(round(value)))))
        rows.append(bytes(row))
    return png_bytes(size, size, rows)


def png_bytes(width: int, height: int, rows) -> bytes:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("icon-192.png", 192, 0.62, False),
        ("icon-512.png", 512, 0.62, False),
        ("icon-maskable-512.png", 512, 0.46, True),
    ]
    for name, size, coverage, full_bleed in jobs:
        path = ICON_DIR / name
        path.write_bytes(render(size, coverage, full_bleed))
        print("wrote icons/" + name + " (" + str(path.stat().st_size) + " bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
