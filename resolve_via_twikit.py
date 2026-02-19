"""
Resolve tweet IDs to media URLs using twikit (Twitter's internal GraphQL API).
No paid API credits needed — uses the same endpoints as the web client.
Requires X account credentials (username + password) or saved cookies.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """Load .env vars into os.environ (same logic as fetch_likes_api)."""
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


COOKIES_PATH = Path(__file__).resolve().parent / "twikit_cookies.json"


async def _get_client():
    """Create and authenticate a twikit Client, reusing saved cookies when possible."""
    from twikit import Client

    client = Client("en-US")

    if COOKIES_PATH.exists():
        client.load_cookies(str(COOKIES_PATH))
        return client

    _load_dotenv()
    username = os.environ.get("X_USERNAME", "")
    password = os.environ.get("X_PASSWORD", "")
    email = os.environ.get("X_EMAIL", "")

    if not username or not password:
        raise ValueError(
            "No saved cookies and no X_USERNAME / X_PASSWORD in .env. "
            "Add these to .env to enable twikit login."
        )

    await client.login(
        auth_info_1=username,
        auth_info_2=email or username,
        password=password,
    )
    client.save_cookies(str(COOKIES_PATH))
    return client


def _tweet_to_record(tweet, like_source: str = "twikit") -> dict[str, Any] | None:
    """Convert a twikit Tweet object to our standard record format."""
    media_urls: list[str] = []
    if tweet.media:
        for m in tweet.media:
            url = getattr(m, "media_url", None) or getattr(m, "media_url_https", None)
            if url and hasattr(m, "type") and m.type == "photo":
                media_urls.append(url)

    if not media_urls:
        return None

    username = "unknown"
    if tweet.user:
        username = tweet.user.screen_name or tweet.user.name or "unknown"

    date = ""
    created = getattr(tweet, "created_at_datetime", None) or getattr(tweet, "created_at", None)
    if created:
        try:
            date = created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else str(created)[:10]
        except Exception:
            pass

    return {
        "tweet_id": tweet.id,
        "username": username,
        "date": date,
        "media_urls": media_urls,
        "text": tweet.text or "",
        "like_source": like_source,
    }


async def _resolve_batch(
    client,
    tweet_ids: list[str],
    photos_only: bool = True,
    batch_size: int = 20,
    delay: float = 1.0,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Fetch tweets by ID in batches. Returns (records_with_media, all_resolved_ids)."""
    records: list[dict[str, Any]] = []
    resolved: set[str] = set()
    total = len(tweet_ids)
    failed_streak = 0

    for i in range(0, total, batch_size):
        batch = tweet_ids[i : i + batch_size]

        try:
            tweets = await client.get_tweets_by_ids(batch)
            resolved.update(batch)
            failed_streak = 0

            for tw in tweets:
                if tw is None:
                    continue
                rec = _tweet_to_record(tw)
                if rec:
                    records.append(rec)

        except Exception as exc:
            failed_streak += 1
            err_msg = str(exc)
            print(
                f"  twikit batch {i//batch_size + 1}: error ({err_msg[:80]})",
                file=sys.stderr, flush=True,
            )
            if failed_streak >= 3:
                print(
                    f"  3 consecutive failures — stopping. Resolved {len(resolved)}/{total}.",
                    file=sys.stderr, flush=True,
                )
                break
            if "rate" in err_msg.lower() or "429" in err_msg:
                wait = min(60 * (2 ** failed_streak), 900)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr, flush=True)
                await asyncio.sleep(wait)
                continue

        processed = min(i + batch_size, total)
        print(
            f"  twikit: {processed}/{total} looked up, {len(records)} with media",
            file=sys.stderr, flush=True,
        )
        if i + batch_size < total:
            await asyncio.sleep(delay)

    return records, resolved


def resolve_tweets(
    tweet_ids: list[str],
    photos_only: bool = True,
    batch_size: int = 20,
    delay: float = 1.0,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Synchronous entry point. Returns (records_with_media, resolved_ids)."""

    async def _run():
        client = await _get_client()
        return await _resolve_batch(
            client, tweet_ids,
            photos_only=photos_only,
            batch_size=batch_size,
            delay=delay,
        )

    return asyncio.run(_run())


def main() -> None:
    """CLI: resolve a list of tweet IDs from stdin or arguments."""
    import argparse

    parser = argparse.ArgumentParser(description="Resolve tweet IDs via twikit (internal API)")
    parser.add_argument("ids", nargs="*", help="Tweet IDs to look up")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between batches")
    args = parser.parse_args()

    ids = args.ids
    if not ids and not sys.stdin.isatty():
        ids = [line.strip() for line in sys.stdin if line.strip()]

    if not ids:
        parser.error("No tweet IDs provided")

    print(f"Resolving {len(ids)} tweet IDs via twikit...", file=sys.stderr, flush=True)
    records, resolved = resolve_tweets(ids, batch_size=args.batch_size, delay=args.delay)
    print(f"Done: {len(records)} tweets with media, {len(resolved)} total resolved.", file=sys.stderr, flush=True)
    print(json.dumps(records, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
