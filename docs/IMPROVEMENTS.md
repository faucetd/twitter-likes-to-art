# Ideas for improving this repo (including for open source)

## Credentials and security

- **Never log or print** API keys, secrets, or tokens; avoid leaving them in error messages.
- **Optional:** Support loading secrets from the system keychain or a single env file with multiple named profiles instead of multiple `.env.*` files.
- **Docs:** Keep [CREDENTIALS.md](CREDENTIALS.md) in sync with any new env vars or auth methods.

## Reliability and robustness

- **URL allowlist:** In `download_media.py`, only allow image URLs from known X CDN hosts (e.g. `pbs.twimg.com`, `twimg.com`) and reject `file://` and private/local IPs to reduce SSRF risk.
- **Path containment:** When reading `path` from manifests, resolve and ensure files are under the expected download/output directory so paths can’t escape (e.g. `../../etc/passwd`).
- **Retries and backoff:** For API and download calls, add retries with exponential backoff (and respect `Retry-After` on 429).
- **Rate limits:** Document X API limits (e.g. 75 req/15min for liked_tweets, 900 for tweet lookup) and optionally throttle or warn when approaching them.

## Testing and CI

- **Unit tests:** Parser tests with fixed `like.js` fixtures (full-tweet and ID-only formats); tests for filename sanitization and manifest shape.
- **Integration tests:** Optional “dry run” or mock API that returns minimal JSON so the pipeline can run without real credentials.
- **CI:** GitHub Actions (or similar) to run tests and lint on push/PR; no secrets in CI for public repos.

## Code quality and structure

- **Type hints:** Keep/expand type hints and run a strict mypy or pyright check.
- **Lint/format:** Use ruff (or black + isort) and a single `make lint` / `make format` (or `tox`).
- **Config:** Optional YAML/TOML config for default paths, account labels, and art-filter threshold instead of only CLI flags.
- **Logging:** Replace ad-hoc `print(..., file=sys.stderr)` with the `logging` module and configurable level.

## Features

- **Progress:** Progress bar (e.g. tqdm) for download and resolve steps when running on large archives.
- **Resume:** Persist “last resolved” state so gallery-dl scraping can resume after interruptions.
- **Two accounts in one run:** Support multiple credential sets in one invocation and merge results, instead of requiring separate runs per account.
- **Videos/GIFs:** Option to keep video or GIF media (e.g. first frame or small clip) for backgrounds, not only photos.

## Documentation and open source

- **README:** Clear “What this does”, “Quick start”, “Requirements”, “Configuration”, “Multiple accounts”, “Troubleshooting”; link to CREDENTIALS.md and IMPROVEMENTS.md.
- **Contributing:** CONTRIBUTING.md with how to run tests, submit PRs, and code style.
- **License:** Add LICENSE (e.g. MIT) and reference it in README.
- **Changelog:** CHANGELOG.md or GitHub Releases for notable changes and versioning.
- **Issue templates:** GitHub issue templates for “bug”, “feature”, “question” so contributors know what to include.

## Optional dependencies

- **CLIP/art filter:** Document optional deps in README and `requirements-optional.txt` or `extras` in `pyproject.toml` so the core pipeline stays minimal and the art filter is clearly optional.
