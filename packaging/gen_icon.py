#!/usr/bin/env python3
"""
Generate a placeholder Insight Mine icon and convert it to .icns.

Requires:
  - Python 3.11+
  - Pillow (`python -m pip install pillow`)
  - macOS utilities: sips, iconutil
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        sys.exit("Pillow is required. Install with: python -m pip install pillow")


def generate_placeholder_png(path: Path, size: int = 1024) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)

    bg = Image.new("RGBA", (size, size), "#0f172a")
    draw = ImageDraw.Draw(bg)

    # Soft radial highlight
    for r in range(size // 2, 0, -40):
        alpha = int(255 * (r / (size // 2)) ** 2)
        draw.ellipse(
            [
                (size // 2 - r, size // 2 - r),
                (size // 2 + r, size // 2 + r),
            ],
            fill=(45, 212, 191, max(25, min(alpha, 140))),
        )

    # Foreground ring
    ring_margin = size // 6
    ring_width = size // 18
    draw.ellipse(
        [(ring_margin, ring_margin), (size - ring_margin, size - ring_margin)],
        outline="#22d3ee",
        width=ring_width,
    )

    # IM monogram
    font = ImageFont.load_default()
    try:
        # Prefer a slightly nicer font if available
        font = ImageFont.truetype("Helvetica Bold", size // 3)
    except Exception:
        try:
            font = ImageFont.truetype("Arial Bold", size // 3)
        except Exception:
            font = ImageFont.load_default()

    text = "IM"
    # Pillow 12 removed textsize; use textbbox for compatibility
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    text_pos = ((size - tw) / 2, (size - th) / 2 - size * 0.02)
    draw.text(text_pos, text, font=font, fill="#e2e8f0")

    bg.save(path)
    return path


def run_cmd(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_iconset(base_png: Path, iconset_dir: Path) -> None:
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for s in (16, 32, 64, 128, 256, 512):
        target = iconset_dir / f"icon_{s}x{s}.png"
        target2x = iconset_dir / f"icon_{s}x{s}@2x.png"
        run_cmd(["sips", "-z", str(s), str(s), str(base_png), "--out", str(target)])
        run_cmd(
            ["sips", "-z", str(s * 2), str(s * 2), str(base_png), "--out", str(target2x)]
        )


def build_icns(iconset_dir: Path, icns_path: Path) -> None:
    icns_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)])


def main():
    repo_root = Path(__file__).resolve().parents[1]
    default_png = repo_root / "packaging" / "icon.png"
    default_icns = repo_root / "packaging" / "app.icns"
    default_iconset = repo_root / "packaging" / "icon.iconset"

    parser = argparse.ArgumentParser(description="Generate placeholder icon + .icns")
    parser.add_argument("--png", type=Path, default=default_png, help="Output 1024px PNG")
    parser.add_argument("--icns", type=Path, default=default_icns, help="Output .icns path")
    parser.add_argument(
        "--iconset", type=Path, default=default_iconset, help="Intermediate iconset folder"
    )
    parser.add_argument(
        "--force-placeholder",
        action="store_true",
        help="Rebuild base PNG with placeholder art even if an icon already exists",
    )
    args = parser.parse_args()

    require_pillow()

    base_png = args.png
    if args.force_placeholder or not base_png.exists():
        base_png = generate_placeholder_png(args.png)
    build_iconset(base_png, args.iconset)
    build_icns(args.iconset, args.icns)

    print(f"Wrote {args.icns}")


if __name__ == "__main__":
    main()

