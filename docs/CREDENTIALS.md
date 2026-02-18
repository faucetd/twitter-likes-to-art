# Credentials and token setup

## Important: one app = one set of four values

OAuth 1.0a uses **four** values. **All four must come from the same X Developer app** for a given account:

| Variable | Where it comes from |
|----------|----------------------|
| `TWITTER_API_KEY` | **Consumer Key** (same app) |
| `TWITTER_API_SECRET` | **Consumer Key Secret** (same app) |
| `TWITTER_ACCESS_TOKEN` | **Access Token** – generated for a *user* (e.g. @destroyerfaucet) **in that same app** |
| `TWITTER_ACCESS_SECRET` | **Access Token Secret** – generated together with the Access Token |

**Common mix-up:** Using the Consumer Key/Secret from *App A* and the Access Token/Secret from *App B* (or from a different user in another app). The API will reject that. For each `.env` file, ensure:

- Consumer Key + Consumer Secret = from **one** developer app  
- Access Token + Access Token Secret = generated in **that same app** for the X account you want to fetch likes for  

## Per-account env files

| Env file | X Developer app | Account | How to use |
|----------|------------------|---------|------------|
| **`.env`** | **screapa** | @destroyerfaucet | Default (no `TWITTER_ENV`). All four OAuth 1.0a values from the **screapa** app. |
| **`.env.hareofsorrow`** | **screapa2** | @hareofsorrow | Run with `TWITTER_ENV=hareofsorrow`. All four values from the **screapa2** app. |

- **screapa** = destroyerfaucet’s app  
- **screapa2** = hareofsorrow’s app  

If you have `.env.screapa2`, it’s the same app as hareofsorrow; use `.env.hareofsorrow` (which has the full four credentials) and `TWITTER_ENV=hareofsorrow` when running for that account.

## Checklist

- [ ] I have one X Developer app per account (or one app and one Access Token per user).
- [ ] For each `.env.*` file, Consumer Key/Secret and Access Token/Secret are from the **same** app.
- [ ] The Access Token was generated under “Keys and tokens” → “Access Token” → Generate (for the correct @username).
- [ ] No credentials are committed to git (`.env` and `.env.*` are in `.gitignore`).

## If you think tokens were mixed up

1. **screapa** app → use for **@destroyerfaucet**. Put all four (Consumer Key/Secret + Access Token/Secret from that app) into **`.env`**.
2. **screapa2** app → use for **@hareofsorrow**. Put all four from that app into **`.env.hareofsorrow`**.
3. In the [developer portal](https://developer.x.com/en/portal/projects-and-apps): open **screapa** → Keys and tokens → copy Consumer Key + Secret and generate Access Token for @destroyerfaucet → fill `.env`. Open **screapa2** → same steps for @hareofsorrow → fill `.env.hareofsorrow`.
4. Run: `python run.py ...` (uses `.env` = destroyerfaucet) or `TWITTER_ENV=hareofsorrow python run.py ...` (uses `.env.hareofsorrow` = hareofsorrow).
