"""
Art filter for downloaded images. Two modes:

1. Zero-shot CLIP: contrastive scoring against art/non-art text prompts.
2. Trained classifier: logistic regression on CLIP embeddings, trained on
   your labels from label_images.py.  Much more accurate for your taste.

The trained classifier is used automatically when art_classifier.pkl exists.
Train it with:  python filter_art.py --train labels.json
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

CLASSIFIER_PATH = Path("art_classifier.pkl")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

DEFAULT_ART_PROMPT = "digital art, illustration, drawing, aesthetic artwork, painting"
DEFAULT_NON_ART_PROMPT = (
    "screenshot, text message, meme with caption, UI interface, "
    "photograph of a person, selfie, news article, spreadsheet"
)


def _load_clip():
    """Load CLIP ViT-B-32 model. Returns (model, preprocess, device)."""
    import torch
    import open_clip

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai"
    )
    model = model.to(device).eval()
    return model, preprocess, device


def _extract_embeddings(
    image_paths: list[Path],
    model,
    preprocess,
    device: str,
    batch_size: int = 16,
) -> np.ndarray:
    """Extract normalized CLIP embeddings for a list of images. Returns (N, 512) array."""
    import torch
    from PIL import Image

    all_features = []
    total = len(image_paths)

    for batch_start in range(0, total, batch_size):
        batch_paths = image_paths[batch_start : batch_start + batch_size]
        tensors = []
        for p in batch_paths:
            try:
                img = Image.open(p).convert("RGB")
                tensors.append(preprocess(img))
            except Exception as exc:
                logger.warning("Failed to open %s: %s", p, exc)
                tensors.append(None)

        valid = [t for t in tensors if t is not None]
        if not valid:
            all_features.extend([np.zeros(512)] * len(batch_paths))
            continue

        batch_tensor = torch.stack(valid).to(device)
        with torch.no_grad():
            features = model.encode_image(batch_tensor).float()
            features /= features.norm(dim=-1, keepdim=True)

        feat_np = features.cpu().numpy()
        feat_idx = 0
        for t in tensors:
            if t is not None:
                all_features.append(feat_np[feat_idx])
                feat_idx += 1
            else:
                all_features.append(np.zeros(512))

        processed = min(batch_start + batch_size, total)
        if processed % (batch_size * 4) < batch_size or processed == total:
            print(f"  Embeddings: {processed}/{total}", file=sys.stderr)

    return np.array(all_features)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_classifier(
    labels_path: Path,
    classifier_path: Path = CLASSIFIER_PATH,
    batch_size: int = 16,
) -> Path:
    """
    Train a logistic regression on CLIP embeddings using labels from label_images.py.
    Saves to classifier_path and returns it.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    import joblib

    labels_path = Path(labels_path)
    labels: dict[str, bool] = json.loads(labels_path.read_text(encoding="utf-8"))
    if not labels:
        print("Error: labels file is empty.", file=sys.stderr)
        sys.exit(1)

    # Resolve image paths (labels.json maps filenames → bool)
    image_dir = labels_path.parent
    paths, targets = [], []
    for filename, keep in labels.items():
        p = image_dir / filename
        if not p.is_file():
            logger.warning("Labeled image not found: %s", p)
            continue
        paths.append(p)
        targets.append(1 if keep else 0)

    if len(paths) < 4:
        print(f"Error: need at least 4 labeled images, got {len(paths)}.", file=sys.stderr)
        sys.exit(1)

    keep_count = sum(targets)
    skip_count = len(targets) - keep_count
    print(f"Training on {len(paths)} images ({keep_count} keep, {skip_count} skip)...", file=sys.stderr)

    model, preprocess, device = _load_clip()
    X = _extract_embeddings(paths, model, preprocess, device, batch_size=batch_size)
    y = np.array(targets)

    clf = LogisticRegression(class_weight="balanced", max_iter=1000)

    n_folds = min(5, min(keep_count, skip_count))
    if n_folds >= 2:
        scores = cross_val_score(clf, X, y, cv=n_folds, scoring="accuracy")
        print(f"  {n_folds}-fold CV accuracy: {scores.mean():.1%} (±{scores.std():.1%})", file=sys.stderr)

    clf.fit(X, y)
    classifier_path = Path(classifier_path)
    joblib.dump(clf, classifier_path)
    print(f"Classifier saved to {classifier_path}", file=sys.stderr)
    return classifier_path


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _resolve_manifest_images(
    manifest_path: Path,
    download_dir: Path,
) -> list[tuple[dict[str, Any], Path]]:
    """Validate manifest entries and return (entry, path) pairs for real files."""
    download_dir = Path(download_dir)
    resolved_download = download_dir.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    valid: list[tuple[dict[str, Any], Path]] = []

    for entry in manifest:
        raw = entry.get("path") or ""
        path = Path(raw)
        if not path.is_file() and not path.is_absolute():
            path = download_dir / path.name
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(resolved_download):
            logger.warning("Skipping file outside download dir: %s", path)
            continue
        valid.append((entry, path))

    return valid


def _filter_with_classifier(
    valid_entries: list[tuple[dict[str, Any], Path]],
    classifier_path: Path,
    threshold: float,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Score images with the trained classifier."""
    import joblib

    clf = joblib.load(classifier_path)
    paths = [p for _, p in valid_entries]
    model, preprocess, device = _load_clip()
    X = _extract_embeddings(paths, model, preprocess, device, batch_size=batch_size)
    probs = clf.predict_proba(X)[:, 1]

    kept = []
    for i, (entry, _) in enumerate(valid_entries):
        if probs[i] >= threshold:
            kept.append(entry)
    return kept


def _filter_zero_shot(
    valid_entries: list[tuple[dict[str, Any], Path]],
    art_prompt: str,
    non_art_prompt: str,
    threshold: float,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Score images with zero-shot CLIP contrastive scoring."""
    import torch
    import open_clip

    model, preprocess, device = _load_clip()
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    text_tokens = tokenizer([art_prompt, non_art_prompt]).to(device)
    with torch.no_grad():
        text_features = model.encode_text(text_tokens).float()
        text_features /= text_features.norm(dim=-1, keepdim=True)
    art_feat = text_features[0:1]
    non_art_feat = text_features[1:2]

    paths = [p for _, p in valid_entries]
    model_clip, preprocess_clip, device_clip = model, preprocess, device

    kept = []
    from PIL import Image

    for batch_start in range(0, len(valid_entries), batch_size):
        batch_items = valid_entries[batch_start : batch_start + batch_size]
        tensors = []
        batch_entries = []
        for entry, path in batch_items:
            try:
                img = Image.open(path).convert("RGB")
                tensors.append(preprocess_clip(img))
                batch_entries.append(entry)
            except Exception as exc:
                logger.warning("Failed to open image %s: %s", path, exc)

        if not tensors:
            continue

        batch_tensor = torch.stack(tensors).to(device_clip)
        with torch.no_grad():
            image_features = model_clip.encode_image(batch_tensor).float()
            image_features /= image_features.norm(dim=-1, keepdim=True)
            art_scores = (image_features @ art_feat.T).squeeze(-1)
            non_art_scores = (image_features @ non_art_feat.T).squeeze(-1)
            delta_scores = art_scores - non_art_scores

        for i, entry in enumerate(batch_entries):
            if delta_scores[i].item() >= threshold:
                kept.append(entry)

        processed = min(batch_start + batch_size, len(valid_entries))
        if processed % (batch_size * 4) < batch_size or processed == len(valid_entries):
            print(f"  Art filter: {processed}/{len(valid_entries)} scored, {len(kept)} kept so far...", file=sys.stderr)

    return kept


def filter_art_from_manifest(
    manifest_path: Path,
    download_dir: Path,
    output_manifest_path: Path | None = None,
    threshold: float | None = None,
    art_prompt: str = DEFAULT_ART_PROMPT,
    non_art_prompt: str = DEFAULT_NON_ART_PROMPT,
    batch_size: int = 16,
    classifier_path: Path = CLASSIFIER_PATH,
) -> Path | None:
    """
    Filter manifest to art-like images. Uses trained classifier if available,
    otherwise falls back to zero-shot CLIP contrastive scoring.
    """
    manifest_path = Path(manifest_path)
    download_dir = Path(download_dir)
    if output_manifest_path is None:
        output_manifest_path = manifest_path.parent / "art_manifest.json"

    try:
        import torch  # noqa: F401
        import open_clip  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Art filter requires: pip install open-clip-torch torch pillow"
        ) from e

    valid_entries = _resolve_manifest_images(manifest_path, download_dir)
    total = len(valid_entries)
    if not total:
        output_manifest_path.write_text("[]", encoding="utf-8")
        return output_manifest_path

    use_classifier = Path(classifier_path).is_file()

    if use_classifier:
        default_threshold = 0.5
        t = threshold if threshold is not None else default_threshold
        print(f"  Art filter: scoring {total} images with trained classifier (threshold={t})...", file=sys.stderr)
        kept = _filter_with_classifier(valid_entries, classifier_path, t, batch_size)
    else:
        default_threshold = 0.03
        t = threshold if threshold is not None else default_threshold
        print(f"  Art filter: scoring {total} images with zero-shot CLIP (threshold={t})...", file=sys.stderr)
        kept = _filter_zero_shot(valid_entries, art_prompt, non_art_prompt, t, batch_size)

    print(f"  Art filter: kept {len(kept)}/{total} images.", file=sys.stderr)

    output_manifest_path.write_text(
        json.dumps(kept, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_manifest_path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Art filter: zero-shot CLIP or trained classifier on CLIP embeddings.",
    )
    sub = parser.add_subparsers(dest="command")

    # -- train --
    train_p = sub.add_parser("train", help="Train classifier from labels.json")
    train_p.add_argument("labels", type=Path, help="labels.json from label_images.py")
    train_p.add_argument("--batch-size", type=int, default=16)
    train_p.add_argument(
        "--classifier", type=Path, default=CLASSIFIER_PATH,
        help=f"Output path for classifier (default: {CLASSIFIER_PATH})",
    )

    # -- filter --
    filter_p = sub.add_parser("filter", help="Filter a manifest to art-like images")
    filter_p.add_argument("manifest", type=Path, help="Manifest JSON from download_media.py")
    filter_p.add_argument("--download-dir", type=Path, default=Path("downloads"))
    filter_p.add_argument("-o", "--output", type=Path, default=None)
    filter_p.add_argument("--threshold", type=float, default=None)
    filter_p.add_argument("--batch-size", type=int, default=16)

    args = parser.parse_args()

    if args.command == "train":
        train_classifier(args.labels, classifier_path=args.classifier, batch_size=args.batch_size)
    elif args.command == "filter":
        out = filter_art_from_manifest(
            args.manifest,
            args.download_dir,
            output_manifest_path=args.output,
            threshold=args.threshold,
            batch_size=args.batch_size,
        )
        kept_count = len(json.loads(out.read_text(encoding="utf-8")))
        print(f"Kept {kept_count} images; manifest at {out}", file=sys.stderr)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
