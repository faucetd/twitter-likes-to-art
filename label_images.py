#!/usr/bin/env python3
"""
Local web server for labeling images as keep/skip.
Serves a browser-based grid UI — click thumbnails to cycle through
unlabeled → keep → skip → unlabeled. Saves labels.json on disk.

Usage:
    python label_images.py downloads/
    # Opens browser at http://localhost:8421
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import webbrowser
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
DEFAULT_PORT = 8421


def discover_images(directory: Path) -> list[str]:
    """Return sorted list of image filenames in directory."""
    names = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            names.append(p.name)
    return names


def load_labels(path: Path) -> dict[str, bool]:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label Images</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#111;color:#eee}
header{position:sticky;top:0;z-index:10;background:#1a1a1a;padding:12px 20px;
  border-bottom:1px solid #333;display:flex;flex-wrap:wrap;align-items:center;gap:12px}
header h1{font-size:1.1rem;font-weight:600;white-space:nowrap}
.stats{font-size:.85rem;color:#aaa;white-space:nowrap}
.stats b{color:#eee}
.bar-wrap{flex:1;min-width:120px;max-width:320px;height:18px;background:#333;border-radius:9px;overflow:hidden}
.bar-fill{height:100%;border-radius:9px;transition:width .2s}
.controls{display:flex;gap:8px;margin-left:auto}
button{padding:6px 16px;border:none;border-radius:6px;font-size:.85rem;cursor:pointer;font-weight:600;transition:background .15s}
#save-btn{background:#2563eb;color:#fff}
#save-btn:hover{background:#1d4ed8}
#save-btn.saved{background:#16a34a}
#select-all-keep{background:#22c55e;color:#fff}
#select-all-keep:hover{background:#16a34a}
#select-all-skip{background:#ef4444;color:#fff}
#select-all-skip:hover{background:#dc2626}
#clear-all{background:#555;color:#fff}
#clear-all:hover{background:#666}
.filter-group{display:flex;gap:4px}
.filter-group button{padding:4px 10px;background:#333;color:#aaa;font-size:.75rem;border-radius:4px}
.filter-group button.active{color:#fff;background:#555}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;padding:16px}
.card{position:relative;border-radius:8px;overflow:hidden;cursor:pointer;
  border:3px solid transparent;transition:border-color .15s,opacity .15s;aspect-ratio:1;background:#222}
.card img{width:100%;height:100%;object-fit:cover;display:block;transition:opacity .15s}
.card.keep{border-color:#22c55e}
.card.skip{border-color:#ef4444}
.card .badge{position:absolute;top:6px;right:6px;padding:2px 8px;border-radius:4px;
  font-size:.7rem;font-weight:700;text-transform:uppercase;opacity:0;transition:opacity .15s}
.card.keep .badge{background:#22c55e;color:#fff;opacity:1}
.card.skip .badge{background:#ef4444;color:#fff;opacity:1}
.card.hidden{display:none}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
  background:#16a34a;color:#fff;padding:10px 24px;border-radius:8px;font-size:.9rem;
  font-weight:600;opacity:0;transition:opacity .3s;pointer-events:none;z-index:100}
.toast.show{opacity:1}
</style>
</head>
<body>
<header>
  <h1>Label Images</h1>
  <div class="stats">
    <span id="labeled-count">0</span> / <span id="total-count">0</span> labeled
    &nbsp;(<b id="keep-count">0</b> keep, <b id="skip-count">0</b> skip)
  </div>
  <div class="bar-wrap"><div class="bar-fill" id="bar-fill"></div></div>
  <div class="filter-group">
    <button class="active" data-filter="all">All</button>
    <button data-filter="unlabeled">Unlabeled</button>
    <button data-filter="keep">Keep</button>
    <button data-filter="skip">Skip</button>
  </div>
  <div class="controls">
    <button id="select-all-keep">All keep</button>
    <button id="select-all-skip">All skip</button>
    <button id="clear-all">Clear</button>
    <button id="save-btn">Save</button>
  </div>
</header>
<div class="grid" id="grid"></div>
<div class="toast" id="toast"></div>
<script>
const CYCLE = [null, true, false]; // unlabeled → keep → skip

let images = [];
let labels = {};  // filename → true/false
let filter = "all";

async function init() {
  const [imgRes, lblRes] = await Promise.all([
    fetch("/api/images").then(r => r.json()),
    fetch("/api/labels").then(r => r.json()),
  ]);
  images = imgRes;
  labels = lblRes;
  document.getElementById("total-count").textContent = images.length;
  renderGrid();
  updateStats();
}

function renderGrid() {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  for (const name of images) {
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.name = name;
    applyLabel(card, name);

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = "/images/" + encodeURIComponent(name);
    img.alt = name;
    card.appendChild(img);

    const badge = document.createElement("div");
    badge.className = "badge";
    card.appendChild(badge);

    card.addEventListener("click", () => onToggle(card, name));
    grid.appendChild(card);
  }
  applyFilter();
}

function applyLabel(card, name) {
  const v = labels[name];
  card.classList.toggle("keep", v === true);
  card.classList.toggle("skip", v === false);
  const badge = card.querySelector(".badge");
  if (badge) badge.textContent = v === true ? "keep" : v === false ? "skip" : "";
}

function onToggle(card, name) {
  const cur = labels[name];
  const idx = CYCLE.indexOf(cur === undefined ? null : cur);
  const next = CYCLE[(idx + 1) % CYCLE.length];
  if (next === null) {
    delete labels[name];
  } else {
    labels[name] = next;
  }
  applyLabel(card, name);
  applyFilter();
  updateStats();
}

function updateStats() {
  let keep = 0, skip = 0;
  for (const v of Object.values(labels)) {
    if (v === true) keep++;
    else if (v === false) skip++;
  }
  const labeled = keep + skip;
  document.getElementById("labeled-count").textContent = labeled;
  document.getElementById("keep-count").textContent = keep;
  document.getElementById("skip-count").textContent = skip;
  const pct = images.length ? (labeled / images.length * 100) : 0;
  const fill = document.getElementById("bar-fill");
  fill.style.width = pct + "%";
  const keepPct = images.length ? (keep / images.length * 100) : 0;
  const skipPct = images.length ? (skip / images.length * 100) : 0;
  fill.style.background = `linear-gradient(90deg, #22c55e ${keepPct / (keepPct + skipPct + 0.001) * 100}%, #ef4444 0%)`;
}

function applyFilter() {
  for (const card of document.querySelectorAll(".card")) {
    const name = card.dataset.name;
    const v = labels[name];
    let show = true;
    if (filter === "unlabeled") show = (v === undefined);
    else if (filter === "keep") show = (v === true);
    else if (filter === "skip") show = (v === false);
    card.classList.toggle("hidden", !show);
  }
}

document.querySelectorAll(".filter-group button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelector(".filter-group .active").classList.remove("active");
    btn.classList.add("active");
    filter = btn.dataset.filter;
    applyFilter();
  });
});

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2000);
}

document.getElementById("save-btn").addEventListener("click", async () => {
  const btn = document.getElementById("save-btn");
  const res = await fetch("/api/labels", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(labels),
  });
  if (res.ok) {
    btn.classList.add("saved");
    btn.textContent = "Saved!";
    const data = await res.json();
    showToast("Saved " + data.count + " labels");
    setTimeout(() => { btn.classList.remove("saved"); btn.textContent = "Save"; }, 1500);
  }
});

document.getElementById("select-all-keep").addEventListener("click", () => {
  const visible = document.querySelectorAll(".card:not(.hidden)");
  visible.forEach(card => {
    const name = card.dataset.name;
    labels[name] = true;
    applyLabel(card, name);
  });
  updateStats();
});

document.getElementById("select-all-skip").addEventListener("click", () => {
  const visible = document.querySelectorAll(".card:not(.hidden)");
  visible.forEach(card => {
    const name = card.dataset.name;
    labels[name] = false;
    applyLabel(card, name);
  });
  updateStats();
});

document.getElementById("clear-all").addEventListener("click", () => {
  const visible = document.querySelectorAll(".card:not(.hidden)");
  visible.forEach(card => {
    const name = card.dataset.name;
    delete labels[name];
    applyLabel(card, name);
  });
  updateStats();
});

init();
</script>
</body>
</html>"""


class LabelHandler(BaseHTTPRequestHandler):
    image_dir: Path
    labels_path: Path
    image_names: list[str]

    def log_message(self, fmt: str, *args: object) -> None:
        # Quiet request logging; only log errors
        pass

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = unquote(self.path)

        if path == "/":
            self._send_html(HTML_PAGE)
            return

        if path == "/api/images":
            self._send_json(self.image_names)
            return

        if path == "/api/labels":
            self._send_json(load_labels(self.labels_path))
            return

        if path.startswith("/images/"):
            filename = path[len("/images/"):]
            file_path = self.image_dir / filename
            resolved = file_path.resolve()
            if not resolved.is_relative_to(self.image_dir.resolve()):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime, _ = mimetypes.guess_type(file_path.name)
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = unquote(self.path)

        if path == "/api/labels":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
                return
            if not isinstance(data, dict):
                self.send_error(HTTPStatus.BAD_REQUEST, "Expected JSON object")
                return
            # Only keep labels for images that actually exist
            clean: dict[str, bool] = {}
            valid = set(self.image_names)
            for k, v in data.items():
                if k in valid and isinstance(v, bool):
                    clean[k] = v
            self.labels_path.write_text(
                json.dumps(clean, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._send_json({"ok": True, "count": len(clean)})
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def run_server(image_dir: Path, labels_path: Path, port: int = DEFAULT_PORT) -> None:
    image_dir = image_dir.resolve()
    labels_path = labels_path.resolve()
    image_names = discover_images(image_dir)

    if not image_names:
        print(f"No images found in {image_dir}", file=sys.stderr)
        sys.exit(1)

    LabelHandler.image_dir = image_dir
    LabelHandler.labels_path = labels_path
    LabelHandler.image_names = image_names

    server = HTTPServer(("127.0.0.1", port), LabelHandler)
    url = f"http://localhost:{port}"
    print(f"Serving {len(image_names)} images from {image_dir}", file=sys.stderr)
    print(f"Labels will be saved to {labels_path}", file=sys.stderr)
    print(f"Open {url} in your browser (Ctrl+C to stop)", file=sys.stderr)

    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Label images via a browser grid UI. Click to cycle: unlabeled → keep → skip.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing images to label (e.g. downloads/)",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="Path to labels JSON file (default: <directory>/labels.json)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory", file=sys.stderr)
        sys.exit(1)

    labels_path = args.labels or (args.directory / "labels.json")
    run_server(args.directory, labels_path, port=args.port)


if __name__ == "__main__":
    main()
