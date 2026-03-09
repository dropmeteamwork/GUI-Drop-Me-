"""
Optimize image assets for deployment.

Usage:
  python tools/optimize_assets.py --input images --output images-optimized
  python tools/optimize_assets.py --input images --in-place

Notes:
- PNG optimization preserves format.
- JPG/JPEG optimization uses quality and progressive options.
- Requires Pillow: pip install pillow
"""

from __future__ import annotations

import argparse
from pathlib import Path


def optimize_image(src: Path, dst: Path, jpg_quality: int) -> tuple[int, int]:
    from PIL import Image

    before = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)

    suffix = src.suffix.lower()
    with Image.open(src) as img:
        if suffix in (".jpg", ".jpeg"):
            img.save(dst, format="JPEG", optimize=True, quality=jpg_quality, progressive=True)
        elif suffix == ".png":
            img.save(dst, format="PNG", optimize=True)
        else:
            img.save(dst)

    after = dst.stat().st_size
    return before, after


def walk_images(input_dir: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"}
    return [p for p in input_dir.rglob("*") if p.is_file() and p.suffix in exts]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input assets directory")
    parser.add_argument("--output", help="Output directory (omit when using --in-place)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite original files")
    parser.add_argument("--jpg-quality", type=int, default=85)
    args = parser.parse_args()

    input_dir = Path(args.input).resolve()
    if not input_dir.exists():
        raise SystemExit(f"Input path not found: {input_dir}")

    if args.in_place and args.output:
        raise SystemExit("Use either --in-place or --output, not both")

    output_dir = input_dir if args.in_place else Path(args.output or (str(input_dir) + "-optimized")).resolve()
    images = walk_images(input_dir)
    if not images:
        print("No images found.")
        return 0

    total_before = 0
    total_after = 0

    try:
        from PIL import Image  # noqa: F401
    except Exception as exc:
        raise SystemExit(f"Pillow is required: {exc}")

    for src in images:
        rel = src.relative_to(input_dir)
        dst = (output_dir / rel) if not args.in_place else src
        before, after = optimize_image(src, dst, args.jpg_quality)
        total_before += before
        total_after += after

    saved = total_before - total_after
    ratio = (saved / total_before * 100.0) if total_before else 0.0
    print(f"Optimized {len(images)} files")
    print(f"Before: {total_before:,} bytes")
    print(f"After:  {total_after:,} bytes")
    print(f"Saved:  {saved:,} bytes ({ratio:.2f}%)")
    print(f"Output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
