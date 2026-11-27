# DeutschFlow — Personal German Translation Trainer

A minimalist local Python + SQLite trainer for practicing German translations from vocabulary you collect, available both as a **desktop website (Streamlit)** and an **installable mobile PWA** synchronized against the exact same database.

## Features Included

- **Vocabulary Collection**: Add, search, filter (`A2`, `B1`, `B2`), edit, and delete German words/expressions with English meanings, grammatical notes, and optional notes.
- **AI Challenge Generator (Groq + Google Gemini)**: Generates contextual English sentences with varied sentence structures (`A2`, `B1`, `B2`), avoiding repetitive contexts, with automatic retries and provider fallback.
- **Translation Practice & Strict-but-Fair Evaluation**:
  - Target vocabulary is shown by default; the German answer remains hidden until you submit.
  - Evaluates **grammatical correctness** and **semantic accuracy** separately.
  - Accepts different valid German translations rather than comparing word-for-word against one reference sentence.
  - Distinguishes actual mistakes (cases, articles, prepositions, conjugation, word order) from optional stylistic improvements.
- **Favorites**: Save useful sentences right after reviewing feedback, filter/search saved favorites, inspect stored corrections, or re-practice them without revealing the answer.
- **Synchronized Local SQLite Storage**: Both the Streamlit website (`app.py`) and the mobile PWA (`pwa_server.py`) read and write the same `deutschflow.db` file (WAL mode enabled).

## Project Structure

```text
d:\DFPT\
├── app.py                  # Streamlit desktop website (Practice, Favorites, Vocabulary)
├── pwa_server.py           # Mobile PWA backend (Starlette + Uvicorn) sharing db.py & ai_service.py
├── pwa/                    # Installable mobile PWA frontend (HTML/CSS/JS, manifest, icons, sw.js)
├── ai_service.py           # Isolated Groq + Google Gemini provider & fallback layer
├── db.py                   # SQLite schema & CRUD helpers
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── .streamlit/config.toml  # Warm cream & forest-olive theme
└── tests/test_workflow.py  # Backend, Streamlit UI, and PWA sync tests
```

## Windows Installation & Startup

### 1. Prerequisites
- Python **3.10+** installed (verify with `python --version`)
- A **Groq API key** ([Groq Console](https://console.groq.com/keys)) and/or a **Google Gemini API key** ([Google AI Studio](https://aistudio.google.com/apikey))

### 2. Create and activate a virtual environment
Open PowerShell in `d:\DFPT`:

```powershell
cd d:\DFPT
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> If PowerShell blocks script execution, run:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure your API keys
Copy `.env.example` to `.env` and add your key(s):

```powershell
Copy-Item .env.example .env
```

*(Or enter your keys inside **API Settings** in the app and click **Save Settings Locally**.)*

### 5. Run the Website (Streamlit)

```powershell
streamlit run app.py
```

Open `http://localhost:8501` on your laptop.

### 6. Run the Mobile PWA (Phone + Laptop Synchronized)

```powershell
.\.venv\Scripts\python.exe pwa_server.py
```

The terminal prints two addresses:
- **Laptop:** `http://localhost:8000`
- **Phone (same Wi-Fi):** `http://<your-laptop-ip>:8000`

Because both `app.py` and `pwa_server.py` share `deutschflow.db`, any word, sentence, attempt, or favorite added on your phone or laptop appears on both immediately.

#### Install on your phone
- **iPhone (Safari):** Open `http://<your-laptop-ip>:8000` → tap **Share** → **Add to Home Screen**.
- **Android (Chrome):** Open `http://<your-laptop-ip>:8000` → tap **Install app** (or menu **⋮ → Add to Home screen**).

> **Tip for Windows Firewall:** On first run, allow Python on **Private networks** if Windows asks, so your phone on the same Wi-Fi can reach port `8000`. To also sync when away from home Wi-Fi, you can connect both devices with [Tailscale](https://tailscale.com/) and open `http://<laptop-tailscale-ip>:8000`.

## Running Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
