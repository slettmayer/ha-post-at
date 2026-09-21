"""Generate the HACS/Home Assistant brand icon for this integration.

The icon is an **original work** authored here and shipped under this
repository's MIT licence. It deliberately does **not** reproduce Österreichische
Post's post-horn mark, wordmark or brand yellow -- those are registered
trademarks of Österreichische Post AG and could not be relicensed under MIT.
See docs/tech/BRANDING.md for the reasoning.

The design is functional rather than brand-derived: a parcel drawn in
isometric projection with a delivery arc sweeping over it and terminating in a
waypoint. That is exactly what this integration reports -- a parcel, and where
it is on its way to you.

Run:
    pip install Pillow
    python scripts/generate_brand_icon.py

Writes custom_components/post_at/brand/icon.png (256px) and icon@2x.png (512px).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SUPERSAMPLE = 4
OUT_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "post_at" / "brand"
)

# Background squircle: a dark slate that reads on both light and dark HA themes.
BG_TOP = (44, 52, 66)
BG_BOTTOM = (20, 25, 34)

# Parcel faces. A warm amber, deliberately several steps away from Post's
# saturated lemon brand yellow -- see docs/tech/BRANDING.md.
BOX_TOP = (232, 168, 84)
BOX_LEFT = (186, 124, 56)
BOX_RIGHT = (150, 96, 42)
TAPE = (247, 214, 166)

# The delivery arc and its waypoint.
ARC = (150, 200, 245)
WAYPOINT = (210, 232, 255)

CORNER_RADIUS = 0.22


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """Blend two colours top-to-bottom across a square image."""
    mask = Image.linear_gradient("L").resize((size, size), Image.LANCZOS)
    return Image.composite(
        Image.new("RGB", (size, size), bottom),
        Image.new("RGB", (size, size), top),
        mask,
    )


def _tint(size: int, colour: tuple, alpha: Image.Image) -> Image.Image:
    """Build an RGBA layer of one flat colour carrying `alpha`."""
    layer = Image.new("RGBA", (size, size), (*colour, 0))
    layer.putalpha(alpha)
    return layer


def _iso(cx: float, cy: float, x: float, y: float, z: float, unit: float) -> tuple:
    """Project a point from box space into the 2:1 isometric plane.

    `x` runs to the lower right, `y` to the lower left, `z` straight up --
    the usual game-art isometric basis, which keeps the three visible faces
    distinguishable without any shading tricks.
    """
    return (
        cx + (x - y) * unit,
        cy + (x + y) * unit * 0.5 - z * unit,
    )


def _draw_parcel(draw: ImageDraw.ImageDraw, n: int) -> None:
    """Draw the isometric parcel, three visible faces plus a tape band."""
    unit = n * 0.155
    cx, cy = n * 0.5, n * 0.605
    half, height = 1.0, 1.15

    def point(x, y, z):
        return _iso(cx, cy, x, y, z, unit)

    # Top face, then the two visible side faces.
    top = [
        point(-half, -half, height),
        point(half, -half, height),
        point(half, half, height),
        point(-half, half, height),
    ]
    left = [
        point(-half, half, height),
        point(half, half, height),
        point(half, half, 0),
        point(-half, half, 0),
    ]
    right = [
        point(half, -half, height),
        point(half, half, height),
        point(half, half, 0),
        point(half, -half, 0),
    ]
    draw.polygon(left, fill=(*BOX_LEFT, 255))
    draw.polygon(right, fill=(*BOX_RIGHT, 255))
    draw.polygon(top, fill=(*BOX_TOP, 255))

    # Tape across the top face, running along the y axis so it reads as a seam.
    band = 0.16
    draw.polygon(
        [
            point(-band, -half, height),
            point(band, -half, height),
            point(band, half, height),
            point(-band, half, height),
        ],
        fill=(*TAPE, 255),
    )
    # ...and continuing down the left face, the way real tape wraps an edge.
    draw.polygon(
        [
            point(-band, half, height),
            point(band, half, height),
            point(band, half, 0),
            point(-band, half, 0),
        ],
        fill=(*TAPE, 190),
    )


def _arc_mask(n: int) -> Image.Image:
    """An 'L' mask holding the delivery arc sweeping over the parcel."""
    mask = Image.new("L", (n, n), 0)
    draw = ImageDraw.Draw(mask)
    width = max(1, int(n * 0.030))
    box = (n * 0.145, n * 0.150, n * 0.855, n * 0.795)
    # Left-to-right over the top of the parcel: 190 deg to 350 deg.
    draw.arc(box, start=190, end=350, fill=255, width=width)
    return mask


def _waypoint_mask(n: int) -> Image.Image:
    """An 'L' mask holding the dot that terminates the arc."""
    mask = Image.new("L", (n, n), 0)
    draw = ImageDraw.Draw(mask)
    # Sits on the arc's right-hand end.
    angle = math.radians(350)
    cx, cy = n * 0.5, n * 0.4725
    rx, ry = n * 0.355, n * 0.3225
    px, py = cx + rx * math.cos(angle), cy + ry * math.sin(angle)
    r = n * 0.052
    draw.ellipse((px - r, py - r, px + r, py + r), fill=255)
    return mask


def build_icon(size: int) -> Image.Image:
    """Render the icon at `size` px, supersampled internally."""
    n = size * SUPERSAMPLE

    # 1. The rounded-square plate.
    plate = Image.new("L", (n, n), 0)
    ImageDraw.Draw(plate).rounded_rectangle(
        (0, 0, n - 1, n - 1), radius=int(n * CORNER_RADIUS), fill=255
    )
    canvas = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    canvas.paste(_vertical_gradient(n, BG_TOP, BG_BOTTOM), (0, 0), plate)

    # 2. The delivery arc, softened a touch so it glows rather than cuts.
    arc = _arc_mask(n).filter(ImageFilter.GaussianBlur(radius=n * 0.002))
    canvas = Image.alpha_composite(canvas, _tint(n, ARC, arc))

    # 3. The parcel, drawn over the arc so the arc passes behind it.
    parcel = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    _draw_parcel(ImageDraw.Draw(parcel), n)
    canvas = Image.alpha_composite(canvas, parcel)

    # 4. The waypoint last, so it sits above everything.
    waypoint = _waypoint_mask(n).filter(ImageFilter.GaussianBlur(radius=n * 0.0015))
    canvas = Image.alpha_composite(canvas, _tint(n, WAYPOINT, waypoint))

    # 5. Clip back to the plate so nothing bleeds past the corners.
    clipped = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    clipped.paste(canvas, (0, 0), plate)
    return clipped.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Write both icon sizes into the brand directory."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    root = OUT_DIR.parents[2]
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        path = OUT_DIR / name
        build_icon(size).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(root)} ({size}x{size})")


if __name__ == "__main__":
    main()
