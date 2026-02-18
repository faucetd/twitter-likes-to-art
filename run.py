#!/usr/bin/env python3
"""
End-to-end pipeline: parse one or more Twitter archives (or fetch via X API),
download media, rename to username_date_tweetid_index.ext, and optionally filter for art.
Dedupes across accounts by tweet_id.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# Local modules
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
        description="Twitter likes → art backgrounds: parse archives or fetch via API, download media, rename, optional art filter.",
    )
    parser.add_argument(
        "--source",
        choices=("archive", "api"),
        default="archive",
        help="Data source: archive (parse local like.js) or api (X API v2 liked_tweets). Default: archive",
    )
    parser.add_argument(
        "--archives",
        nargs="+",
        type=Path,
        default=None,
        help="Paths to unpacked archive directories (required if --source=archive). Ignored if --source=api",
    )
    parser.add_argument(
        "--api-user-id",
        default=None,
        help="X user ID for API (only with --source=api). If omitted, uses authenticated user from /2/users/me.",
    )
    parser.add_argument(
        "--output",
        "-o",
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
        help="Run CLIP art filter and keep only art-like images (requires filter_art.py deps)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Download timeout per image (default: 30)",
    )
    parser.add_argument(
        "--resolve-ids",
        action="store_true",
        help="When using archive: include ID-only likes and resolve them via X API (needs API env vars). Use if your archive has no media URLs.",
    )
    args = parser.parse_args()

    all_records: list[dict[str, Any]] = []

    if args.source == "archive":
        if not args.archives:
            parser.error("--archives is required when --source=archive")
        include_id_only = args.resolve_ids
        for arch in args.archives:
            arch = Path(arch)
            if not arch.is_dir():
                print(f"Warning: not a directory: {arch}", file=sys.stderr)
                continue
            label = arch.name
            recs = extract_tweets_with_media(arch, like_source_label=label, include_id_only=include_id_only)
            all_records.extend(recs)
        if include_id_only:
            print(f"Parsed {len(all_records)} likes from archives (ID-only; will resolve via API).", file=sys.stderr)
        else:
            print(f"Parsed {len(all_records)} tweets with media from archives.", file=sys.stderr)
    else:
        # --source=api: fetch via X API v2 (one account per run; for two accounts run twice with different env and merge)
        from fetch_likes_api import get_oauth1_session, get_me, fetch_liked_tweets
        session = get_oauth1_session()
        user_id = args.api_user_id or get_me(session)
        all_records = fetch_liked_tweets(session, user_id, like_source_label="api")
        print(f"Fetched {len(all_records)} tweets with media from API.", file=sys.stderr)

    # Dedupe by tweet_id across archives / API calls (keep first occurrence)
    seen_ids: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in all_records:
        tid = r.get("tweet_id") or ""
        if tid and tid not in seen_ids:
            seen_ids.add(tid)
            unique.append(r)

    # If archive had only IDs (--resolve-ids), resolve via API to get media
    if args.source == "archive" and args.resolve_ids and unique:
        id_only = [r for r in unique if not r.get("media_urls")]
        if id_only:
            try:
                from fetch_likes_api import get_oauth1_session as _get_session
                from resolve_tweet_ids import fetch_tweets_by_ids
                session = _get_session()
                ids = [r["tweet_id"] for r in id_only]
                resolved = fetch_tweets_by_ids(session, ids)
                # Replace ID-only records with resolved ones, keep records that already had media
                unique = [r for r in unique if r.get("media_urls")] + resolved
                print(f"Resolved {len(resolved)} tweets with media via API.", file=sys.stderr)
            except ValueError as e:
                print(f"Error: {e}. Set TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET.", file=sys.stderr)
                sys.exit(1)
        print(f"Total {len(unique)} unique tweets.", file=sys.stderr)
    else:
        print(f"Total {len(unique)} unique tweets with media.", file=sys.stderr)
    if args.no_download:
        if unique:
            print(json.dumps(unique[:3], indent=2, ensure_ascii=False))
        return

    # 2. Download
    manifest_path = args.download_dir / "manifest.json"
    download_all(
        unique,
        output_dir=args.download_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        timeout=args.timeout,
    )

    if args.no_rename:
        print(f"Downloads in {args.download_dir}, manifest at {manifest_path}", file=sys.stderr)
        return

    # 3. Optional art filter: keep only art-like images (writes subset manifest)
    manifest_to_rename = manifest_path
    if args.filter_art:
        try:
            from filter_art import filter_art_from_manifest
            art_manifest = filter_art_from_manifest(manifest_path, args.download_dir)
            if art_manifest and art_manifest.is_file():
                manifest_to_rename = art_manifest
        except ImportError as e:
            print(f"Warning: --filter-art requested but filter_art failed: {e}", file=sys.stderr)

    # 4. Rename and move to output dir
    rename_from_manifest(
        manifest_to_rename,
        args.output,
        include_title=args.include_title,
        sidecar_path=args.output / "metadata.json",
    )

    print(f"Done. Output in {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
