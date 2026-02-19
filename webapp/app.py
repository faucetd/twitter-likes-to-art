"""
Wall Peepo — swipe on art to decide what goes on your wall.

Run:
    python -m webapp.app
"""

import json
import random
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Cookie, Request, Response, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import get_db, init_db, load_metadata_into_db


# ---------------------------------------------------------------------------
# Rate limiter — simple sliding window per IP
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        # Prune old entries
        self._hits[key] = hits = [t for t in hits if now - t < self.window]
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


# 120 votes/min per IP — generous for normal use, blocks spam
vote_limiter = RateLimiter(max_requests=120, window_seconds=60)

ART_DIR = Path(__file__).resolve().parent.parent / "art"
METADATA_PATH = ART_DIR / "metadata.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with open(METADATA_PATH) as f:
        metadata = json.load(f)
    inserted = load_metadata_into_db(metadata)
    if inserted:
        print(f"Loaded {inserted} new images into DB")
    yield


app = FastAPI(title="Wall Peepo", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Static files & pages
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    return FileResponse(STATIC_DIR / "dashboard.html")


# ---------------------------------------------------------------------------
# Image serving
# ---------------------------------------------------------------------------

@app.get("/img/{filename}")
def serve_image(filename: str):
    path = ART_DIR / filename
    if not path.exists():
        return Response(status_code=404)
    media = "image/jpeg" if filename.endswith(".jpg") else "image/png"
    return FileResponse(path, media_type=media)


# ---------------------------------------------------------------------------
# API: get next image
# ---------------------------------------------------------------------------

ELO_K = 32  # Elo K-factor

def _ensure_session(session_id: str | None, response: Response) -> str:
    if not session_id:
        session_id = uuid.uuid4().hex
        response.set_cookie("session_id", session_id, max_age=60 * 60 * 24 * 365)
    return session_id


@app.get("/api/next")
def next_image(response: Response, session_id: str | None = Cookie(default=None)):
    session_id = _ensure_session(session_id, response)
    conn = get_db()

    # Weighted random: use score to bias selection toward better images.
    # Fetch all image ids + scores, pick weighted-random, excluding recently
    # seen by this session (last 50).
    seen_rows = conn.execute(
        "SELECT DISTINCT image_id FROM votes WHERE session_id = ? ORDER BY id DESC LIMIT 200",
        (session_id,),
    ).fetchall()
    seen_ids = {r["image_id"] for r in seen_rows}

    rows = conn.execute("SELECT id, filename, username, tweet_id, title, score, votes_up, votes_down, votes_super FROM images").fetchall()
    conn.close()

    candidates = [r for r in rows if r["id"] not in seen_ids]
    if not candidates:
        # They've seen everything — reset and show all
        candidates = list(rows)
    if not candidates:
        return {"done": True}

    min_score = min(r["score"] for r in candidates)
    weights = [r["score"] - min_score + 100 for r in candidates]
    chosen = random.choices(candidates, weights=weights, k=1)[0]

    return {
        "id": chosen["id"],
        "filename": chosen["filename"],
        "username": chosen["username"],
        "tweet_id": chosen["tweet_id"],
        "title": chosen["title"],
        "score": round(chosen["score"]),
        "votes_up": chosen["votes_up"],
        "votes_down": chosen["votes_down"],
        "remaining": len(candidates),
    }


# ---------------------------------------------------------------------------
# API: vote
# ---------------------------------------------------------------------------

class VoteRequest(BaseModel):
    image_id: int
    direction: str  # "left" (no), "right" (yes), or "super" (superlike)


@app.post("/api/vote")
def cast_vote(vote: VoteRequest, request: Request, response: Response, session_id: str | None = Cookie(default=None)):
    session_id = _ensure_session(session_id, response)

    if vote.direction not in ("left", "right", "super"):
        return Response(status_code=400)

    client_ip = request.client.host if request.client else "unknown"
    if not vote_limiter.is_allowed(client_ip):
        return Response(status_code=429)

    conn = get_db()

    conn.execute(
        "INSERT INTO votes (image_id, direction, session_id) VALUES (?, ?, ?)",
        (vote.image_id, vote.direction, session_id),
    )

    img = conn.execute("SELECT score, votes_up, votes_down FROM images WHERE id = ?", (vote.image_id,)).fetchone()
    if img:
        expected = 1 / (1 + 10 ** ((1500 - img["score"]) / 400))
        if vote.direction == "super":
            actual = 1.0
            k = ELO_K * 2
        elif vote.direction == "right":
            actual = 1.0
            k = ELO_K
        else:
            actual = 0.0
            k = ELO_K
        new_score = img["score"] + k * (actual - expected)

        if vote.direction == "super":
            conn.execute(
                "UPDATE images SET score = ?, votes_up = votes_up + 1, votes_super = votes_super + 1 WHERE id = ?",
                (new_score, vote.image_id),
            )
        elif vote.direction == "right":
            conn.execute(
                "UPDATE images SET score = ?, votes_up = votes_up + 1 WHERE id = ?",
                (new_score, vote.image_id),
            )
        else:
            conn.execute(
                "UPDATE images SET score = ?, votes_down = votes_down + 1 WHERE id = ?",
                (new_score, vote.image_id),
            )
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: leaderboard
# ---------------------------------------------------------------------------

@app.get("/api/leaderboard")
def leaderboard(limit: int = Query(default=50, le=200)):
    conn = get_db()
    rows = conn.execute(
        """SELECT id, filename, username, tweet_id, title, score, votes_up, votes_down, votes_super
           FROM images
           WHERE votes_up + votes_down > 0
           ORDER BY score DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/stats")
def stats():
    conn = get_db()
    total_images = conn.execute("SELECT COUNT(*) as c FROM images").fetchone()["c"]
    total_votes = conn.execute("SELECT COUNT(*) as c FROM votes").fetchone()["c"]
    total_sessions = conn.execute("SELECT COUNT(DISTINCT session_id) as c FROM votes").fetchone()["c"]
    voted_images = conn.execute("SELECT COUNT(*) as c FROM images WHERE votes_up + votes_down > 0").fetchone()["c"]
    conn.close()
    return {
        "total_images": total_images,
        "total_votes": total_votes,
        "total_sessions": total_sessions,
        "voted_images": voted_images,
    }


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webapp.app:app", host="0.0.0.0", port=8000, reload=True)
