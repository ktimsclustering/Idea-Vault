# 💡 IdeaVault

A tiny, fully **local** idea catalog. You dump a raw thought into a clean
web page; your own LLM (running through [Ollama](https://ollama.com)) gives it a
title, picks a category, adds tags, and writes a one-line summary. Everything is
saved as plain **Markdown files** on your own computer — no cloud, no account,
nothing leaves your machine.

Think of it as a private, offline, Notion-style inbox for ideas.

---

## What you get

- A browser UI: a "dump" box, a category sidebar, searchable idea cards, and click-to-edit.
- Automatic organizing by a local model: **title, category, tags, summary**.
- Storage as readable `.md` files (with frontmatter) in a `vault\` folder — open them in Notion, Obsidian, VS Code, or import anywhere.
- Works **offline**. If the model isn't running, ideas are still saved to an "Inbox" and you can organize them by hand.

---

## Quick start (Windows)

1. **Install Python** (if you don't have it): https://www.python.org/downloads/
   — tick *"Add python.exe to PATH"* during setup.

2. **Install Ollama and a model** (for the auto-organizing):
   - Download Ollama: https://ollama.com
   - Open a terminal and pull a small, fast model:
     ```
     ollama pull llama3.2
     ```
   - Ollama runs in the background automatically after install.

3. **Start IdeaVault**: double-click **`start.bat`**.
   It sets everything up on first run and opens http://localhost:5000 in your browser.

That's it. Type an idea, press **Capture** (or Ctrl+Enter), and watch it get filed.

---

## Where your ideas live

Inside this folder:

```
vault\
  product-ideas\
    20260613-...-a1b2c3.md
  reading-list\
    ...
```

Each file looks like:

```markdown
---
id: 20260613153012-a1b2c3
title: App that turns voice notes into recipes
category: Product ideas
tags: [cooking, ai, mobile]
created: 2026-06-13T15:30:12
updated: 2026-06-13T15:30:12
summary: A mobile app that transcribes spoken cooking steps into structured recipes.
---

Original raw note text goes here, exactly as you typed it.
```

Because they're just Markdown, you can back them up, sync them, or open them in any other notes app.

---

## Settings (optional)

The app reads a few environment variables if you want to change defaults:

| Variable          | Default                  | Meaning                              |
|-------------------|--------------------------|--------------------------------------|
| `OLLAMA_MODEL`    | `llama3.2`               | Which local model to use             |
| `OLLAMA_URL`      | `http://localhost:11434` | Where Ollama is listening            |
| `IDEAVAULT_DIR`   | `.\vault`                | Where Markdown files are stored      |

Example (PowerShell):
```powershell
$env:OLLAMA_MODEL="qwen2.5"; python app.py
```

---

## Manual run (instead of start.bat)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Then open http://localhost:5000.

---

## Troubleshooting

- **Ideas all go to "Inbox".** The model isn't reachable. Make sure Ollama is
  installed and you ran `ollama pull llama3.2`. Test it with `ollama run llama3.2`.
- **Port 5000 in use.** Edit the last line of `app.py` and change `port=5000`.
- **Want a different model.** Pull it (`ollama pull <name>`) and set `OLLAMA_MODEL`.

---

Private by design: the only network call is to Ollama on your own machine.
