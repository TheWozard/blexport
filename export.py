#!/usr/bin/env python3
"""Render .blend assets into per-direction PNGs plus a JSON manifest.

For each *.blend file found, invokes Blender headlessly (blender_scene_export.py)
to render its four standard isometric directions — NE/NW/SE/SW, auto-framed to
the object's bounding box unless the scene already has a camera by that name —
plus any other camera already in the scene, and writes:

  <out>/<stem>_<direction-or-camera>.png   one per rendered view
  <out>/<stem>.json                        manifest describing them all

See blender_scene_export.py for the camera/anchor conventions, and README.md
for the JSON schema.

Usage:
  python3 export.py <blend-file-or-directory> [--out DIR] [--force]
                     [--px-per-unit 32] [--supersample 4] [--pitch 35.264]
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BLENDER_SCRIPT = SCRIPT_DIR / "blender_scene_export.py"


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def find_blends(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.blend"))


def stale(blend: Path, out_dir: Path) -> bool:
    manifest = out_dir / f"{blend.stem}.json"
    if not manifest.exists():
        return True
    return blend.stat().st_mtime > manifest.stat().st_mtime


def render_blend(blend: Path, out_dir: Path, px_per_unit: float, png_px_per_unit: float, pitch_deg: float):
    out_json = out_dir / f"{blend.stem}.json"
    result = subprocess.run(
        ["blender", str(blend), "--background", "--python", str(BLENDER_SCRIPT), "--",
         str(out_dir), str(px_per_unit), str(png_px_per_unit), str(pitch_deg)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not out_json.exists():
        print(f"  ✗ {blend.stem} failed:\n{result.stderr.strip()}", file=sys.stderr)
        return None
    with out_json.open() as f:
        return json.load(f)


def process(blend: Path, out_dir: Path, args) -> bool:
    print(f"{blend.name}:")
    data = render_blend(blend, out_dir, args.px_per_unit, args.px_per_unit * args.supersample, args.pitch)
    if data is None:
        return False
    manifest = out_dir / f"{blend.stem}.json"
    views = data.get("views", {})
    n_dirs = sum(1 for key in views if key.lower() in ("ne", "nw", "se", "sw"))
    n_extra = len(views) - n_dirs
    n_anchors = len(next(iter(views.values()), {}).get("anchors", {}))
    print(f"  wrote {manifest.name} ({n_dirs} direction(s), {n_extra} extra camera(s), {n_anchors} anchor(s))")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="a .blend file, or a directory to scan recursively")
    parser.add_argument("--out", type=Path, default=None, help="output directory (default: alongside each .blend)")
    parser.add_argument("--force", action="store_true", help="re-render even if the manifest is up to date")
    parser.add_argument("--px-per-unit", type=float, default=32.0,
                         help="game display pixels per Blender unit (default: 32)")
    parser.add_argument("--supersample", type=float, default=4.0,
                         help="rendered PNG pixels per display pixel, for auto-framed cameras (default: 4)")
    parser.add_argument("--pitch", type=float, default=35.264,
                         help="camera pitch below horizontal in degrees, for auto-framed cameras "
                              "(default: true isometric, 35.264)")
    args = parser.parse_args()

    if shutil.which("blender") is None:
        die("blender not found — install from https://www.blender.org/download/ "
            "(or `brew install --cask blender`) and ensure it's on PATH")

    blends = find_blends(args.path)
    if not blends:
        die(f"no .blend files found under {args.path}")

    ok = 0
    for blend in blends:
        out_dir = args.out if args.out else blend.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        if not args.force and not stale(blend, out_dir):
            print(f"{blend.name}: up to date, skipping")
            ok += 1
            continue
        if process(blend, out_dir, args):
            ok += 1

    print(f"\n{ok}/{len(blends)} asset(s) exported.")
    if ok < len(blends):
        sys.exit(1)


if __name__ == "__main__":
    main()
