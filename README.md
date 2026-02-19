# Twitter likes → art backgrounds

Download images from your X (Twitter) liked tweets, filter for art using a
trained CLIP classifier, and rename them to `username_date_tweetid_index.ext`.

## Results

| Metric | Value |
|--------|-------|
| Archives parsed | 2 accounts, 8,845 likes |
| Unique tweets | 8,785 (after dedup) |
| Images downloaded | 8,231 |
| Training labels | 1,005 (626 keep / 379 skip) |
| Classifier accuracy | 78% (5-fold CV) |
| Images kept as art | 4,003 (49%) |
| Final output | 4,177 files (3,919 jpg + 258 png) |
| Unique artists | 1,810 |

Top artists by volume: @solisolsoli (153), @HoracioAltuna (43),
@xe0_xeo (35), @wikivictorian (30), @rezaafsharr (29), @wiresandtrees (29).

---

## Quick start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Get your X archive

X → Settings → Your account → Download an archive of your data.
Unzip into e.g. `archives/account1`.

### 3. Set up authentication

Tweet resolution uses [twikit](https://github.com/d60/twikit) (Twitter's
internal GraphQL API — free, no paid API needed). On first run you need
browser cookies. Grab `auth_token` and `ct0` from your browser dev tools
(F12 → Application → Cookies → x.com) and run the setup once:

```python
from twikit import Client
import asyncio

async def setup():
    client = Client("en-US")
    client.set_cookies({"auth_token": "YOUR_TOKEN", "ct0": "YOUR_CT0"})
    client.save_cookies("twikit_cookies.json")

asyncio.run(setup())
```

Subsequent runs reuse `twikit_cookies.json` automatically.

### 4. Run

```bash
python run.py archives/account1 -o art
```

The pipeline parses the archive, resolves tweet IDs via twikit, downloads
images from the CDN, and renames them into `art/`.

---

## Common recipes

```bash
# Two accounts at once
python run.py archives/account1 archives/account2 -o art

# Download only (no rename), limit to 500 tweets
python run.py archives/account1 --no-rename --limit 500

# With CLIP art filter (uses trained classifier if available)
python run.py archives/account1 -o art --filter-art

# Fetch from X API instead of archive (needs .env credentials)
python run.py --api -o art
```

---

## Train a personal art filter

The `--filter-art` flag uses zero-shot CLIP by default. Training a classifier
on your own labels is much more accurate (78% vs generic prompts):

```bash
# 1. Download everything first
python run.py archives/account1 archives/account2 --no-rename

# 2. Label images in browser (click to cycle: keep / skip)
python label_images.py downloads/
# ~100+ labels is enough, 1000+ is great

# 3. Train classifier
python filter_art.py train downloads/labels.json

# 4. Filter with trained classifier
python filter_art.py filter downloads/manifest.json

# 5. Rename filtered images into art/
python run.py archives/account1 archives/account2 -o art --filter-art
```

The classifier uses CLIP ViT-B-32 embeddings (512-dim) with logistic
regression. Training takes ~45s on CPU for 1,000 labels. The trained model
is saved as `art_classifier.pkl` and auto-detected on subsequent runs.

---

## Flags

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Output directory (default: `art`) |
| `--download-dir` | Staging directory (default: `downloads`) |
| `--no-download` | Parse only, print record count |
| `--no-rename` | Download only, don't rename |
| `--filter-art` | CLIP art filter (zero-shot or trained) |
| `--limit N` | Limit tweets to resolve |
| `--browser NAME` | Browser for gallery-dl fallback cookies (default: `brave`) |
| `--include-title` | Add tweet text to filenames |
| `--timeout N` | Download timeout in seconds (default: 30) |
| `--api` | Fetch likes via X API v2 instead of archive |

---

## How resolution works

Tweet ID resolution tries three strategies in order:

1. **twikit** (free) — Uses Twitter's internal GraphQL API with browser cookies.
   Handles ~20 tweets/batch, no rate limit issues for typical archive sizes.
2. **X API v2** (paid) — Bearer token auth against `api.x.com`. Falls back here
   if twikit cookies are missing. Requires pay-per-use credits ($0.005/read).
3. **gallery-dl** (free, slow) — Scrapes individual tweet pages using browser
   cookies. Last resort; rate-limited to ~140 tweets before throttling.

---

## API credentials (optional)

For `--api` mode or as a fallback, copy `.env.example` to `.env` and fill in
your OAuth 1.0a values and/or bearer token.

---

## Project layout

| File | Purpose |
|------|---------|
| `run.py` | Main pipeline: parse → resolve → download → filter → rename |
| `parse_archive.py` | Read `data/like.js` from X archives |
| `resolve_via_twikit.py` | Resolve tweet IDs via twikit (internal GraphQL API) |
| `resolve_via_scrape.py` | Fallback: resolve via gallery-dl |
| `download_media.py` | Download images from X CDN |
| `rename_and_organize.py` | Rename files to `user_date_id_idx.ext` |
| `filter_art.py` | CLIP art filter + classifier training |
| `label_images.py` | Browser UI for labeling images (keep/skip) |
| `fetch_likes_api.py` | X API v2 liked tweets (for `--api` mode) |
| `webapp/` | Web gallery for browsing filtered art (deployed separately) |

---

## Web gallery

A small FastAPI app for browsing the filtered art lives in `webapp/`.
See it live at [wall-peepo.fly.dev](https://wall-peepo.fly.dev).

---

## License

[MIT](LICENSE)
