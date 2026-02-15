# GPA Adaptiv – Deployment (Streamlit Community Cloud)

Du bekommst in ChatGPT keinen sofort gehosteten Link, weil ich hier nichts „live“ im Internet hosten kann.
Aber du kannst in 5–10 Minuten einen **teilbaren Link** erstellen – so wie bei Claude – über **Streamlit Community Cloud**.

## Option A: Streamlit Community Cloud (am einfachsten)

1) Lege ein GitHub-Repository an (z. B. `gpa-adaptiv`)
2) Lade diese 3 Dateien hoch:
   - `app.py`
   - `requirements.txt`
   - `gpa_adaptiv_v2_seed.db`  (die SQLite DB mit Itembank)
3) Öffne https://share.streamlit.io/ und verbinde dein GitHub
4) Wähle Repo + `app.py` als Entry
5) Deploy → du bekommst sofort eine URL wie:
   `https://<name>.streamlit.app`

### Wichtig
- Die DB-Datei muss im Repo liegen (gleicher Ordner wie `app.py`), damit `DB_PATH = "gpa_adaptiv_v2_seed.db"` passt.
- Streamlit Cloud ist super für Prototypen. Für produktiven Schulbetrieb: Auth, Rollen, Datenschutz, Hosting in EU.

## Option B: Hugging Face Spaces (Streamlit)
- Neues Space → SDK: Streamlit
- Dateien hochladen (wie oben)
- Startet automatisch und gibt dir eine sharebare URL.

## Option C: Eigener Server (Render/Fly/Hetzner)
- Auch möglich, aber mehr Setup (Docker, Persistenz für DB).

Wenn du willst, schreibe ich dir auch eine **Dockerfile** + **Procfile** für Render oder Fly.
