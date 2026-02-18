"""
Resolve tweet IDs to full tweet records (with media) via X API v2 GET /2/tweets.
Use when your archive only contains like references (tweet IDs) and no media URLs.
Outputs the same record format as parse_archive.py for use with download_media.py.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from fetch_likes_api import API_BASE, get_oauth1_session, parse_api_tweet

logger = logging.getLogger(__name__)


def fetch_tweets_by_ids(
    session: requests.Session,
    tweet_ids: list[str],
    photos_only: bool = True,
) -> list[dict[str, Any]]:
    """
    GET /2/tweets with ids=... (batch 100), expansions for media and author.
    Returns list of records: tweet_id, username, date, media_urls, text, like_source.
    """
    records: list[dict[str, Any]] = []
    ids = [i for i in tweet_ids if i]
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        params = {
            "ids": ",".join(batch),
            "expansions": "attachments.media_keys,author_id",
            "tweet.fields": "created_at,author_id,attachments",
            "user.fields": "username",
            "media.fields": "url,type",
        }
        # Retry loop for rate limits (don't skip the batch on 429)
        for _attempt in range(5):
            r = session.get(f"{API_BASE}/tweets", params=params, timeout=30)
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 60))
                logger.warning("Rate limited on /2/tweets; sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue
            break
        r.raise_for_status()
        data = r.json()
        tweets = data.get("data") or []
        includes = data.get("includes") or {}
        users_by_id = {u["id"]: u for u in (includes.get("users") or [])}
        media_by_key = {m["media_key"]: m for m in (includes.get("media") or [])}
        for t in tweets:
            rec = parse_api_tweet(t, users_by_id, media_by_key, photos_only=photos_only, like_source="api_resolved")
            if rec:
                records.append(rec)
        time.sleep(0.5)
    return records


def main() -> None:
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        description="Resolve tweet IDs to full records (with media) via X API v2. For ID-only archives.",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help="JSON file: array of tweet IDs, or array of objects with tweet_id. Or stdin (-)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        required=True,
        help="Output JSON path (same format as parse_archive for download_media.py)",
    )
    args = parser.parse_args()

    if args.input is None or args.input == Path("-"):
        raw = json.load(sys.stdin)
    else:
        raw = json.loads(args.input.read_text(encoding="utf-8"))

    if isinstance(raw, list):
        ids = []
        for x in raw:
            if isinstance(x, str):
                ids.append(x)
            elif isinstance(x, dict) and "tweet_id" in x:
                ids.append(str(x["tweet_id"]))
            elif isinstance(x, dict) and "id" in x:
                ids.append(str(x["id"]))
        tweet_ids = ids
    else:
        tweet_ids = []

    if not tweet_ids:
        print("No tweet IDs found in input.", file=sys.stderr)
        args.output.write_text("[]", encoding="utf-8")
        return

    session = get_oauth1_session()
    records = fetch_tweets_by_ids(session, tweet_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Resolved {len(records)} tweets with media; wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
