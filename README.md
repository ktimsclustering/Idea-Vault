<div align="center">
  <h1>💡 IdeaVault</h1>
  <p><b>A tiny, fully local idea catalog powered by your own LLM.</b></p>
</div>

<br />

<!-- 📸 SCREENSHOT SECTION 📸 -->
<!-- Replace the placeholder URL inside the parenthesis below with your actual image path or upload it via GitHub's web UI -->
<img width="864" height="388" alt="IdeaVault UI" src="https://github.com/user-attachments/assets/2de63860-47cf-4988-8a2e-d6fa85779e9d" />



---

## ✨ What is it?

You dump a raw thought into a clean web page; your own LLM (running through [Ollama](https://ollama.com)) automatically gives it a:
- 🏷️ **Title**
- 📁 **Category**
- 🔖 **Tags**
- 📝 **Summary**

Everything is saved as plain **Markdown files** on your own computer — no cloud, no account, nothing leaves your machine. Think of it as a private, offline, Notion-style inbox for ideas.

## 🚀 What you get

- **A beautiful browser UI:** a "dump" box, a category sidebar, searchable idea cards, and click-to-edit.
- **Automatic organizing:** No more manual sorting.
- **Markdown portability:** Your ideas are stored as readable `.md` files (with frontmatter) in a `vault\` folder — open them in Notion, Obsidian, VS Code, or import anywhere.
- **Offline support:** If the model isn't running, ideas are still saved to an "Inbox" and you can organize them by hand.

## ⚡ Quick Start (Windows)

1. **Install Python** (if you don't have it): [Download here](https://www.python.org/downloads/) 
   *(Make sure to tick "Add python.exe to PATH" during setup).*

2. **Install Ollama and a model** (for the auto-organizing):
   - Download Ollama: [ollama.com](https://ollama.com)
   - Open a terminal and pull a small, fast model:
     ```bash
     ollama pull llama3.2
     ```

3. **Start IdeaVault**: 
   - Double-click **`start.bat`**.
   - It sets everything up on the first run and opens `http://localhost:5000` in your browser.

> [!TIP]
> **Capture an idea:** Type an idea, press **Capture** (or `Ctrl+Enter`), and watch it get filed instantly!

## 📂 Where your ideas live

Inside the app folder, you will find:
```text
vault\
  product-ideas\
    20260613-...-a1b2c3.md
  reading-list\
    ...
```

Each file looks like this:
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

## ⚙️ Settings (optional)

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

## 🛠️ Manual Run

Instead of using `start.bat`, you can run it manually:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Then open `http://localhost:5000`.

## 🆘 Troubleshooting

- **Ideas all go to "Inbox"**  
  The model isn't reachable. Make sure Ollama is installed and you ran `ollama pull llama3.2`. Test it with `ollama run llama3.2`.
- **Port 5000 in use**  
  Edit the last line of `app.py` and change `port=5000` to something else.
- **Want a different model**  
  Pull it (`ollama pull <name>`) and set `OLLAMA_MODEL`.

---

<div align="center">
  <sub>Private by design: the only network call is to Ollama on your own machine.</sub>
</div>
