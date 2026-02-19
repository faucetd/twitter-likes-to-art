#!/usr/bin/env python3
"""
End-to-end pipeline: parse one or more Twitter archives (or fetch via X API),
download media, rename to username_date_tweetid_index.ext, and optionally filter for art.
Dedupes across accounts by tweet_id.

Archives with only tweet IDs (no embedded media) are automatically resolved
via gallery-dl using browser cookies.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from parse_archive import extract_tweets_with_media
from download_media import download_all
from rename_and_organize import rename_from_manifest


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    import argparse
    parser = argparse.ArgumentParser(
        description="Twitter likes → art backgrounds: download, rename, and optionally filter.",
    )

    parser.add_argument(
        "archives",
        nargs="*",
        type=Path,
        help="Unpacked archive directories (e.g. archives/account1 archives/account2)",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Fetch likes via X API v2 instead of archives (needs .env credentials)",
    )
    parser.add_argument(
        "--api-user-id",
        default=None,
        help="X user ID for --api mode. If omitted, uses authenticated user.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("art"),
        help="Final output directory for renamed images (default: art)",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("downloads"),
        help="Staging directory for downloads (default: downloads)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Only parse and print record count (no download/rename)",
    )
    parser.add_argument(
        "--no-rename",
        action="store_true",
        help="Download only; do not rename/move to --output",
    )
    parser.add_argument(
        "--include-title",
        action="store_true",
        help="Embed sanitized tweet text in filenames",
    )
    parser.add_argument(
        "--filter-art",
        action="store_true",
        help="Run CLIP art filter and keep only art-like images",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Download timeout per image in seconds (default: 30)",
    )
    parser.add_argument(
        "--browser",
        default="brave",
        help="Browser for cookie extraction when resolving ID-only archives (default: brave). "
        "The browser must be closed during the run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of tweets to resolve via gallery-dl.",
    )
    args = parser.parse_args()

    if not args.archives and not args.api:
        parser.error("Provide archive directories or use --api")

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    all_records: list[dict[str, Any]] = []

    # --- Step 1: Parse ---
    if args.api:
        log("[1/5] Fetching likes via X API...")
        from fetch_likes_api import get_oauth1_session, get_me, fetch_liked_tweets
        session = get_oauth1_session()
        user_id = args.api_user_id or get_me(session)
        all_records = fetch_liked_tweets(session, user_id, like_source_label="api")
        log(f"[1/5] Fetched {len(all_records)} tweets with media from API.")
    else:
        log(f"[1/5] Parsing {len(args.archives)} archive(s)...")
        for arch in args.archives:
            arch = Path(arch)
            if not arch.is_dir():
                log(f"  Warning: not a directory: {arch}")
                continue
            recs = extract_tweets_with_media(
                arch, like_source_label=arch.name, include_id_only=True,
            )
            log(f"  {arch.name}: {len(recs)} likes")
            all_records.extend(recs)
        log(f"[1/5] Parsed {len(all_records)} likes total.")

    # Dedupe by tweet_id across archives / API calls
    seen_ids: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in all_records:
        tid = r.get("tweet_id") or ""
        if tid and tid not in seen_ids:
            seen_ids.add(tid)
            unique.append(r)

    log(f"[1/5] {len(unique)} unique tweets after dedup.")

    if args.no_download:
        if unique:
            print(json.dumps(unique[:3], indent=2, ensure_ascii=False))
        return

    # --- Step 2: Resolve ID-only records ---
    manifest_path = args.download_dir / "manifest.json"
    id_only = [r for r in unique if not r.get("media_urls")]
    has_media = [r for r in unique if r.get("media_urls")]

    all_entries: list[dict[str, Any]] = []

    if id_only:
        if args.limit:
            id_only = id_only[:args.limit]
            log(f"[2/5] Limited to {len(id_only)} tweets (--limit {args.limit}).")

        unresolved = id_only  # tracks what still needs fallback

        # Strategy: twikit (free, internal API) → paid X API → gallery-dl
        try:
            from resolve_via_twikit import resolve_tweets
            log(f"[2/5] Resolving {len(id_only)} tweets via twikit (internal API)...")
            resolved_records, resolved_ids = resolve_tweets(
                [r["tweet_id"] for r in id_only],
            )
            if resolved_records:
                has_media.extend(resolved_records)
                log(f"[2/5] twikit resolved {len(resolved_records)} tweets with media.")
            unresolved = [r for r in id_only if r["tweet_id"] not in resolved_ids]
            if unresolved:
                log(f"[2/5] {len(unresolved)} tweets unresolved by twikit.")
            else:
                log("[2/5] All tweets resolved via twikit.")
        except Exception as exc:
            log(f"[2/5] twikit unavailable: {exc}")
            log("[2/5] Falling back to paid X API...")
            try:
                from fetch_likes_api import get_bearer_session, get_oauth1_session, fetch_tweets_by_ids
                session = get_bearer_session()
                if session:
                    log("[2/5] Using bearer token auth...")
                else:
                    session = get_oauth1_session()
                    log("[2/5] Using OAuth 1.0a auth...")
                resolved_records, resolved_ids = fetch_tweets_by_ids(
                    session,
                    [r["tweet_id"] for r in unresolved],
                )
                if resolved_records:
                    has_media.extend(resolved_records)
                    log(f"[2/5] API resolved {len(resolved_records)} tweets with media.")
                unresolved = [r for r in unresolved if r["tweet_id"] not in resolved_ids]
            except Exception as exc2:
                log(f"[2/5] Paid API also unavailable: {exc2}")

        if unresolved:
            from resolve_via_scrape import resolve_and_download
            log(f"[2/5] Resolving {len(unresolved)} remaining tweets via gallery-dl (browser: {args.browser})...")
            scrape_entries = resolve_and_download(
                unresolved,
                output_dir=args.download_dir,
                manifest_path=manifest_path,
                browser=args.browser,
            )
            all_entries.extend(scrape_entries)
            log(f"[2/5] gallery-dl: {len(scrape_entries)} images.")
    else:
        log("[2/5] No ID-only tweets to resolve.")

    # --- Step 3: Download from CDN ---
    if has_media:
        log(f"[3/5] Downloading {len(has_media)} tweets with CDN URLs...")
        cdn_manifest = args.download_dir / "_manifest_cdn.json"
        cdn_entries = download_all(
            has_media,
            output_dir=args.download_dir,
            manifest_path=cdn_manifest,
            skip_existing=True,
            timeout=args.timeout,
        )
        all_entries.extend(cdn_entries)
        cdn_manifest.unlink(missing_ok=True)
        log(f"[3/5] Downloaded {len(cdn_entries)} images.")
    else:
        log("[3/5] No CDN downloads needed.")

    manifest_path.write_text(
        json.dumps(all_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log(f"[3/5] Manifest: {len(all_entries)} images total.")

    if args.no_rename:
        log(f"Downloads in {args.download_dir}, manifest at {manifest_path}")
        return

    # --- Step 4: Art filter ---
    manifest_to_rename = manifest_path
    if args.filter_art:
        log("[4/5] Running art filter...")
        try:
            from filter_art import filter_art_from_manifest
            art_manifest = filter_art_from_manifest(manifest_path, args.download_dir)
            if art_manifest and art_manifest.is_file():
                manifest_to_rename = art_manifest
                kept = len(json.loads(art_manifest.read_text(encoding="utf-8")))
                log(f"[4/5] Art filter kept {kept}/{len(all_entries)} images.")
        except ImportError as e:
            log(f"[4/5] Warning: --filter-art failed: {e}")
    else:
        log("[4/5] Skipping art filter (use --filter-art to enable).")

    # --- Step 5: Rename ---
    log(f"[5/5] Renaming to {args.output}/...")
    rename_from_manifest(
        manifest_to_rename,
        args.output,
        include_title=args.include_title,
        sidecar_path=args.output / "metadata.json",
    )

    log(f"[5/5] Done. Output in {args.output}")


if __name__ == "__main__":
    main()
