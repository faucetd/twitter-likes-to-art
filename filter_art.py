"""
Optional art filter: use CLIP (or similar) to keep only images that score high
as "art / illustration / aesthetic" and drop screenshots, memes, text photos.
Writes a new manifest containing only the kept entries.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def filter_art_from_manifest(
    manifest_path: Path,
    download_dir: Path,
    output_manifest_path: Path | None = None,
    threshold: float = 0.22,
    art_prompt: str = "digital art, illustration, drawing, aesthetic artwork, painting",
) -> Path | None:
    """
    Read manifest, score each image with CLIP against art_prompt, keep entries
    with score >= threshold. Write subset manifest and return its path.
    """
    manifest_path = Path(manifest_path)
    download_dir = Path(download_dir)
    if output_manifest_path is None:
        output_manifest_path = manifest_path.parent / "art_manifest.json"

    try:
        import torch
        import open_clip
        from PIL import Image
    except ImportError as e:
        raise ImportError(
            "Art filter requires: pip install open-clip-torch torch pillow"
        ) from e

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai"
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model = model.to(device).eval()

    text_tokens = tokenizer([art_prompt]).to(device)
    with torch.no_grad():
        text_features = model.encode_text(text_tokens).float()
        text_features /= text_features.norm(dim=-1, keepdim=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kept: list[dict[str, Any]] = []

    resolved_download = download_dir.resolve()
    for entry in manifest:
        raw = entry.get("path") or ""
        path = Path(raw)
        if not path.is_file() and not path.is_absolute():
            path = download_dir / path.name
        if not path.is_file():
            continue
        # Path containment: reject paths outside the download directory
        if not path.resolve().is_relative_to(resolved_download):
            logger.warning("Skipping file outside download dir: %s", path)
            continue
        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:
            logger.warning("Failed to open image %s: %s", path, exc)
            continue
        img_t = preprocess(img).unsqueeze(0).to(device)
        with torch.no_grad():
            image_features = model.encode_image(img_t).float()
            image_features /= image_features.norm(dim=-1, keepdim=True)
            score = (image_features @ text_features.T).item()
        if score >= threshold:
            kept.append(entry)

    output_manifest_path.write_text(
        json.dumps(kept, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_manifest_path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Filter manifest to art-like images only (CLIP).")
    parser.add_argument("manifest", type=Path, help="Manifest JSON from download_media.py")
    parser.add_argument("--download-dir", type=Path, default=Path("downloads"), help="Directory where images live")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output manifest path (default: download_dir/art_manifest.json)")
    parser.add_argument("--threshold", type=float, default=0.22, help="CLIP similarity threshold (default: 0.22)")
    args = parser.parse_args()

    out = filter_art_from_manifest(
        args.manifest,
        args.download_dir,
        output_manifest_path=args.output,
        threshold=args.threshold,
    )
    print(f"Kept {len(json.loads(out.read_text(encoding='utf-8')))} images; manifest at {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
