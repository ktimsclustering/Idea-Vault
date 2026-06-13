"""
IdeaVault - a local, private idea catalog powered by your own LLM (Ollama).

Dump any thought into the web UI. A local model gives it a title, picks a
category, adds tags, and writes a one-line summary. Everything is saved as
plain Markdown files on your computer - no cloud, no account.

Run:  python app.py   (then open http://localhost:5000)
"""

import os
import re
import json
import uuid
import socket
import datetime
import threading
import urllib.request
import urllib.error

from flask import Flask, request, jsonify, Response, send_file

# ----------------------------------------------------------------------------
# Configuration (override with environment variables if you like)
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_DIR = os.environ.get("IDEAVAULT_DIR", os.path.join(BASE_DIR, "vault"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e2b")

# Optional custom background: drop an image named background.jpg/.png/.webp
# next to this file and it will be used as the page background automatically.
BG_NAMES = ("background.jpg", "background.jpeg", "background.png", "background.webp")

app = Flask(__name__)

os.makedirs(VAULT_DIR, exist_ok=True)

# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def slugify(text, maxlen=50):
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:maxlen].strip("-") or "idea"


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def category_dir(category):
    d = os.path.join(VAULT_DIR, slugify(category))
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# Markdown read/write (YAML-ish frontmatter, no external deps)
# ----------------------------------------------------------------------------
def write_idea(idea):
    """Persist an idea dict to a Markdown file. Returns the file path."""
    d = category_dir(idea["category"])
    path = os.path.join(d, idea["id"] + ".md")
    tags = ", ".join(idea.get("tags", []))
    front = (
        "---\n"
        f"id: {idea['id']}\n"
        f"title: {idea['title']}\n"
        f"category: {idea['category']}\n"
        f"tags: [{tags}]\n"
        f"created: {idea['created']}\n"
        f"updated: {idea.get('updated', idea['created'])}\n"
        f"summary: {idea.get('summary', '')}\n"
        "---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(front + idea["body"].strip() + "\n")
    return path


def parse_idea(path):
    """Read a Markdown file back into an idea dict."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    meta, body = {}, raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            block, body = parts[1], parts[2]
            for line in block.strip().splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    tags_raw = meta.get("tags", "").strip().strip("[]")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return {
        "id": meta.get("id", os.path.splitext(os.path.basename(path))[0]),
        "title": meta.get("title", "Untitled"),
        "category": meta.get("category", "Uncategorized"),
        "tags": tags,
        "created": meta.get("created", ""),
        "updated": meta.get("updated", meta.get("created", "")),
        "summary": meta.get("summary", ""),
        "body": body.strip(),
        "_path": path,
    }


def load_all_ideas():
    ideas = []
    for root, _dirs, files in os.walk(VAULT_DIR):
        for fn in files:
            if fn.endswith(".md"):
                try:
                    ideas.append(parse_idea(os.path.join(root, fn)))
                except Exception:
                    pass
    ideas.sort(key=lambda x: x.get("created", ""), reverse=True)
    return ideas


def find_path(idea_id):
    for root, _dirs, files in os.walk(VAULT_DIR):
        for fn in files:
            if fn == idea_id + ".md":
                return os.path.join(root, fn)
    return None


# ----------------------------------------------------------------------------
# LLM: ask the local model to organize a raw idea
# ----------------------------------------------------------------------------
def llm_split(text, existing_categories):
    """Split a raw dump into one or more organized ideas.

    Returns (ideas, llm_used) where ideas is a list of dicts with keys
    title, category, tags, summary, body. A single dump may contain several
    distinct ideas; each becomes its own entry with its own category.
    """
    cats_hint = ", ".join(existing_categories) if existing_categories else "none yet"
    instructions = (
        "You organize a person's raw notes into a knowledge base. "
        "The input may contain ONE OR MORE separate ideas - often one per line, "
        "but a single idea can also span several lines. Identify each DISTINCT idea "
        "and classify them independently (different ideas usually get different "
        "categories). Respond with STRICT JSON only, no prose: an object with a key "
        '"ideas" whose value is an array. Each array item is an object with keys: '
        '"title" (max 8 words), "category" (one or two words; reuse an existing '
        'category when it fits), "tags" (array of 2-5 lowercase keywords), '
        '"summary" (one sentence), "body" (the original text of that idea, verbatim). '
        f"Existing categories: {cats_hint}."
    )
    # Note: some models (e.g. Gemma) reject a separate "system" role and
    # return HTTP 400. Folding the instructions into the user turn works
    # across all Ollama chat models.
    prompt = instructions + "\n\n--- NOTES TO ORGANIZE ---\n" + text
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
        "keep_alive": "30m",  # keep the model in memory between requests
    }
    try:
        req = urllib.request.Request(
            OLLAMA_URL.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("message", {}).get("content", "{}")
        parsed = extract_json(content)
        raw = parsed.get("ideas") if isinstance(parsed, dict) else parsed
        if isinstance(parsed, dict) and not isinstance(raw, list):
            # model returned a single idea object instead of a list
            raw = [parsed]
        ideas = []
        for it in (raw or []):
            if not isinstance(it, dict):
                continue
            body = str(it.get("body") or "").strip()
            ideas.append({
                "title": str(it.get("title") or "").strip()[:120] or fallback_title(body or text),
                "category": str(it.get("category") or "Uncategorized").strip()[:40] or "Uncategorized",
                "tags": [str(t).strip().lower() for t in it.get("tags", []) if str(t).strip()][:5],
                "summary": str(it.get("summary") or "").strip()[:280],
                "body": body or text.strip(),
            })
        if ideas:
            return ideas, True
        raise ValueError("model returned no parseable ideas")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        app.logger.warning("Ollama returned HTTP %s for model '%s': %s",
                           e.code, OLLAMA_MODEL, body or e.reason)
        return _fallback_split(text), False
    except Exception as e:
        app.logger.warning("Ollama unavailable/unparseable, using fallback: %s", e)
        return _fallback_split(text), False


def _fallback_split(text):
    """Offline fallback: split a multi-line dump into one Inbox note per idea."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) > 1:
        chunks = paras
    else:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        chunks = lines if len(lines) > 1 else ([text.strip()] if text.strip() else [])
    return [
        {"title": fallback_title(c), "category": "Inbox", "tags": [], "summary": "", "body": c}
        for c in chunks
    ]


def extract_json(content):
    """Be forgiving: some models wrap JSON in prose or code fences."""
    try:
        return json.loads(content)
    except Exception:
        pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def fallback_title(text):
    first = text.strip().splitlines()[0] if text.strip() else "Untitled"
    words = first.split()
    return (" ".join(words[:8]) + ("…" if len(words) > 8 else "")) or "Untitled"


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
@app.get("/api/ideas")
def api_list():
    ideas = load_all_ideas()
    for i in ideas:
        i.pop("_path", None)
    cats = {}
    for i in ideas:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    return jsonify({"ideas": ideas, "categories": cats, "model": OLLAMA_MODEL})


@app.post("/api/ideas")
def api_create():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    existing = sorted({i["category"] for i in load_all_ideas()})
    ideas, llm_used = llm_split(text, existing)
    created = []
    for org in ideas:
        idea = {
            "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "title": org["title"],
            "category": org["category"],
            "tags": org["tags"],
            "summary": org["summary"],
            "body": org.get("body") or text,
            "created": now_iso(),
            "updated": now_iso(),
        }
        write_idea(idea)
        created.append(idea)
    return jsonify({"created": created, "count": len(created), "llm": llm_used}), 201


@app.put("/api/ideas/<idea_id>")
def api_update(idea_id):
    path = find_path(idea_id)
    if not path:
        return jsonify({"error": "not found"}), 404
    idea = parse_idea(path)
    data = request.get_json(force=True)
    new_category = data.get("category", idea["category"]).strip() or idea["category"]
    for field in ("title", "body", "summary"):
        if field in data:
            idea[field] = data[field]
    if "tags" in data:
        idea["tags"] = [t.strip().lower() for t in data["tags"] if t.strip()]
    idea["updated"] = now_iso()
    # If category changed, remove the old file before writing the new one.
    if new_category != idea["category"]:
        try:
            os.remove(path)
        except OSError:
            pass
        idea["category"] = new_category
    write_idea(idea)
    idea.pop("_path", None)
    return jsonify(idea)


@app.delete("/api/ideas/<idea_id>")
def api_delete(idea_id):
    path = find_path(idea_id)
    if not path:
        return jsonify({"error": "not found"}), 404
    os.remove(path)
    return jsonify({"ok": True})


def _bg_path():
    for name in BG_NAMES:
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            return p
    return None


@app.get("/background-image")
def background_image():
    p = _bg_path()
    if not p:
        return ("", 404)
    return send_file(p)


@app.get("/")
def index():
    body_class = "has-img" if _bg_path() else ""
    html = INDEX_HTML.replace("__BG_CLASS__", body_class)
    return Response(html, mimetype="text/html")


# ----------------------------------------------------------------------------
# Frontend (single page, no build step)
# ----------------------------------------------------------------------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>IdeaVault</title>
<style>
  :root{
    --ink:#f4f0ff; --muted:#b9aee0; --accent:#c08bff; --accent-2:#8b5cf0;
    /* dark tinted glass so panels stay readable over a colourful background */
    --panel:rgba(18,10,34,.55); --panel-2:rgba(28,16,50,.62);
    --line:rgba(190,160,255,.22); --chip:rgba(190,160,255,.14);
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       color:var(--ink);position:relative;overflow-x:hidden;
       background:radial-gradient(1200px 900px at 50% 38%, #3a1457 0%, #220a3a 42%, #0c0518 100%);}
  /* recreated cosmic scene (used when no custom background image is present) */
  .cosmos{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}
  /* custom background image layer (shown only when one is provided) */
  .bg-photo{position:fixed;inset:0;z-index:0;pointer-events:none;display:none;
       background:#0c0518 center/cover no-repeat;}
  body.has-img .cosmos{display:none}
  body.has-img .bg-photo{display:block;background-image:url('/background-image')}
  /* dark scrim guarantees text never blends into the artwork */
  .scrim{position:fixed;inset:0;z-index:0;pointer-events:none;
       background:linear-gradient(90deg, rgba(8,4,18,.55) 0%, rgba(8,4,18,.40) 38%, rgba(8,4,18,.70) 100%);}
  .watermark{position:fixed;top:26px;right:40px;z-index:1;text-align:right;pointer-events:none;
       font-size:13px;letter-spacing:.42em;color:rgba(228,214,255,.55);font-weight:300;
       text-shadow:0 2px 8px rgba(0,0,0,.6)}
  .watermark span{display:block;font-size:11px;letter-spacing:.42em;color:rgba(228,214,255,.32)}
  .app{position:relative;z-index:1;display:flex;min-height:100vh}

  .sidebar{width:248px;padding:24px 16px;position:sticky;top:0;height:100vh;overflow:auto;
           background:linear-gradient(180deg, rgba(10,5,22,.62), rgba(10,5,22,.30));
           border-right:1px solid var(--line);backdrop-filter:blur(10px)}
  .brand{font-weight:700;font-size:19px;margin:0 8px 4px;display:flex;align-items:center;gap:8px;letter-spacing:.2px;text-shadow:0 2px 8px rgba(0,0,0,.6)}
  .brand small{display:block;font-weight:500;font-size:10px;color:var(--muted);margin-top:3px;
       text-transform:uppercase;letter-spacing:.18em}
  .status{font-size:11px;color:var(--muted);margin:8px 8px 18px}
  .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#566184;margin-right:6px}
  .dot.on{background:#5fd6b0;box-shadow:0 0 8px rgba(95,214,176,.7)}
  .nav button{width:100%;text-align:left;background:none;border:none;padding:9px 10px;
              border-radius:9px;color:var(--ink);font-size:14px;cursor:pointer;display:flex;
              justify-content:space-between;align-items:center;transition:background .15s}
  .nav button:hover{background:var(--chip)}
  .nav button.active{background:linear-gradient(90deg, rgba(192,139,255,.26), rgba(192,139,255,.06));
              font-weight:600;box-shadow:inset 2px 0 0 var(--accent)}
  .nav .count{color:var(--muted);font-size:12px}
  .nav .label{margin:18px 10px 8px;font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted)}

  .main{flex:1;padding:34px 44px;max-width:1020px}
  .composer{background:var(--panel);border:1px solid var(--line);border-radius:16px;
            padding:18px;backdrop-filter:blur(16px);
            box-shadow:0 8px 30px rgba(5,10,22,.35)}
  .composer textarea{width:100%;border:none;outline:none;resize:vertical;min-height:72px;
            font-size:15px;line-height:1.5;font-family:inherit;color:var(--ink);background:transparent}
  .composer textarea::placeholder{color:#a99cce}
  .composer .row{display:flex;justify-content:space-between;align-items:center;margin-top:10px}
  .hint{font-size:12px;color:var(--muted)}
  .btn{background:linear-gradient(135deg, var(--accent), var(--accent-2));color:#0e1426;font-weight:600;
       border:none;padding:10px 20px;border-radius:10px;font-size:14px;cursor:pointer;
       box-shadow:0 4px 16px rgba(111,135,214,.35);transition:transform .12s,box-shadow .12s}
  .btn:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(111,135,214,.5)}
  .btn:disabled{opacity:.5;cursor:default;transform:none}
  .search{margin:26px 0 16px}
  .search input{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:11px;
       font-size:14px;color:var(--ink);background:var(--panel);backdrop-filter:blur(10px);outline:none}
  .search input::placeholder{color:#a99cce}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;
        cursor:pointer;backdrop-filter:blur(16px) saturate(1.1);transition:box-shadow .18s,transform .18s,border-color .18s}
  .card:hover{box-shadow:0 12px 34px rgba(0,0,0,.5);transform:translateY(-3px);border-color:rgba(192,139,255,.6)}
  .card h3{margin:0 0 6px;font-size:15.5px;line-height:1.32;color:#fbf8ff;text-shadow:0 1px 3px rgba(0,0,0,.55)}
  .card .cat{font-size:10.5px;color:#d6b3ff;font-weight:700;text-transform:uppercase;letter-spacing:.1em}
  .card .sum{font-size:13px;color:#ddd4f5;margin:8px 0 12px;line-height:1.45}
  .tags{display:flex;flex-wrap:wrap;gap:6px}
  .tag{background:var(--chip);color:#e3d8ff;font-size:11px;padding:3px 9px;border-radius:20px;border:1px solid rgba(190,160,255,.18)}
  .meta{font-size:11px;color:var(--muted);margin-top:12px}
  .empty{color:var(--muted);text-align:center;padding:70px 0}
  /* modal */
  .overlay{position:fixed;inset:0;background:rgba(6,10,20,.55);display:none;align-items:center;
           justify-content:center;padding:20px;z-index:20;backdrop-filter:blur(4px)}
  .overlay.show{display:flex}
  .modal{background:linear-gradient(180deg, rgba(28,37,60,.96), rgba(18,25,42,.96));
         border:1px solid var(--line);border-radius:18px;max-width:640px;width:100%;max-height:86vh;
         overflow:auto;padding:26px;box-shadow:0 24px 70px rgba(0,0,0,.55)}
  .modal input,.modal textarea{width:100%;border:1px solid var(--line);border-radius:10px;
         padding:10px 12px;font-size:14px;font-family:inherit;margin-top:5px;color:var(--ink);
         background:rgba(255,255,255,.05);outline:none}
  .modal input:focus,.modal textarea:focus{border-color:var(--accent)}
  .modal textarea{min-height:160px;resize:vertical;line-height:1.5}
  .modal label{font-size:11px;color:var(--muted);display:block;margin-top:16px;font-weight:600;
         text-transform:uppercase;letter-spacing:.08em}
  .modal .actions{display:flex;justify-content:space-between;margin-top:24px;align-items:center}
  .link{background:none;border:none;color:#ff8a8a;cursor:pointer;font-size:13px}
  .ghost{background:rgba(255,255,255,.10);color:var(--ink);box-shadow:none}
  .ghost:hover{box-shadow:none;background:rgba(255,255,255,.16)}
  @media(max-width:720px){.sidebar{display:none}.main{padding:20px}.watermark{display:none}}
</style>
</head>
<body class="__BG_CLASS__">
<svg class="cosmos" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <radialGradient id="neb" cx="50%" cy="42%" r="62%">
      <stop offset="0" stop-color="#5a1f7e"/><stop offset="42%" stop-color="#2c0e4c"/>
      <stop offset="100%" stop-color="#0a0416"/>
    </radialGradient>
    <radialGradient id="halo" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#ff8a3c" stop-opacity=".55"/>
      <stop offset="55%" stop-color="#c0398a" stop-opacity=".22"/>
      <stop offset="100%" stop-color="#c0398a" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="disk" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#fff1c2"/><stop offset="28%" stop-color="#ffb347"/>
      <stop offset="62%" stop-color="#ff5a2e"/><stop offset="100%" stop-color="#7a1d4a"/>
    </radialGradient>
    <filter id="soft" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="9"/>
    </filter>
    <filter id="bolt" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="6"/>
    </filter>
  </defs>
  <rect width="1600" height="900" fill="url(#neb)"/>
  <g fill="#ffffff">
    <circle cx="120" cy="90" r="1.6" opacity=".8"/><circle cx="280" cy="200" r="1.1" opacity=".5"/>
    <circle cx="430" cy="120" r="1.8" opacity=".7"/><circle cx="610" cy="70" r="1.2" opacity=".55"/>
    <circle cx="760" cy="160" r="1.4" opacity=".5"/><circle cx="980" cy="90" r="1.7" opacity=".75"/>
    <circle cx="1180" cy="150" r="1.2" opacity=".5"/><circle cx="1330" cy="80" r="1.9" opacity=".8"/>
    <circle cx="1470" cy="200" r="1.3" opacity=".55"/><circle cx="200" cy="380" r="1.2" opacity=".5"/>
    <circle cx="1500" cy="430" r="1.6" opacity=".7"/><circle cx="90" cy="560" r="1.4" opacity=".6"/>
    <circle cx="1540" cy="640" r="1.2" opacity=".5"/><circle cx="160" cy="760" r="1.7" opacity=".7"/>
    <circle cx="350" cy="830" r="1.2" opacity=".5"/><circle cx="560" cy="800" r="1.5" opacity=".6"/>
    <circle cx="820" cy="840" r="1.3" opacity=".55"/><circle cx="1080" cy="820" r="1.7" opacity=".7"/>
    <circle cx="1280" cy="780" r="1.2" opacity=".5"/><circle cx="1440" cy="840" r="1.5" opacity=".65"/>
    <circle cx="40" cy="300" r="1.1" opacity=".45"/><circle cx="1570" cy="300" r="1.1" opacity=".45"/>
  </g>
  <!-- glowing accretion disk seen nearly edge-on -->
  <ellipse cx="800" cy="470" rx="600" ry="190" fill="url(#halo)" filter="url(#soft)"/>
  <ellipse cx="800" cy="470" rx="540" ry="120" fill="url(#disk)" filter="url(#soft)"/>
  <ellipse cx="800" cy="470" rx="500" ry="96" fill="url(#disk)"/>
  <ellipse cx="800" cy="470" rx="360" ry="58" fill="#0a0414"/>
  <ellipse cx="800" cy="470" rx="360" ry="58" fill="none" stroke="#ffcaa0" stroke-opacity=".5" stroke-width="2"/>
  <!-- lightning bolt through the core -->
  <g filter="url(#bolt)" stroke="#dfe6ff" stroke-opacity=".9" fill="none" stroke-linejoin="round">
    <polyline points="790,40 820,250 770,430 815,470 775,520 820,700 795,860" stroke-width="10"/>
  </g>
  <polyline points="790,40 820,250 770,430 815,470 775,520 820,700 795,860" fill="none"
            stroke="#ffffff" stroke-width="3.2" stroke-linejoin="round"/>
</svg>
<div class="bg-photo"></div>
<div class="scrim"></div>
<div class="watermark">IDEA<span>VAULT</span></div>

<div class="app">
  <aside class="sidebar">
    <div class="brand">💡 IdeaVault
      <small>local & private</small>
    </div>
    <div class="status"><span id="dot" class="dot"></span><span id="statusText">checking model…</span></div>
    <div class="nav" id="nav"></div>
  </aside>

  <main class="main">
    <div class="composer">
      <textarea id="dump" placeholder="Dump an idea… (Ctrl/Cmd+Enter to save). The local model will title, categorize, tag and summarize it."></textarea>
      <div class="row">
        <span class="hint" id="composerHint">Stored as Markdown on your computer.</span>
        <button class="btn" id="saveBtn">Capture</button>
      </div>
    </div>

    <div class="search"><input id="search" placeholder="Search ideas, tags, categories…"/></div>
    <div id="list" class="grid"></div>
  </main>
</div>

<div class="overlay" id="overlay">
  <div class="modal">
    <label>Title</label><input id="mTitle"/>
    <label>Category</label><input id="mCategory"/>
    <label>Tags (comma separated)</label><input id="mTags"/>
    <label>Summary</label><input id="mSummary"/>
    <label>Note</label><textarea id="mBody"></textarea>
    <div class="actions">
      <button class="link" id="deleteBtn">Delete</button>
      <div>
        <button class="btn ghost" id="cancelBtn">Cancel</button>
        <button class="btn" id="updateBtn">Save</button>
      </div>
    </div>
  </div>
</div>

<script>
let STATE = {ideas:[], categories:{}, filter:"all", q:"", editing:null};

async function load(){
  const r = await fetch("/api/ideas");
  const d = await r.json();
  STATE.ideas = d.ideas; STATE.categories = d.categories;
  document.getElementById("statusText").textContent = "model: " + d.model;
  render();
}

function render(){
  // sidebar
  const nav = document.getElementById("nav");
  const total = STATE.ideas.length;
  let html = `<button class="${STATE.filter==='all'?'active':''}" data-cat="all">
      <span>All ideas</span><span class="count">${total}</span></button>`;
  html += `<div class="label">Categories</div>`;
  const cats = Object.keys(STATE.categories).sort();
  if(!cats.length) html += `<div class="hint" style="margin:0 8px">No ideas yet.</div>`;
  for(const c of cats){
    html += `<button class="${STATE.filter===c?'active':''}" data-cat="${esc(c)}">
        <span>${esc(c)}</span><span class="count">${STATE.categories[c]}</span></button>`;
  }
  nav.innerHTML = html;
  nav.querySelectorAll("button").forEach(b=>b.onclick=()=>{STATE.filter=b.dataset.cat;render();});

  // list
  const q = STATE.q.toLowerCase();
  let items = STATE.ideas.filter(i=>{
    if(STATE.filter!=="all" && i.category!==STATE.filter) return false;
    if(!q) return true;
    return (i.title+" "+i.body+" "+i.category+" "+(i.tags||[]).join(" ")+" "+i.summary)
            .toLowerCase().includes(q);
  });
  const list = document.getElementById("list");
  if(!items.length){
    list.innerHTML = `<div class="empty">Nothing here yet. Capture your first idea above.</div>`;
    return;
  }
  list.innerHTML = items.map(i=>`
    <div class="card" data-id="${i.id}">
      <div class="cat">${esc(i.category)}</div>
      <h3>${esc(i.title)}</h3>
      ${i.summary?`<div class="sum">${esc(i.summary)}</div>`:`<div class="sum">${esc(i.body.slice(0,120))}${i.body.length>120?'…':''}</div>`}
      <div class="tags">${(i.tags||[]).map(t=>`<span class="tag">#${esc(t)}</span>`).join("")}</div>
      <div class="meta">${fmtDate(i.created)}</div>
    </div>`).join("");
  list.querySelectorAll(".card").forEach(c=>c.onclick=()=>openEdit(c.dataset.id));
}

function openEdit(id){
  const i = STATE.ideas.find(x=>x.id===id); if(!i) return;
  STATE.editing = id;
  mTitle.value=i.title; mCategory.value=i.category;
  mTags.value=(i.tags||[]).join(", "); mSummary.value=i.summary||""; mBody.value=i.body;
  overlay.classList.add("show");
}
function closeEdit(){overlay.classList.remove("show");STATE.editing=null;}

async function save(){
  const text = dump.value.trim(); if(!text) return;
  saveBtn.disabled=true; saveBtn.textContent="Thinking…";
  try{
    const r = await fetch("/api/ideas",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({text})});
    const d = await r.json();
    setStatus(!!d.llm);
    const n = d.count || 0;
    const noun = n === 1 ? "idea" : "ideas";
    document.getElementById("composerHint").textContent =
      d.llm ? `Organized ${n} ${noun} with your local model.`
            : `Saved ${n} ${noun} to Inbox (model offline — start Ollama to auto-organize).`;
    dump.value="";
    await load();
  } finally { saveBtn.disabled=false; saveBtn.textContent="Capture"; }
}

function setStatus(ok){
  document.getElementById("dot").classList.toggle("on", ok);
}

async function update(){
  const id = STATE.editing; if(!id) return;
  const body = {title:mTitle.value, category:mCategory.value, summary:mSummary.value,
    body:mBody.value, tags:mTags.value.split(",").map(t=>t.trim()).filter(Boolean)};
  await fetch("/api/ideas/"+id,{method:"PUT",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)});
  closeEdit(); await load();
}
async function remove(){
  const id = STATE.editing; if(!id) return;
  if(!confirm("Delete this idea? The Markdown file will be removed.")) return;
  await fetch("/api/ideas/"+id,{method:"DELETE"});
  closeEdit(); await load();
}

function esc(s){return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function fmtDate(s){if(!s)return"";const d=new Date(s);return isNaN(d)?s:d.toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"});}

saveBtn.onclick=save;
updateBtn.onclick=update;
deleteBtn.onclick=remove;
cancelBtn.onclick=closeEdit;
overlay.onclick=e=>{if(e.target===overlay)closeEdit();};
dump.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key==="Enter")save();});
search.addEventListener("input",e=>{STATE.q=e.target.value;render();});
load();
</script>
</body>
</html>
"""

def warm_up():
    """Preload the model into memory so the first real request isn't slow.

    Runs in a background thread at startup; failures are harmless (the model
    may not be pulled yet, or Ollama may be off - the app still works).
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": "ok"}],
        "stream": False,
        "options": {"num_predict": 1},
        "keep_alive": "30m",  # keep the model resident between requests
    }
    try:
        req = urllib.request.Request(
            OLLAMA_URL.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
        app.logger.info("Warm-up complete: '%s' is loaded and ready.", OLLAMA_MODEL)
    except Exception as e:
        app.logger.info("Warm-up skipped (%s). First request may be slower.", e)


def _lan_ip():
    """Best-effort local network IP so you can open the app from your phone."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = _lan_ip()
    print("=" * 56)
    print("IdeaVault is running. Open it at:")
    print("   On this PC:     http://localhost:5000")
    print("   On your phone:  http://%s:5000   (same Wi-Fi)" % ip)
    print("=" * 56)
    print("Saving notes to:", VAULT_DIR)
    print("Using Ollama model:", OLLAMA_MODEL, "at", OLLAMA_URL)
    print("Warming up the model in the background...")
    # Preload the model so the first idea you capture is fast.
    threading.Thread(target=warm_up, daemon=True).start()
    # host=0.0.0.0 lets other devices on your network reach it.
    app.run(host="0.0.0.0", port=5000, debug=False)
