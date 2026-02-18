"""
Parse X/Twitter data archive like.js (or liked_tweets.js) and extract
tweets that contain image media. Outputs a JSON list of records suitable
for download_media.py.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Possible locations and prefixes for likes in the archive
LIKE_FILE_NAMES = ("like.js", "liked_tweets.js")
LIKE_JS_PREFIXES = (
    "window.YTD.like.part0 = ",
    "window.YTD.liked_tweets.part0 = ",
)
DATA_DIR = "data"


def find_like_files(archive_dir: Path) -> list[Path]:
    """Find all like.js / liked_tweets.js under archive_dir (e.g. data/like.js)."""
    archive_dir = Path(archive_dir)
    found: list[Path] = []
    data_dir = archive_dir / DATA_DIR
    if not data_dir.is_dir():
        return found
    for name in LIKE_FILE_NAMES:
        p = data_dir / name
        if p.is_file():
            found.append(p)
    # Also check for part1, part2, ... (large archives are split)
    for f in data_dir.iterdir():
        if f.suffix == ".js" and "like" in f.stem.lower():
            if f not in found:
                found.append(f)
    return sorted(found)


def strip_js_prefix(raw: str) -> str:
    """Remove window.YTD.like.part0 = (or similar) to get valid JSON."""
    for prefix in LIKE_JS_PREFIXES:
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip()
    # Try regex for part0, part1, etc.
    m = re.match(r"^window\.YTD\.\w+\.part\d+\s*=\s*", raw)
    if m:
        return raw[m.end() :].strip()
    return raw.strip()


def parse_like_js(path: Path) -> list[Any]:
    """Parse a single like.js file and return the JSON array of entries."""
    text = path.read_text(encoding="utf-8", errors="replace")
    json_str = strip_js_prefix(text)
    return json.loads(json_str)


def get_tweet_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """
    Get the tweet object from an archive entry. Entry may be:
    - {"like": {"tweetId": "..."}}  -> no full tweet, return None (caller can record ID only)
    - {"like": { <full tweet> }}     -> return the inner object
    - { <full tweet> }              -> return entry
    """
    if "like" in entry:
        inner = entry["like"]
        if isinstance(inner, dict):
            # If it has only tweetId (or is empty), it's ID-only — no full tweet data
            if not inner or set(inner.keys()) <= {"tweetId", "fullText"}:
                return None
            return inner
        return None
    return entry


def get_media_urls(tweet: dict[str, Any], photos_only: bool = True) -> list[str]:
    """
    Extract image media URLs from a tweet. Prefer extended_entities, then entities.
    If photos_only, skip video/gif (type "video" or "animated_gif").
    Uses extended_entities when available (superset); falls back to entities.
    Deduplicates by URL.
    """
    urls: list[str] = []
    seen: set[str] = set()
    # extended_entities is the superset; only fall back to entities if it's absent/empty
    for key in ("extended_entities", "entities"):
        entities = tweet.get(key) or {}
        media = entities.get("media") or []
        if not media:
            continue
        for m in media:
            if not isinstance(m, dict):
                continue
            kind = (m.get("type") or "").lower()
            if photos_only and kind in ("video", "animated_gif"):
                continue
            url = m.get("media_url_https") or m.get("media_url")
            if url:
                # Prefer large size for images
                if "?" not in url and ("pbs.twimg.com" in url or "twimg.com" in url):
                    url = url + "?format=jpg&name=large"
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        # If we got results from extended_entities, skip entities (avoid dupes)
        if urls:
            break
    return urls


def get_username(tweet: dict[str, Any]) -> str:
    """Get poster username; archive may use user.screen_name or user.username."""
    user = tweet.get("user") or {}
    return user.get("username") or user.get("screen_name") or "unknown"


def get_created_at(tweet: dict[str, Any]) -> str:
    """Get tweet date as YYYY-MM-DD."""
    created = tweet.get("created_at") or tweet.get("date") or ""
    # "Wed Oct 10 20:19:24 +0000 2018" or ISO
    if not created:
        return ""
    if " " in created and "+" in created:
        parts = created.split()
        if len(parts) >= 6:
            # e.g. "Wed Oct 10 20:19:24 +0000 2018"
            month, day, year = parts[1], parts[2], parts[5]
            month_map = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05",
                         "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10",
                         "Nov": "11", "Dec": "12"}
            return f"{year}-{month_map.get(month[:3], month)}-{day.zfill(2)}"
    if created.startswith("20") and "-" in created:
        return created[:10]
    return created


def get_tweet_id(tweet: dict[str, Any]) -> str:
    """Get tweet ID string (id, id_str, or tweetId for archive format)."""
    return str(tweet.get("id") or tweet.get("id_str") or tweet.get("tweetId") or "")


def get_full_text(tweet: dict[str, Any]) -> str:
    """Get tweet text; archive may use full_text, fullText, or text."""
    return tweet.get("full_text") or tweet.get("fullText") or tweet.get("text") or ""


def extract_tweets_with_media(
    archive_dir: Path,
    like_source_label: str = "",
    include_id_only: bool = False,
) -> list[dict[str, Any]]:
    """
    From an unpacked archive directory, find like.js files, parse them,
    and return a list of records: { tweet_id, username, date, media_urls, text, like_source }.
    By default only includes tweets that have at least one image URL in the archive.
    If include_id_only=True, also emits likes that only have tweetId/fullText (media_urls=[])
    so they can be resolved via the API (resolve_tweet_ids.py).
    """
    like_files = find_like_files(archive_dir)
    if not like_files:
        return []

    records: list[dict[str, Any]] = []
    seen_tweet_ids: set[str] = set()

    for path in like_files:
        try:
            entries = parse_like_js(path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse %s: %s", path, exc)
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            tweet = get_tweet_from_entry(entry)
            if tweet is None:
                inner = entry.get("like") or {}
                tid = str(inner.get("tweetId") or "")
                if tid and tid not in seen_tweet_ids and include_id_only:
                    seen_tweet_ids.add(tid)
                    records.append({
                        "tweet_id": tid,
                        "username": "unknown",
                        "date": "",
                        "media_urls": [],
                        "text": inner.get("fullText") or "",
                        "like_source": like_source_label or str(archive_dir),
                    })
                continue

            tweet_id = get_tweet_id(tweet)
            if not tweet_id or tweet_id in seen_tweet_ids:
                continue
            media_urls = get_media_urls(tweet, photos_only=True)
            if not media_urls and not include_id_only:
                continue
            seen_tweet_ids.add(tweet_id)
            records.append({
                "tweet_id": tweet_id,
                "username": get_username(tweet),
                "date": get_created_at(tweet),
                "media_urls": media_urls or [],
                "text": get_full_text(tweet),
                "like_source": like_source_label or str(archive_dir),
            })
    return records


def main() -> None:
    """CLI: parse one or more archive dirs and print JSON to stdout or --output."""
    import argparse
    parser = argparse.ArgumentParser(description="Parse Twitter archive like.js and extract tweets with media.")
    parser.add_argument("archives", nargs="+", type=Path, help="Paths to unpacked archive directories")
    parser.add_argument("-o", "--output", type=Path, help="Write combined JSON here (default: stdout)")
    parser.add_argument("--sample", type=int, default=0, help="Print N sample tweet objects (with media) and exit")
    parser.add_argument(
        "--include-id-only",
        action="store_true",
        help="Include likes that only have tweetId/fullText (no media in archive). Use with resolve_tweet_ids.py to fetch media via API.",
    )
    args = parser.parse_args()

    all_records: list[dict[str, Any]] = []
    for arch_path in args.archives:
        label = arch_path.name
        recs = extract_tweets_with_media(arch_path, like_source_label=label, include_id_only=args.include_id_only)
        all_records.extend(recs)

    if args.sample:
        for i, r in enumerate(all_records[: args.sample]):
            print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    out = args.output
    if out:
        out.write_text(json.dumps(all_records, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        print(json.dumps(all_records, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
