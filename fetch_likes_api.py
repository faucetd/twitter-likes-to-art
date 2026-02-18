"""
Fetch liked tweets (with media) from X API v2. Uses OAuth 1.0a User Context.
Outputs the same record format as parse_archive.py for use with download_media and run.py.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests
from requests_oauthlib import OAuth1

logger = logging.getLogger(__name__)

API_BASE = "https://api.twitter.com/2"


def parse_api_tweet(
    tweet: dict[str, Any],
    users_by_id: dict[str, dict[str, Any]],
    media_by_key: dict[str, dict[str, Any]],
    photos_only: bool = True,
    like_source: str = "api",
) -> dict[str, Any] | None:
    """Convert an API v2 tweet object (with includes lookups) to a standard record.

    Returns None if the tweet has no matching media.
    """
    tweet_id = tweet.get("id") or ""
    text = tweet.get("text") or ""
    created_at = tweet.get("created_at") or ""
    date = created_at[:10] if created_at else ""
    author_id = tweet.get("author_id")
    username = "unknown"
    if author_id and author_id in users_by_id:
        username = users_by_id[author_id].get("username") or username

    att = tweet.get("attachments") or {}
    media_keys = att.get("media_keys") or []
    media_urls: list[str] = []
    for key in media_keys:
        if key in media_by_key:
            m = media_by_key[key]
            if photos_only and (m.get("type") or "").lower() != "photo":
                continue
            url = m.get("url")
            if url:
                media_urls.append(url)

    if not media_urls:
        return None
    return {
        "tweet_id": tweet_id,
        "username": username,
        "date": date,
        "media_urls": media_urls,
        "text": text,
        "like_source": like_source,
    }


def _load_dotenv() -> None:
    """Load .env from current or script directory into os.environ.
    If TWITTER_ENV is set (e.g. hareofsorrow), load .env.<value> instead of .env (for second account).
    """
    suffix = os.environ.get("TWITTER_ENV", "").strip()
    base = ".env" + (f".{suffix}" if suffix else "")
    for d in (Path.cwd(), Path(__file__).resolve().parent):
        env_file = d / base
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and v:
                        os.environ.setdefault(k, v)
            break


def get_oauth1_session() -> requests.Session:
    """Build a requests session with OAuth 1.0a for X API v2 user context."""
    _load_dotenv()
    api_key = os.environ.get("TWITTER_API_KEY") or os.environ.get("API_KEY")
    api_secret = os.environ.get("TWITTER_API_SECRET") or os.environ.get("API_SECRET")
    access_token = os.environ.get("TWITTER_ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN")
    access_secret = os.environ.get("TWITTER_ACCESS_SECRET") or os.environ.get("ACCESS_SECRET")
    if not all((api_key, api_secret, access_token, access_secret)):
        raise ValueError(
            "Missing credentials. Set TWITTER_API_KEY, TWITTER_API_SECRET, "
            "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET (or API_KEY, API_SECRET, etc.)."
        )
    auth = OAuth1(
        api_key,
        client_secret=api_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )
    session = requests.Session()
    session.auth = auth
    session.headers["User-Agent"] = "TwitterLikesDownloader/1.0"
    return session


def get_me(session: requests.Session) -> str:
    """GET /2/users/me and return the authenticated user's ID."""
    r = session.get(f"{API_BASE}/users/me", params={"user.fields": "id"})
    r.raise_for_status()
    data = r.json()
    return data["data"]["id"]


def fetch_liked_tweets(
    session: requests.Session,
    user_id: str,
    like_source_label: str = "api",
    max_results: int = 100,
    photos_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Paginate GET /2/users/:id/liked_tweets with media and user expansions.
    Return list of records: tweet_id, username, date, media_urls, text, like_source.
    """
    params = {
        "max_results": min(max_results, 100),
        "expansions": "attachments.media_keys,author_id",
        "tweet.fields": "created_at,author_id,attachments",
        "user.fields": "username",
        "media.fields": "url,type",
    }
    records: list[dict[str, Any]] = []
    next_token: str | None = None

    max_retries = 5
    while True:
        if next_token:
            params["pagination_token"] = next_token
        # Retry loop for rate limits (don't spin forever on 429)
        for _attempt in range(max_retries):
            r = session.get(
                f"{API_BASE}/users/{user_id}/liked_tweets",
                params=params,
                timeout=30,
            )
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 60))
                logger.warning("Rate limited on liked_tweets; sleeping %ds (attempt %d/%d)", retry_after, _attempt + 1, max_retries)
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
            rec = parse_api_tweet(t, users_by_id, media_by_key, photos_only=photos_only, like_source=like_source_label)
            if rec:
                records.append(rec)

        next_token = data.get("meta", {}).get("next_token")
        if not next_token:
            break
        time.sleep(0.5)

    return records


def fetch_likes(
    user_id: str | None = None,
    like_source_label: str = "api",
    output_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch all liked tweets with media for the authenticated user (or given user_id).
    If output_path is set, write JSON there. Returns same record shape as parse_archive.
    """
    session = get_oauth1_session()
    if not user_id:
        user_id = os.environ.get("TWITTER_USER_ID") or get_me(session)
    records = fetch_liked_tweets(session, user_id, like_source_label=like_source_label)
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return records


def main() -> None:
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        description="Fetch liked tweets (with media) from X API v2. Requires OAuth 1.0a env vars.",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="X user ID to fetch likes for (default: authenticated user from /2/users/me)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Write records JSON here (e.g. api_likes.json)",
    )
    parser.add_argument(
        "--label",
        default="api",
        help="like_source label in output (default: api)",
    )
    args = parser.parse_args()
    records = fetch_likes(
        user_id=args.user_id,
        like_source_label=args.label,
        output_path=str(args.output) if args.output else None,
    )
    if not args.output:
        print(json.dumps(records, indent=2, ensure_ascii=False))
    else:
        print(f"Fetched {len(records)} tweets with media; wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
