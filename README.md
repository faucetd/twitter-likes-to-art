# Twitter likes → art backgrounds

Turn your X (Twitter) liked tweets into a local folder of images named `username_date_tweetid_index.ext`, with optional filtering for “art” only. Supports one or two accounts (archives and/or API).

**No scraping.** Data comes from your **downloaded X archive** (no API keys) and/or **X API v2** (OAuth 1.0a). No browser automation.

---

## What it does

1. **Get likes** – From unpacked X archives (`data/like.js`) and/or the X API (`GET /2/users/:id/liked_tweets`).
2. **Resolve IDs** – If your archive only has tweet IDs (no media URLs), optionally resolve them via the API to get image URLs.
3. **Download** – Fetch images into a staging folder; dedupe by tweet ID across accounts.
4. **Rename** – Move to a final folder with filenames like `artistname_2024-03-15_1234567890_0.jpg`.
5. **Optional** – Filter to “art-like” images with a CLIP-based step.

Output is a single directory of images (and optional `metadata.json`) you can use as backgrounds or reference.

---

## Requirements

- Python 3.10+
- For **archive-only** use: no API keys (you only need your X data export).
- For **API** or **ID-only archives**: [X Developer account](https://developer.x.com) and an app with OAuth 1.0a User authentication (Read). See [docs/CREDENTIALS.md](docs/CREDENTIALS.md) so you don’t mix tokens between apps.

---

## Quick start

### 1. Install

```bash
git clone <this-repo>
cd twitter_scraper
pip install -r requirements.txt
```

### 2. Get your data

- **Archive:** X → Settings → Your account → Download an archive of your data. Wait for the email, download the ZIP, unzip into e.g. `archives/account1`.
- **API (optional):** Create an app in the [developer portal](https://developer.x.com), enable User authentication (OAuth 1.0a, Read), then generate **Access Token and Secret** for your user. Put all four OAuth 1.0a values into a `.env` file (see [Credentials](#credentials)).

### 3. Run

**Archive with full tweet data (older exports):**

```bash
python run.py --source archive --archives archives/account1 --output art
```

**Archive with only tweet IDs (newer exports) – resolve via API then download:**

```bash
python run.py --source archive --archives archives/account1 --output art --resolve-ids
```

**API only (no archive):**

```bash
python run.py --source api --output art
```

**Two accounts:** Run once per account (different archives and/or different env), then merge the output folders if you want.

```bash
# Account 1 (uses .env)
python run.py --source archive --archives archives/account1 --output art --resolve-ids

# Account 2 (uses .env.hareofsorrow when TWITTER_ENV is set)
TWITTER_ENV=hareofsorrow python run.py --source archive --archives archives/account2 --output art_hare --resolve-ids
```

---

## Data sources

| Source | How | When to use |
|--------|-----|-------------|
| **Archive** | Parse `data/like.js` from your downloaded X ZIP. | No API keys; one-time export. Newer archives may be ID-only → use `--resolve-ids`. |
| **API** | `GET /2/users/:id/liked_tweets` with OAuth 1.0a. | Fresh data; need developer app + user tokens. |

---

## Credentials

- Copy [.env.example](.env.example) to `.env` and fill in the four OAuth 1.0a values.
- **All four must be from the same X Developer app** (Consumer Key/Secret + Access Token/Secret for one user in that app). Mixing apps or users causes auth errors. See **[docs/CREDENTIALS.md](docs/CREDENTIALS.md)** for details and a checklist.
- For a second account, create e.g. `.env.hareofsorrow` with that account’s four values and run with `TWITTER_ENV=hareofsorrow`.
- **App ↔ account mapping (example):** screapa app = @destroyerfaucet (use `.env`); screapa2 app = @hareofsorrow (use `.env.hareofsorrow`). See [docs/CREDENTIALS.md](docs/CREDENTIALS.md).

Never commit `.env` or `.env.*` (they are in `.gitignore`).

---

## Usage reference

| Goal | Command |
|------|--------|
| Archive only (no API) | `python run.py --source archive --archives archives/account1 -o art` |
| Archive + resolve IDs via API | `python run.py --source archive --archives archives/account1 -o art --resolve-ids` |
| API only | `python run.py --source api -o art` |
| Second account | `TWITTER_ENV=hareofsorrow python run.py --source archive --archives archives/account2 -o art_hare --resolve-ids` |
| Filter to “art” (needs CLIP deps) | Add `--filter-art` |
| Tweet title in filename | Add `--include-title` |
| Parse/fetch only (no download) | Add `--no-download` |

Step-by-step (advanced):

```bash
python parse_archive.py archives/account1 -o parsed.json --include-id-only
python resolve_tweet_ids.py parsed.json -o resolved.json   # needs .env
python download_media.py resolved.json -o downloads -m downloads/manifest.json
python rename_and_organize.py downloads/manifest.json -o art --sidecar art/metadata.json
```

---

## Output

- **art/** (or `--output`) – Images named `username_YYYY-MM-DD_tweetid_index.ext`; optional `metadata.json`.
- **downloads/** – Staging images and `manifest.json` (and `art_manifest.json` if you used `--filter-art`).

---

## Optional: art filter (CLIP)

To keep only “art-like” images:

```bash
pip install open-clip-torch torch Pillow
python run.py --source archive --archives archives/account1 -o art --resolve-ids --filter-art
```

---

## Project layout

- **run.py** – Main entry (archive or API → download → rename; optional resolve-ids and filter-art).
- **parse_archive.py** – Reads `data/like.js`; supports full tweets and ID-only (`--include-id-only`).
- **fetch_likes_api.py** – Fetches liked tweets (with media) via X API v2; loads `.env` or `.env.$TWITTER_ENV`.
- **resolve_tweet_ids.py** – Resolves tweet IDs to full tweets + media via API (for ID-only archives).
- **download_media.py** – Downloads image URLs; writes `downloads/` and manifest.
- **rename_and_organize.py** – Renames/moves to final filenames and optional metadata.
- **filter_art.py** – Optional CLIP-based art filter.
- **docs/CREDENTIALS.md** – How to set up and avoid mixing API tokens.
- **docs/IMPROVEMENTS.md** – Ideas for improving the repo (security, tests, features, open source).

---

## Improving the repo

See **[docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md)** for concrete ideas (security, testing, two-account-in-one-run, progress bars, contributing guide, license, etc.) and for making this ready for open source.

---

## License

Add a LICENSE file (e.g. MIT) when you open-source the project.
