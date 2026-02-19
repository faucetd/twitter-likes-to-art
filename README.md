# twitter-likes-to-art

Download images from your X (Twitter) liked tweets, optionally filter for art
with a CLIP classifier, and rename them to clean filenames like
`username_date_tweetid_1.jpg`. Includes a Tinder-style voting webapp for
ranking your favorites.

## What this does

```
X archive  ──→  parse  ──→  resolve tweet IDs  ──→  download images
                                                         │
                                          ┌──────────────┘
                                          ▼
                                    (optional) CLIP art filter
                                          │
                                          ▼
                                    rename & organize  ──→  art/
                                          │
                                          ▼
                                    (optional) voting webapp
```

1. **Parse** your X data archive to extract liked tweet IDs and media URLs
2. **Resolve** ID-only tweets to get their media URLs (many archives only store IDs)
3. **Download** images from the X CDN
4. **Filter** (optional) using CLIP to keep only art/illustrations
5. **Rename** files to `username_date_tweetid_index.ext` with a metadata sidecar

## Prerequisites

- Python 3.10+
- An X (Twitter) account
- Your X data archive (Settings → Your account → Download an archive of your data)

## Setup

### 1. Clone and install

```bash
git clone https://github.com/faucetd/twitter-likes-to-art.git
cd twitter-likes-to-art
pip install -r requirements.txt
```

The core pipeline needs only `requests`, `twikit`, and `gallery-dl`. The CLIP
art filter and webapp have additional dependencies — see
[Optional dependencies](#optional-dependencies) below.

### 2. Prepare your archive

Request your data from X (Settings → Your account → Download an archive of your
data). This can take 24–48 hours. Once you get the zip:

```bash
mkdir -p archives
unzip twitter-archive.zip -d archives/myaccount
```

The pipeline looks for `data/like.js` (or `data/likes.js`) inside the archive
directory.

### 3. Authenticate for tweet resolution

Most archives only contain tweet IDs, not media URLs. The pipeline resolves
these IDs using [twikit](https://github.com/d60/twikit), which talks to X's
internal GraphQL API — no paid developer account needed.

**Option A — Browser cookies (recommended):**

1. Log into x.com in your browser
2. Open DevTools (F12) → Application → Cookies → `https://x.com`
3. Copy the values for `auth_token` and `ct0`
4. Run this once to save them:

```python
from twikit import Client
import asyncio

async def setup():
    client = Client("en-US")
    client.set_cookies({"auth_token": "PASTE_AUTH_TOKEN", "ct0": "PASTE_CT0"})
    client.save_cookies("twikit_cookies.json")

asyncio.run(setup())
```

Cookies expire after a few weeks — repeat when that happens.

**Option B — Username and password:**

Copy `.env.example` to `.env` and fill in:

```
X_USERNAME=your_username
X_PASSWORD=your_password
X_EMAIL=your_email
```

twikit will log in and save cookies on first run.

### 4. Run the pipeline

```bash
python run.py archives/myaccount -o art
```

This parses the archive, resolves tweet IDs, downloads images, and renames them
into `art/`. Progress is printed to stderr.

## Usage

### Basic recipes

```bash
# Single archive → art/
python run.py archives/myaccount -o art

# Multiple archives at once (dedupes across accounts)
python run.py archives/account1 archives/account2 -o art

# Download only, don't rename (useful before labeling/filtering)
python run.py archives/myaccount --no-rename

# Limit to first 500 tweets (good for testing)
python run.py archives/myaccount --no-rename --limit 500

# With CLIP art filter
python run.py archives/myaccount -o art --filter-art

# Fetch likes via X API v2 instead of archive (needs paid API credentials)
python run.py --api -o art
```

### CLI flags

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Output directory for renamed images (default: `art`) |
| `--download-dir` | Staging directory for raw downloads (default: `downloads`) |
| `--no-download` | Parse only — print record count, don't download |
| `--no-rename` | Download but don't rename/move to output |
| `--filter-art` | Apply CLIP art filter before renaming |
| `--limit N` | Cap number of tweets to resolve |
| `--browser NAME` | Browser for gallery-dl cookie extraction (default: `brave`) |
| `--include-title` | Embed sanitized tweet text in filenames |
| `--timeout N` | Per-image download timeout in seconds (default: 30) |
| `--api` | Fetch likes from X API v2 instead of archive |

### Output format

Renamed files follow the pattern:

```
{username}_{YYYY-MM-DD}_{tweetid}_{index}.{ext}
```

A `metadata.json` sidecar is written alongside with full tweet metadata
(username, date, tweet text, original URLs, etc.).

## Art filtering

The `--filter-art` flag uses [CLIP](https://openai.com/research/clip) to
classify images. Two modes are available:

### Zero-shot (no training needed)

Works out of the box — scores images against art vs. non-art text prompts.
Decent for obvious cases but not great at matching your personal taste.

```bash
python run.py archives/myaccount -o art --filter-art
```

### Trained classifier (recommended)

Train a simple logistic regression on CLIP embeddings using your own labels.
Much more accurate since it learns *your* definition of "art I want."

```bash
# 1. Download everything first
python run.py archives/myaccount --no-rename

# 2. Label images in your browser (click to cycle: keep / skip)
python label_images.py downloads/
# Opens http://localhost:8421 — label at least ~100 images, more is better

# 3. Train the classifier
python filter_art.py train downloads/labels.json

# 4. Apply the filter
python filter_art.py filter downloads/manifest.json

# 5. Full pipeline with trained classifier (auto-detected)
python run.py archives/myaccount -o art --filter-art
```

The classifier is saved as `art_classifier.pkl` and automatically used by
`--filter-art` when present. Training takes ~45 seconds on CPU for 1,000 labels.

<details>
<summary>Example results</summary>

With ~1,000 hand-labeled images (626 keep / 379 skip) across two accounts:

| Metric | Value |
|--------|-------|
| Training labels | 1,005 |
| Classifier accuracy | 78% (5-fold CV) |
| Images kept as art | ~49% of downloads |

</details>

## How tweet resolution works

Archives from X often contain only tweet IDs without media URLs. The pipeline
resolves these using three strategies, tried in order:

1. **twikit** (free) — Twitter's internal GraphQL API, same as the web client.
   Batches ~20 tweets per request. Works reliably for typical archive sizes.
2. **X API v2** (paid, optional) — Bearer token or OAuth 1.0a against
   `api.x.com`. Falls back here if twikit is unavailable. Costs ~$0.005 per
   tweet read.
3. **gallery-dl** (free, slow) — Scrapes individual tweet pages using browser
   cookies. Last resort — rate-limited to ~140 tweets before throttling.

Most users only need twikit (strategy 1).

## Webapp — Wall Peepo

A Tinder-style voting app for ranking your art. Swipe right to keep, left to
skip, up to superlike. Images are scored with an Elo rating system.

**Features:**
- Swipe/drag/keyboard interface
- Elo-based scoring with superlike support
- Leaderboard dashboard with stats
- Artist attribution with links to original tweets
- Perceptual-hash deduplication (`python -m webapp.dedup`)

### Run locally

```bash
pip install fastapi uvicorn[standard] Pillow imagehash
uvicorn webapp.app:app --reload --port 8000
```

The app serves images from `art/` and stores votes in a local SQLite database.

### Deploy to Fly.io

```bash
fly launch    # first time
fly deploy    # subsequent deploys
```

See `fly.toml` and `Dockerfile` for configuration. The deployed app uses a
persistent volume for the database.

## Project layout

| File | Purpose |
|------|---------|
| `run.py` | Main pipeline orchestrator |
| `parse_archive.py` | Parse `data/like.js` from X archives |
| `resolve_via_twikit.py` | Resolve tweet IDs via twikit (internal GraphQL) |
| `resolve_via_scrape.py` | Fallback resolution via gallery-dl |
| `download_media.py` | Download images from X CDN (with host allowlist) |
| `rename_and_organize.py` | Rename files + write metadata sidecar |
| `filter_art.py` | CLIP art filter + classifier training |
| `label_images.py` | Browser-based image labeling UI |
| `fetch_likes_api.py` | X API v2 integration (for `--api` mode) |
| `webapp/` | Voting webapp (FastAPI + vanilla JS) |
| `webapp/dedup.py` | Perceptual-hash image deduplication |

## Optional dependencies

The core pipeline (`run.py`) only needs:

```
requests, twikit, gallery-dl
```

Additional features require:

| Feature | Packages | Install |
|---------|----------|---------|
| Art filter (`--filter-art`) | `open-clip-torch`, `torch`, `Pillow`, `scikit-learn` | `pip install open-clip-torch torch pillow scikit-learn` |
| Webapp | `fastapi`, `uvicorn`, `Pillow`, `imagehash` | `pip install fastapi uvicorn[standard] Pillow imagehash` |

## API credentials (optional)

For `--api` mode or as a paid fallback, copy `.env.example` to `.env` and fill
in your X developer credentials. See [docs/CREDENTIALS.md](docs/CREDENTIALS.md)
for full setup instructions covering all authentication methods.

## Troubleshooting

**"twikit unavailable" or cookie errors**
Your cookies have expired. Grab fresh `auth_token` and `ct0` from your browser
and re-run the setup snippet above. Delete `twikit_cookies.json` first.

**gallery-dl hangs or gets rate-limited**
This is expected — X throttles after ~140 requests. The pipeline falls back to
gallery-dl only as a last resort. Make sure twikit is configured so it handles
the bulk of resolution.

**"No module named 'open_clip'" when using --filter-art**
The CLIP dependencies are optional. Install them:
`pip install open-clip-torch torch pillow`

**Images downloading slowly**
The X CDN can be slow for large batches. Use `--timeout` to increase the
per-image timeout, and `--limit` to test with a smaller set first.

**Port 8421 already in use (label_images.py)**
Kill the old process: `lsof -ti:8421 | xargs kill -9`

## License

[MIT](LICENSE)
