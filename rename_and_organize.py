"""
Rename downloaded media files to final form: username_date_tweetid_index.ext.
Optional: embed sanitized title in filename or write sidecar JSON.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def sanitize_username(s: str, max_len: int = 40) -> str:
    """Replace spaces/slashes with underscore, remove invalid chars, truncate."""
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^\w\-.]", "", s)
    return s[:max_len] if len(s) > max_len else s or "unknown"


def sanitize_title(text: str, max_len: int = 40) -> str:
    """Remove URLs, collapse whitespace, truncate, safe for filename."""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^\w\s\-.,'!?]", "", text)
    text = text.replace(" ", "_")[:max_len].strip("_")
    return text or ""


def build_filename(
    username: str,
    date: str,
    tweet_id: str,
    index: int,
    ext: str,
    title: str | None = None,
) -> str:
    """Produce final filename: username_date_tweet_id_index.ext or with title."""
    user = sanitize_username(username)
    safe_date = date.replace("/", "-")[:10] if date else "unknown"
    if title:
        title_part = sanitize_title(title)
        if title_part:
            return f"{user}_{safe_date}_{title_part}_{tweet_id}_{index}.{ext}"
    return f"{user}_{safe_date}_{tweet_id}_{index}.{ext}"


def rename_from_manifest(
    manifest_path: Path,
    output_dir: Path,
    include_title: bool = False,
    sidecar_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Read manifest (list of { path, tweet_id, index, username, date, text, like_source }),
    rename each file to username_date_tweetid_index.ext in output_dir, and optionally
    write a sidecar JSON mapping filename -> metadata.
    """
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    sidecar: dict[str, dict[str, Any]] = {}

    for entry in manifest:
        src = Path(entry.get("path") or "").resolve()
        if not src.is_file():
            continue
        # Path containment: reject paths that escape expected directories
        if not any(
            src.is_relative_to(allowed)
            for allowed in (output_dir.resolve(), Path.cwd().resolve())
        ):
            logger.warning("Skipping file outside allowed directories: %s", src)
            continue
        username = entry.get("username") or "unknown"
        date = entry.get("date") or ""
        tweet_id = entry.get("tweet_id") or ""
        index = entry.get("index", 0)
        text = entry.get("text") or ""
        ext = src.suffix.lstrip(".").lower() or "jpg"
        title = (text if include_title else None)
        name = build_filename(username, date, tweet_id, index, ext, title=title)
        dest = output_dir / name
        if dest.resolve() == src:
            continue
        if dest.exists() and dest.resolve() != src:
            # Avoid overwrite: append a suffix until unique
            base = dest.stem
            dest = output_dir / f"{base}_{tweet_id}.{ext}"
            counter = 2
            while dest.exists() and dest.resolve() != src:
                dest = output_dir / f"{base}_{tweet_id}_{counter}.{ext}"
                counter += 1
        shutil.move(str(src), str(dest))
        if sidecar_path is not None:
            sidecar[dest.name] = {
                "username": username,
                "date": date,
                "tweet_id": tweet_id,
                "title": text[:200],
                "like_source": entry.get("like_source", ""),
            }

    if sidecar_path is not None and sidecar:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")

    return list(sidecar.values()) if sidecar else []


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Rename downloaded media to username_date_tweetid_index.ext")
    parser.add_argument("manifest", type=Path, help="Manifest JSON from download_media.py")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("art"), help="Output directory for renamed files")
    parser.add_argument("--include-title", action="store_true", help="Embed sanitized tweet text in filename")
    parser.add_argument("--sidecar", type=Path, default=None, help="Write metadata JSON next to output dir (e.g. art/metadata.json)")
    args = parser.parse_args()

    rename_from_manifest(
        args.manifest,
        args.output_dir,
        include_title=args.include_title,
        sidecar_path=args.sidecar,
    )
    print(f"Renamed files into {args.output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
