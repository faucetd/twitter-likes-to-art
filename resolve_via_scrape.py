"""
Resolve tweet IDs and download media via gallery-dl (no X API needed).

Uses browser cookies for authentication, bypassing the paid API entirely.
Produces a manifest.json compatible with rename_and_organize.py / filter_art.py.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def build_tweet_url(tweet_id: str) -> str:
    """Construct a tweet URL suitable for gallery-dl."""
    return f"https://x.com/i/web/status/{tweet_id}"


def _write_gdl_config(config_path: Path) -> None:
    """Write a minimal gallery-dl config for Twitter media downloads.

    Sets a flat output directory (no subdirs), a filename template that
    includes tweet_id and image index, and enables the metadata
    postprocessor so we can read author/date/text after the run.
    """
    config = {
        "extractor": {
            "twitter": {
                "filename": "{tweet_id}_{num}.{extension}",
                "directory": [],
                "postprocessors": [
                    {
                        "name": "metadata",
                        "mode": "json",
                    }
                ],
            }
        }
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _collect_manifest_entries(
    output_dir: Path,
    record_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Scan output_dir for downloaded images and their gallery-dl metadata JSONs.

    Returns manifest entries compatible with rename_and_organize.py:
    ``{ tweet_id, index, path, username, date, text, like_source }``.
    """
    manifest: list[dict[str, Any]] = []

    for img_path in sorted(output_dir.iterdir()):
        if img_path.suffix.lower() not in _IMAGE_EXTENSIONS:
            continue

        # Filename pattern from config: {tweet_id}_{num}.{ext}
        parts = img_path.stem.rsplit("_", 1)
        if len(parts) != 2:
            continue
        tweet_id, num_str = parts
        try:
            num = int(num_str)
        except ValueError:
            continue

        username = "unknown"
        date_str = ""
        content = ""

        # gallery-dl metadata postprocessor writes {filename}.json next to the image
        meta_path = img_path.with_name(img_path.name + ".json")
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                author = meta.get("author") or meta.get("user") or {}
                username = author.get("name") or author.get("screen_name") or "unknown"
                raw_date = str(meta.get("date") or "")
                date_str = raw_date[:10] if len(raw_date) >= 10 else raw_date
                content = meta.get("content") or ""
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to parse metadata %s: %s", meta_path, exc)

        # Fall back to the original parsed record for any missing fields
        orig = record_by_id.get(tweet_id, {})
        if username == "unknown":
            username = orig.get("username", "unknown")
        if not date_str:
            date_str = orig.get("date", "")
        if not content:
            content = orig.get("text", "")

        manifest.append({
            "tweet_id": tweet_id,
            "index": num - 1,  # gallery-dl num is 1-based; manifest uses 0-based
            "path": str(img_path.resolve()),
            "username": username,
            "date": date_str,
            "text": content,
            "like_source": orig.get("like_source", "scrape"),
        })

    return manifest


def resolve_and_download(
    records: list[dict[str, Any]],
    output_dir: Path,
    manifest_path: Path,
    browser: str = "brave",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Download media for ID-only records using gallery-dl with browser cookies.

    For each record without ``media_urls``, constructs a tweet URL and feeds
    it to gallery-dl.  Images are saved to *output_dir* with gallery-dl
    metadata JSONs, which are then parsed into a manifest compatible with
    the rest of the pipeline (``rename_and_organize.py``, ``filter_art.py``).

    Args:
        records: Parsed tweet records (may include ID-only entries with
            empty ``media_urls``).
        output_dir: Staging directory for downloaded images.
        manifest_path: Path to write the output manifest JSON.
        browser: Browser to extract cookies from (default: ``"brave"``).
            The browser **must be closed** during the run (Chromium locks
            its cookie database while open).
        limit: Max tweets to scrape (``None`` = all).  Useful for testing.

    Returns:
        List of manifest entries that were written to *manifest_path*.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    to_scrape = [r for r in records if r.get("tweet_id") and not r.get("media_urls")]
    if limit is not None:
        to_scrape = to_scrape[:limit]

    if not to_scrape:
        logger.info("No ID-only records to resolve via gallery-dl.")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("[]", encoding="utf-8")
        return []

    print(
        f"Scraping {len(to_scrape)} tweets via gallery-dl "
        f"(browser: {browser})...",
        file=sys.stderr,
    )

    record_by_id = {r["tweet_id"]: r for r in to_scrape}

    # Write URL list for gallery-dl --input-file
    url_file = output_dir / "_gdl_urls.txt"
    urls = [build_tweet_url(r["tweet_id"]) for r in to_scrape]
    url_file.write_text("\n".join(urls) + "\n", encoding="utf-8")

    # Write gallery-dl config
    config_path = output_dir / "_gdl_config.json"
    _write_gdl_config(config_path)

    cmd = [
        "gallery-dl",
        "--cookies-from-browser", browser,
        "--dest", str(output_dir),
        "--config", str(config_path),
        "--input-file", str(url_file),
    ]

    logger.info("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300 + len(to_scrape) * 15,
        )

        if result.stdout:
            for line in result.stdout.strip().splitlines()[-10:]:
                logger.debug("gallery-dl: %s", line)
        if result.returncode != 0:
            logger.warning(
                "gallery-dl exited with code %d", result.returncode,
            )
            if result.stderr:
                for line in result.stderr.strip().splitlines()[-5:]:
                    logger.warning("gallery-dl: %s", line)
    except subprocess.TimeoutExpired:
        logger.error(
            "gallery-dl timed out after %ds", 300 + len(to_scrape) * 15,
        )
    except FileNotFoundError:
        logger.error(
            "gallery-dl not found. Install with: pip install gallery-dl",
        )
        raise

    # Build manifest from downloaded files + metadata
    manifest_entries = _collect_manifest_entries(output_dir, record_by_id)

    # Write manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    unique_tweets = len({e["tweet_id"] for e in manifest_entries})
    print(
        f"gallery-dl done: {len(manifest_entries)} images "
        f"from {unique_tweets} tweets.",
        file=sys.stderr,
    )

    # Cleanup temp files
    url_file.unlink(missing_ok=True)
    config_path.unlink(missing_ok=True)

    return manifest_entries


def main() -> None:
    """CLI: resolve and download tweets from a parsed-records JSON file."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        description="Resolve tweet IDs and download media via gallery-dl "
        "(no API needed).",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="JSON file with parsed records "
        "(from parse_archive.py --include-id-only)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("downloads"),
        help="Staging directory for downloads (default: downloads)",
    )
    parser.add_argument(
        "-m", "--manifest",
        type=Path,
        default=Path("downloads/manifest.json"),
        help="Manifest JSON output path (default: downloads/manifest.json)",
    )
    parser.add_argument(
        "--browser",
        default="brave",
        help="Browser for cookie extraction (default: brave). "
        "Must be closed during run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max tweets to scrape (default: all)",
    )
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))

    entries = resolve_and_download(
        records,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        browser=args.browser,
        limit=args.limit,
    )

    print(
        f"Manifest: {args.manifest} ({len(entries)} entries)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
