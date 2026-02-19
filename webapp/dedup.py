"""
Find and remove near-duplicate images using perceptual hashing.
Keeps the highest-resolution version of each duplicate group.

Usage:
    python -m webapp.dedup [--dry-run] [--threshold 6]
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image
import imagehash

ART_DIR = Path(__file__).resolve().parent.parent / "art"
METADATA_PATH = ART_DIR / "metadata.json"


def phash_images(art_dir: Path, metadata: dict) -> dict[str, imagehash.ImageHash]:
    hashes = {}
    total = len(metadata)
    for i, filename in enumerate(metadata, 1):
        filepath = art_dir / filename
        if not filepath.exists():
            continue
        try:
            img = Image.open(filepath)
            hashes[filename] = imagehash.phash(img)
        except Exception as e:
            print(f"  [{i}/{total}] skip {filename}: {e}")
            continue
        if i % 500 == 0:
            print(f"  [{i}/{total}] hashed...")
    return hashes


def find_duplicate_groups(
    hashes: dict[str, imagehash.ImageHash], threshold: int = 6
) -> list[list[str]]:
    filenames = list(hashes.keys())
    visited = set()
    groups = []

    for i, f1 in enumerate(filenames):
        if f1 in visited:
            continue
        group = [f1]
        for f2 in filenames[i + 1 :]:
            if f2 in visited:
                continue
            if hashes[f1] - hashes[f2] <= threshold:
                group.append(f2)
                visited.add(f2)
        if len(group) > 1:
            groups.append(group)
            visited.add(f1)

    return groups


def pick_best(group: list[str], art_dir: Path) -> str:
    """Keep the largest file (proxy for highest resolution)."""
    return max(group, key=lambda f: (art_dir / f).stat().st_size)


def generate_review_html(groups: list[list[str]], hashes: dict, art_dir: Path, metadata: dict) -> Path:
    """Generate an HTML page showing duplicate groups side-by-side for review."""
    out_path = Path(__file__).resolve().parent / "dedup_review.html"

    tiles_html = []
    for gi, group in enumerate(groups, 1):
        best = pick_best(group, art_dir)
        cards = []
        for filename in group:
            is_keep = filename == best
            info = metadata.get(filename, {})
            size_kb = (art_dir / filename).stat().st_size // 1024
            try:
                w, h = Image.open(art_dir / filename).size
                dims = f"{w}×{h}"
            except Exception:
                dims = "?"
            dist = hashes[best] - hashes[filename] if filename != best else 0
            badge = f'<span class="badge keep">KEEP</span>' if is_keep else f'<span class="badge remove">REMOVE</span>'
            cards.append(f'''
                <div class="card {'keep-card' if is_keep else 'remove-card'}">
                    {badge}
                    <img src="../art/{filename}" loading="lazy">
                    <div class="meta">
                        <b>@{info.get("username", "?")}</b><br>
                        <span class="dim">{filename}</span><br>
                        <span class="dim">{dims} · {size_kb} KB · dist {dist}</span>
                    </div>
                </div>''')

        tiles_html.append(f'''
            <div class="group">
                <div class="group-header">Group {gi} — {len(group)} images</div>
                <div class="group-images">{"".join(cards)}</div>
            </div>''')

    html = f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dedup Review — {len(groups)} groups</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #0e0e10; color: #e0e0e0; padding: 20px; }}
  h1 {{ margin-bottom: 8px; }}
  .summary {{ color: #888; margin-bottom: 24px; font-size: 0.9rem; }}
  .group {{ margin-bottom: 32px; background: #1a1a2e; border-radius: 12px; overflow: hidden; }}
  .group-header {{ padding: 10px 16px; font-weight: 700; font-size: 0.85rem; border-bottom: 1px solid #333; }}
  .group-images {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }}
  .card {{ border-radius: 8px; overflow: hidden; width: 280px; border: 2px solid transparent; }}
  .keep-card {{ border-color: #4ade80; }}
  .remove-card {{ border-color: #f87171; opacity: 0.7; }}
  .card img {{ width: 100%; aspect-ratio: 1; object-fit: cover; display: block; background: #111; }}
  .meta {{ padding: 8px; font-size: 0.75rem; line-height: 1.4; }}
  .dim {{ color: #888; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 700; margin-bottom: 4px; }}
  .badge.keep {{ background: #4ade80; color: #000; }}
  .badge.remove {{ background: #f87171; color: #000; }}
</style>
</head><body>
<h1>Dedup Review</h1>
<p class="summary">{len(groups)} duplicate groups · {sum(len(g) - 1 for g in groups)} images would be removed · green = keep, red = remove</p>
{"".join(tiles_html)}
</body></html>'''

    out_path.write_text(html)
    return out_path


def run_dedup(threshold: int = 6, dry_run: bool = False, review: bool = False):
    with open(METADATA_PATH) as f:
        metadata = json.load(f)

    print(f"Hashing {len(metadata)} images...")
    hashes = phash_images(ART_DIR, metadata)
    print(f"Hashed {len(hashes)} images. Finding duplicates (threshold={threshold})...")

    groups = find_duplicate_groups(hashes, threshold)
    total_dupes = sum(len(g) - 1 for g in groups)
    print(f"Found {len(groups)} duplicate groups ({total_dupes} images to remove)")

    if not groups:
        return

    if review:
        out = generate_review_html(groups, hashes, ART_DIR, metadata)
        print(f"\nReview page written to {out}")
        import webbrowser
        webbrowser.open(f"file://{out}")
        return

    to_remove = []
    for group in groups:
        best = pick_best(group, ART_DIR)
        dupes = [f for f in group if f != best]
        print(f"  keep: {best}")
        for d in dupes:
            print(f"    rm: {d}")
        to_remove.extend(dupes)

    if dry_run:
        print(f"\n[dry run] Would remove {len(to_remove)} files.")
        return

    for filename in to_remove:
        (ART_DIR / filename).unlink(missing_ok=True)
        del metadata[filename]

    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\nRemoved {len(to_remove)} duplicates. metadata.json updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate art images")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--review", action="store_true", help="Generate HTML review page and open in browser")
    parser.add_argument(
        "--threshold", type=int, default=6,
        help="Hamming distance threshold (lower = stricter, default 6)",
    )
    args = parser.parse_args()
    run_dedup(threshold=args.threshold, dry_run=args.dry_run, review=args.review)
