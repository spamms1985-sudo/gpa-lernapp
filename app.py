import sqlite3
import json
import random
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st

# =========================
# Config
# =========================
DB_PATH = "gpa_adaptiv_v2_seed.db"   # put DB next to app.py (same folder)
APP_TITLE = "GPA Adaptiv – Web-App (Prototyp)"
APP_SUBTITLE = "Diagnostik → Profil → adaptive Aufgaben · spielerisch + prüfungsnah · Lehrkraft-Dashboard"

WEIGHTS = {1: 1.0, 2: 1.3, 3: 1.7}

LEARN_FIELDS = [
    ("LF1","Sich im Berufsfeld orientieren"),
    ("LF2","Gesundheit erhalten und fördern"),
    ("LF3","Häusliche Pflege und hauswirtschaftliche Abläufe mitgestalten"),
    ("LF4","Bei der Körperpflege anleiten und unterstützen"),
    ("LF5","Menschen bei der Nahrungsaufnahme und Ausscheidung anleiten und unterstützen"),
    ("LF6","Die Mobilität erhalten und fördern"),
    ("LF7","Menschen bei der Bewältigung von Krisen unterstützen"),
    ("LF8","Menschen in besonderen Lebenssituationen unterstützen"),
    ("LF9","Menschen mit körperlichen und geistigen Beeinträchtigungen unterstützen"),
    ("LF10","Menschen in der Endphase des Lebens begleiten und pflegen"),
]
DOMAINS = [
    ("OPS","Operatoren"),
    ("SPR","Sprache (Verstehen/Schreiben)"),
    ("KOG","Kognition (Struktur/Sequenz/Priorität)"),
    ("FACH","Fachwissen (Pflege/Medizin)"),
]

lf_name = dict(LEARN_FIELDS)
domain_name = dict(DOMAINS)

# =========================
# DB helpers
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def ensure_tables(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        display_name TEXT NOT NULL,
        class_code TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        class_code TEXT,
        item_id TEXT NOT NULL,
        field_id TEXT NOT NULL,
        domain_id TEXT NOT NULL,
        difficulty INTEGER NOT NULL,
        correct INTEGER NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    conn.commit()

def load_items(conn) -> List[Dict[str, Any]]:
    df = pd.read_sql_query("SELECT payload_json FROM items", conn)
    items = [json.loads(x) for x in df["payload_json"].tolist()]
    return items

def upsert_user(conn, user_id: str, role: str, display_name: str, class_code: str):
    conn.execute("""
    INSERT INTO users(user_id, role, display_name, class_code, created_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET
        role=excluded.role,
        display_name=excluded.display_name,
        class_code=excluded.class_code
    """, (user_id, role, display_name, class_code, datetime.utcnow().isoformat()))
    conn.commit()

def log_attempt(conn, user_id: str, class_code: str, item: Dict[str, Any], correct: bool, response: Dict[str, Any]):
    conn.execute("""
    INSERT INTO attempts(user_id, class_code, item_id, field_id, domain_id, difficulty, correct, response_json, created_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        user_id,
        class_code,
        item["id"],
        item["field"],
        item["domain"],
        int(item["difficulty"]),
        int(bool(correct)),
        json.dumps(response, ensure_ascii=False),
        datetime.utcnow().isoformat()
    ))
    conn.commit()

def get_users(conn) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM users ORDER BY created_at DESC", conn)

def get_attempts(conn, user_id: Optional[str] = None, class_code: Optional[str] = None) -> pd.DataFrame:
    q = "SELECT * FROM attempts"
    params = []
    conds = []
    if user_id:
        conds.append("user_id=?")
        params.append(user_id)
    if class_code:
        conds.append("class_code=?")
        params.append(class_code)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY attempt_id DESC"
    return pd.read_sql_query(q, conn, params=params)

# =========================
# Scoring / Profile
# =========================
def compute_profile(attempts_df: pd.DataFrame) -> Dict[Tuple[str, str], Dict[str, Any]]:
    if attempts_df.empty:
        return {}

    agg: Dict[Tuple[str, str], Dict[str, float]] = {}
    for _, r in attempts_df.iterrows():
        key = (r["field_id"], r["domain_id"])
        w = WEIGHTS.get(int(r["difficulty"]), 1.0)
        agg.setdefault(key, {"w": 0.0, "c": 0.0, "n": 0.0})
        agg[key]["w"] += w
        agg[key]["c"] += w * (1.0 if int(r["correct"]) == 1 else 0.0)
        agg[key]["n"] += 1.0

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, v in agg.items():
        acc = v["c"] / max(v["w"], 1e-9)
        mastery = acc
        if mastery < 0.45:
            level = 1
        elif mastery < 0.75:
            level = 2
        else:
            level = 3
        out[key] = {
            "accuracy": round(acc, 2),
            "mastery": round(mastery, 2),
            "level": level,
            "n": int(v["n"])
        }
    return out

def pick_items_adaptive(items: List[Dict[str, Any]],
                        profile: Dict[Tuple[str, str], Dict[str, Any]],
                        field_id: Optional[str],
                        focus_domain: Optional[str],
                        already_seen: set,
                        k: int = 10) -> List[Dict[str, Any]]:
    pool = []
    for it in items:
        if field_id and it["field"] != field_id:
            continue
        if focus_domain and it["domain"] != focus_domain:
            continue
        target = profile.get((it["field"], it["domain"]), {}).get("level", 1)
        dist = abs(int(it["difficulty"]) - int(target))
        seen_penalty = 0.6 if it["id"] in already_seen else 0.0
        score = dist + seen_penalty + random.random() * 0.15
        pool.append((score, it))

    pool.sort(key=lambda x: x[0])

    chosen = []
    for _, it in pool:
        if it["id"] in already_seen and len(chosen) < k - 2:
            continue
        chosen.append(it)
        if len(chosen) >= k:
            break

    # mix: add one easy and one challenge if possible
    if chosen:
        easy = [it for it in pool if it[1]["difficulty"] == 1]
        hard = [it for it in pool if it[1]["difficulty"] == 3]
        if easy:
            chosen = [easy[0][1]] + chosen[:-1]
        if hard and len(chosen) >= 3:
            chosen[-1] = hard[0][1]
    return chosen[:k]

# =========================
# Rendering helpers
# =========================
def simple_language(text: str) -> str:
    repl = {
        "Begründe": "Sag warum",
        "Beurteile": "Entscheide",
        "Beschreibe": "Erkläre kurz",
        "Erkläre": "Sag wie und warum",
        "Leite ab": "Entscheide, was du tust",
        "Symptom": "Zeichen (was die Person merkt)",
        "Befund": "Ergebnis (was man misst/prüft)",
    }
    out = text
    for a, b in repl.items():
        out = out.replace(a, b)
    return out

def render_item(item: Dict[str, Any], easy_mode: bool, key_prefix: str) -> Optional[Dict[str, Any]]:
    prompt = item.get("prompt_easy") if easy_mode and item.get("prompt_easy") else item.get("prompt", "")
    st.subheader(f"{item['type'].upper()} · {item['field']} · {item['domain']} · Stufe {item['difficulty']}")
    st.write(prompt)

    t = item["type"]

    if t in ("mcq", "case", "pattern"):
        choice = st.radio("Antwort wählen:", item["options"], index=None, key=f"{key_prefix}{item['id']}_mcq")
        if st.button("Abgeben", key=f"{key_prefix}{item['id']}_submit"):
            if choice is None:
                st.warning("Bitte wähle eine Option.")
                return None
            correct = (item["options"].index(choice) == item["answer"])
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": {"choice": choice}}

    if t == "cloze":
        choice = st.selectbox("Wort wählen:", item["options"], index=None, key=f"{key_prefix}{item['id']}_cloze")
        if st.button("Abgeben", key=f"{key_prefix}{item['id']}_submit"):
            if choice is None:
                st.warning("Bitte wähle ein Wort.")
                return None
            correct = (item["options"].index(choice) == item["answer"])
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": {"choice": choice}}

    if t == "order":
        st.caption("Gib die Reihenfolge als Zahlenfolge ein, z. B. 1-3-2-4")
        for i, s in enumerate(item["steps"], start=1):
            st.write(f"{i}. {s}")
        text = st.text_input("Reihenfolge:", key=f"{key_prefix}{item['id']}_order")
        if st.button("Abgeben", key=f"{key_prefix}{item['id']}_submit"):
            try:
                parts = [int(p.strip()) for p in text.replace("–", "-").split("-")]
                idx = [p - 1 for p in parts]
                correct = (idx == item["correct_order"])
                if correct:
                    st.success("Richtig ✅")
                else:
                    sol = "-".join(str(i + 1) for i in item["correct_order"])
                    st.error(f"Nicht ganz ❌ · Lösung: {sol}")
                return {"correct": correct, "response": {"order": parts}}
            except Exception:
                st.warning("Bitte als Zahlenfolge eingeben, z. B. 1-3-2-4.")
                return None

    if t == "match":
        st.caption("Ordne zu (Prototype: pro Begriff auswählbar).")
        responses = {}
        right_options = [r for (_, r) in item["pairs"]]
        for left, _right in item["pairs"]:
            responses[left] = st.selectbox(left, right_options, index=None, key=f"{key_prefix}{item['id']}_{left}")
        if st.button("Abgeben", key=f"{key_prefix}{item['id']}_submit"):
            correct = True
            for left, right in item["pairs"]:
                if responses.get(left) != right:
                    correct = False
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": responses}

    if t == "short":
        answer = st.text_area("Deine Antwort:", key=f"{key_prefix}{item['id']}_short")
        if st.button("Abgeben", key=f"{key_prefix}{item['id']}_submit"):
            text = (answer or "").lower()
            kws = item.get("keywords", [])
            hits = sum(1 for kw in kws if kw.lower() in text)
            correct = hits >= max(1, len(kws) // 4) if kws else (len(text.strip()) > 10)
            st.success(f"Abgegeben ✅ · (Prototype-Auswertung: {hits} Stichwort-Treffer)")
            st.info("Kurzantworten: für den Pilotbetrieb ideal mit Rubrik + Lehrkraft-Review.")
            return {"correct": correct, "response": {"text": answer, "hits": hits}}

    st.info("Item-Typ noch nicht implementiert.")
    return None

# =========================
# Streamlit App
# =========================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

conn = get_conn()
ensure_tables(conn)
items = load_items(conn)

with st.sidebar:
    st.header("Login")
    role_ui = st.selectbox("Rolle", ["Schüler:in", "Lehrkraft"])
    role = "student" if role_ui == "Schüler:in" else "teacher"
    user_id = st.text_input("User-ID", value="demo_schueler" if role == "student" else "demo_lehrkraft")
    display_name = st.text_input("Name", value="Demo")
    class_code = st.text_input("Klasse/Kurs (Code)", value="GPA-TEST")
    easy_mode = st.toggle("Einfache Sprache (A2/B1-ähnlich)", value=False)
    if st.button("Einloggen"):
        upsert_user(conn, user_id, role, display_name, class_code)
        st.success("Eingeloggt.")

# Persist user regardless (so teacher can see demo quickly)
upsert_user(conn, user_id, role, display_name, class_code)

my_attempts = get_attempts(conn, user_id=user_id)
profile = compute_profile(my_attempts)
seen_ids = set(my_attempts["item_id"].tolist()) if not my_attempts.empty else set()

tabs = st.tabs(["Schüler:in", "Lehrkraft", "Itembank"])

# -------------------------
# Schüler
# -------------------------
with tabs[0]:
    st.subheader("Schülerbereich")

    c1, c2, c3 = st.columns(3)
    c1.metric("Bearbeitete Aufgaben", int(len(my_attempts)))
    c2.metric("Ø richtig", round(float(my_attempts["correct"].mean()) if not my_attempts.empty else 0.0, 2))
    c3.metric("Items in Bank", len(items))

    st.markdown("### 1) Diagnostik (Mix: Operatoren + Sprache + Kognition + Fachwissen)")
    diag_len = st.slider("Diagnostik-Länge", min_value=10, max_value=30, value=20, step=5)

    if st.button("Diagnostik starten"):
        domains = ["OPS", "SPR", "KOG", "FACH"]
        diag_items: List[Dict[str, Any]] = []
        per_domain = max(2, diag_len // 5)
        for d in domains:
            cand = [it for it in items if it["domain"] == d]
            if cand:
                diag_items.extend(random.sample(cand, k=min(per_domain, len(cand))))
        rest = diag_len - len(diag_items)
        if rest > 0:
            diag_items.extend(random.sample(items, k=min(rest, len(items))))
        random.shuffle(diag_items)
        st.session_state["diag_items"] = diag_items[:diag_len]
        st.session_state["diag_i"] = 0

    diag_items = st.session_state.get("diag_items", [])
    if diag_items:
        i = st.session_state.get("diag_i", 0)
        st.progress((i + 1) / len(diag_items))
        it = diag_items[i]
        res = render_item(it, easy_mode=easy_mode, key_prefix="diag_")
        if res is not None:
            log_attempt(conn, user_id, class_code, it, res["correct"], {"mode": "diagnostic", **res["response"]})
            if i + 1 < len(diag_items):
                st.session_state["diag_i"] = i + 1
                st.rerun()
            else:
                st.success("Diagnostik abgeschlossen ✅")
                st.session_state["diag_items"] = []
                st.session_state["diag_i"] = 0

    st.markdown("### 2) Lernfeld wählen & adaptiv üben (Mix aus Spiel + Prüfung)")
    lf = st.selectbox("Lernfeld", [x for (x, _n) in LEARN_FIELDS], format_func=lambda x: f"{x} – {lf_name.get(x,x)}")
    dom = st.selectbox("Fokus", [x for (x, _n) in DOMAINS], format_func=lambda x: f"{x} – {domain_name.get(x,x)}")

    lvl = profile.get((lf, dom), {}).get("level", 1)
    acc = profile.get((lf, dom), {}).get("accuracy", None)
    st.info(f"Aktuelle Schätzung in {lf}/{dom}: Level **{lvl}**" + (f" · Accuracy ~ {acc}" if acc is not None else ""))

    practice_len = st.slider("Übungsrunde", min_value=5, max_value=15, value=8, step=1)

    if st.button("Adaptive Runde starten"):
        chosen = pick_items_adaptive(items, profile, field_id=lf, focus_domain=dom, already_seen=seen_ids, k=practice_len)
        st.session_state["prac_items"] = chosen
        st.session_state["prac_i"] = 0

    prac_items = st.session_state.get("prac_items", [])
    if prac_items:
        i = st.session_state.get("prac_i", 0)
        st.progress((i + 1) / len(prac_items))
        it = prac_items[i]
        res = render_item(it, easy_mode=easy_mode, key_prefix="prac_")
        if res is not None:
            log_attempt(conn, user_id, class_code, it, res["correct"], {"mode": "practice", **res["response"]})
            if i + 1 < len(prac_items):
                st.session_state["prac_i"] = i + 1
                st.rerun()
            else:
                st.success("Übungsrunde abgeschlossen 🎉")
                st.session_state["prac_items"] = []
                st.session_state["prac_i"] = 0

    st.markdown("### 3) Dein Profil (pro Lernfeld + Bereich)")
    rows = []
    for (f, d), v in sorted(profile.items()):
        rows.append({
            "Lernfeld": f"{f} – {lf_name.get(f,f)}",
            "Bereich": f"{d} – {domain_name.get(d,d)}",
            "Level": v["level"],
            "Accuracy": v["accuracy"],
            "n": v["n"],
        })
    st.dataframe(pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Lernfeld","Bereich","Level","Accuracy","n"]),
                 use_container_width=True)

# -------------------------
# Lehrkraft
# -------------------------
with tabs[1]:
    st.subheader("Lehrkraft-Dashboard")

    users_df = get_users(conn)
    class_options = sorted([c for c in users_df["class_code"].dropna().unique().tolist() if c])
    chosen_class = st.selectbox("Klasse/Kurs", class_options if class_options else [class_code])

    class_users = users_df[(users_df["class_code"] == chosen_class) & (users_df["role"] == "student")]
    class_attempts = get_attempts(conn, class_code=chosen_class)

    c1, c2, c3 = st.columns(3)
    c1.metric("Schüler:innen", int(len(class_users)))
    c2.metric("Versuche gesamt", int(len(class_attempts)))
    c3.metric("Items in Bank", len(items))

    st.markdown("### Klassenübersicht (Profil-Snapshot)")
    if not class_users.empty:
        overview_rows = []
        for sid in class_users["user_id"].tolist():
            s_attempts = get_attempts(conn, user_id=sid)
            s_prof = compute_profile(s_attempts)

            def avg_level(domain_id: str) -> float:
                vals = [v["level"] for (f, d), v in s_prof.items() if d == domain_id]
                return round(sum(vals) / len(vals), 2) if vals else 1.0

            overview_rows.append({
                "User-ID": sid,
                "Name": class_users[class_users["user_id"] == sid]["display_name"].iloc[0],
                "Ø Level OPS": avg_level("OPS"),
                "Ø Level SPR": avg_level("SPR"),
                "Ø Level KOG": avg_level("KOG"),
                "Ø Level FACH": avg_level("FACH"),
                "Versuche": int(len(s_attempts))
            })
        st.dataframe(pd.DataFrame(overview_rows), use_container_width=True)

        st.markdown("### Einzelprofil")
        sid = st.selectbox("Schüler:in auswählen", class_users["user_id"].tolist())
        s_attempts = get_attempts(conn, user_id=sid)
        s_prof = compute_profile(s_attempts)

        st.write("**Letzte 20 Versuche**")
        if not s_attempts.empty:
            show = s_attempts.copy()
            show["created_at"] = pd.to_datetime(show["created_at"])
            st.dataframe(show[["attempt_id","item_id","field_id","domain_id","difficulty","correct","created_at"]].head(20),
                         use_container_width=True)
        else:
            st.info("Noch keine Daten.")

        st.write("**Kompetenzprofil**")
        rows = []
        for (f, d), v in sorted(s_prof.items()):
            rows.append({
                "Lernfeld": f"{f} – {lf_name.get(f,f)}",
                "Bereich": f"{d} – {domain_name.get(d,d)}",
                "Level": v["level"],
                "Accuracy": v["accuracy"],
                "n": v["n"],
            })
        st.dataframe(pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Lernfeld","Bereich","Level","Accuracy","n"]),
                     use_container_width=True)

        st.markdown("### Export (CSV)")
        export = class_attempts.copy()
        csv_bytes = export.to_csv(index=False).encode("utf-8")
        st.download_button("CSV herunterladen", data=csv_bytes, file_name=f"export_{chosen_class}.csv", mime="text/csv")
    else:
        st.info("Noch keine Schüler:innen in dieser Klasse. (Schüler:innen loggen sich mit Klassen-Code ein.)")

# -------------------------
# Itembank
# -------------------------
with tabs[2]:
    st.subheader("Itembank")
    st.write("Items werden aus der DB geladen (Tabelle: items).")

    f = st.selectbox("Filter Lernfeld", ["(alle)"] + [x for (x,_n) in LEARN_FIELDS])
    d = st.selectbox("Filter Bereich", ["(alle)"] + [x for (x,_n) in DOMAINS])
    diff = st.selectbox("Filter Schwierigkeit", ["(alle)"] + [1,2,3])

    filtered = []
    for it in items:
        if f != "(alle)" and it["field"] != f:
            continue
        if d != "(alle)" and it["domain"] != d:
            continue
        if diff != "(alle)" and int(it["difficulty"]) != int(diff):
            continue
        filtered.append(it)

    st.write(f"Gefundene Items: {len(filtered)}")
    rows = []
    for it in filtered[:50]:
        rows.append({
            "id": it["id"],
            "LF": it["field"],
            "Bereich": it["domain"],
            "Diff": it["difficulty"],
            "Typ": it["type"],
            "Prompt": it.get("prompt","")
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

st.caption("Hosting-Hinweis: Für einen teilbaren Link brauchst du Deployment (z. B. Streamlit Community Cloud).")
