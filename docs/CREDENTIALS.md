# Authentication setup

This project supports three ways to resolve tweet IDs, each with different
auth requirements. You only need **one** to work.

## 1. twikit (recommended — free, no API keys)

twikit uses Twitter's internal GraphQL API with your browser session cookies.

### First-time setup

1. Log into x.com in your browser
2. Open Dev Tools (F12) → Application → Cookies → `https://x.com`
3. Copy the values for `auth_token` and `ct0`
4. Run once:

```python
from twikit import Client
import asyncio

async def setup():
    client = Client("en-US")
    client.set_cookies({"auth_token": "YOUR_TOKEN", "ct0": "YOUR_CT0"})
    client.save_cookies("twikit_cookies.json")

asyncio.run(setup())
```

Subsequent runs reuse `twikit_cookies.json` automatically. Cookies expire
after a few weeks — just repeat the steps above when that happens.

### Alternative: username/password login

Add to `.env`:

```
X_USERNAME=your_username
X_PASSWORD=your_password
X_EMAIL=your_email
```

twikit will log in and save cookies on first run.

---

## 2. X API v2 (paid, for `--api` mode)

OAuth 1.0a is used for user-context endpoints (fetching your likes).
Bearer tokens are used for app-only endpoints (tweet lookup by ID).

### Setup

1. Create an app at [developer.x.com](https://developer.x.com)
2. Copy `.env.example` to `.env` and fill in your credentials

All four OAuth values must come from the **same** developer app:

| Variable | Source |
|----------|--------|
| `TWITTER_API_KEY` | Consumer Key |
| `TWITTER_API_SECRET` | Consumer Key Secret |
| `TWITTER_ACCESS_TOKEN` | Access Token (generated for your user) |
| `TWITTER_ACCESS_SECRET` | Access Token Secret |
| `TWITTER_BEARER_TOKEN` | Bearer Token (for tweet lookup) |

### Multiple accounts

Use `TWITTER_ENV` to switch between credential files:

```bash
# Default: uses .env
python run.py --api

# Second account: uses .env.myother
TWITTER_ENV=myother python run.py --api
```

---

## 3. gallery-dl (free, slow fallback)

gallery-dl uses your browser cookies directly. No API keys needed, but it's
rate-limited to ~140 tweets before X throttles it.

Your browser must be **closed** during the run. Use `--browser` to specify
which browser to read cookies from (default: `brave`).

---

## Security checklist

- [ ] `.env` files are in `.gitignore` (they are by default)
- [ ] `twikit_cookies.json` is in `.gitignore` (it is by default)
- [ ] No credentials are committed to git
- [ ] If credentials were compromised, regenerate them in the developer portal
