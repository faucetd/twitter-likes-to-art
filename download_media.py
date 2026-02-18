"""
Download image media from parsed Twitter archive JSON. Reads the output of
parse_archive.py, fetches each media URL, and saves to a staging directory.
Dedupes by (tweet_id, index). Writes a manifest for rename_and_organize.py.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Only allow downloads from known X/Twitter CDN hosts.
ALLOWED_HOSTS = {"pbs.twimg.com", "ton.twimg.com", "video.twimg.com"}


def _is_allowed_url(url: str) -> bool:
    """Return True if url points to a known X CDN host (rejects file://, private IPs, etc.)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    return parsed.hostname in ALLOWED_HOSTS


def extension_from_url(url: str, default: str = "jpg") -> str:
    """Infer file extension from URL or Content-Type; default jpg."""
    path = urlparse(url).path
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext == "jpeg":
            return "jpg"
        if ext in ("jpg", "png", "gif", "webp"):
            return ext
    return default


def safe_filename_tweet_index(tweet_id: str, index: int, ext: str) -> str:
    """Temporary filename for download: tweet_id_index.ext."""
    return f"{tweet_id}_{index}.{ext}"


def download_one(
    url: str,
    dest_path: Path,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> bool:
    """Download url to dest_path. Returns True on success."""
    if not _is_allowed_url(url):
        logger.warning("Blocked download from disallowed host: %s", url)
        return False
    sess = session or requests.Session()
    try:
        r = sess.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as exc:
        logger.warning("Failed to download %s: %s", url, exc)
        return False


def download_all(
    records: list[dict[str, Any]],
    output_dir: Path,
    manifest_path: Path,
    skip_existing: bool = True,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """
    Download all media from records into output_dir. Dedupes by (tweet_id, index).
    Appends to manifest_path a list of { tweet_id, index, path, username, date, text, like_source }.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, int]] = set()
    manifest_entries: list[dict[str, Any]] = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; Twitter archive media downloader; +https://github.com)",
    })

    # Pre-scan to count unique images (accounting for dedup).
    total_images = 0
    count_seen: set[tuple[str, int]] = set()
    for rec in records:
        tid = rec.get("tweet_id") or ""
        urls = rec.get("media_urls") or []
        if not tid or not urls:
            continue
        for idx in range(len(urls)):
            k = (tid, idx)
            if k not in count_seen:
                count_seen.add(k)
                total_images += 1
    del count_seen
    processed = 0

    for rec in records:
        tweet_id = rec.get("tweet_id") or ""
        username = rec.get("username") or "unknown"
        date = rec.get("date") or ""
        text = rec.get("text") or ""
        like_source = rec.get("like_source") or ""
        urls = rec.get("media_urls") or []
        if not tweet_id or not urls:
            continue

        for index, url in enumerate(urls):
            key = (tweet_id, index)
            if key in seen:
                continue
            seen.add(key)
            processed += 1
            ext = extension_from_url(url)
            name = safe_filename_tweet_index(tweet_id, index, ext)
            dest = output_dir / name
            entry = {
                "tweet_id": tweet_id,
                "index": index,
                "path": str(dest),
                "username": username,
                "date": date,
                "text": text,
                "like_source": like_source,
            }
            if skip_existing and dest.is_file():
                manifest_entries.append(entry)
                continue
            if processed % 25 == 1 or processed == total_images:
                print(f"  Downloading {processed}/{total_images}...", file=sys.stderr)
            if download_one(url, dest, timeout=timeout, session=session):
                manifest_entries.append(entry)

    if manifest_path:
        # Append or overwrite: for run.py we'll pass a single manifest and overwrite
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest_entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return manifest_entries


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Download media from parsed archive JSON.")
    parser.add_argument("input", type=Path, nargs="?", help="Parsed JSON file (or stdin if -)")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("downloads"), help="Directory to save images")
    parser.add_argument("-m", "--manifest", type=Path, default=Path("downloads/manifest.json"), help="Manifest JSON path")
    parser.add_argument("--no-skip-existing", action="store_true", help="Re-download even if file exists")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout seconds")
    args = parser.parse_args()

    if args.input is None or (args.input == Path("-")):
        records = json.load(sys.stdin)
    else:
        records = json.loads(args.input.read_text(encoding="utf-8"))

    download_all(
        records,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        skip_existing=not args.no_skip_existing,
        timeout=args.timeout,
    )
    print(f"Manifest written to {args.manifest}", file=sys.stderr)


if __name__ == "__main__":
    main()
