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
DB_PATH = "gpa_adaptiv_v2_seed.db"   # DB must sit next to this file in the repo
APP_TITLE = "GPA Lernapp"
APP_SUBTITLE = "Lernfeld wählen → Lernstand erheben → passende Aufgaben"

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
    ("SPR","Sprache"),
    ("KOG","Denken & Reihenfolgen"),
    ("FACH","Fachwissen"),
]

lf_name = dict(LEARN_FIELDS)
domain_name = dict(DOMAINS)

# Friendly labels for task types (hide internal names)
TYPE_LABEL = {
    "mcq": "Quiz",
    "case": "Fallbeispiel",
    "cloze": "Lückentext",
    "cloze2": "Lückentext",
    "match": "Zuordnen",
    "order": "Reihenfolge",
    "short": "Kurzantwort",
    "pattern": "Quiz",
}

# =========================
# DB helpers
# =========================
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

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
    return [json.loads(x) for x in df["payload_json"].tolist()]

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

def log_attempt(conn, user_id: str, class_code: str, item: Dict[str, Any], correct: bool, response: Dict[str, Any], mode: str):
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
        json.dumps({"mode": mode, **response}, ensure_ascii=False),
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
        if acc < 0.45:
            level = 1
        elif acc < 0.75:
            level = 2
        else:
            level = 3
        out[key] = {"accuracy": round(acc, 2), "level": level, "n": int(v["n"])}
    return out

def pick_items_for_diagnostic(items: List[Dict[str, Any]], field_id: str, n: int) -> List[Dict[str, Any]]:
    domains = ["OPS", "SPR", "KOG", "FACH"]
    per_domain = max(2, n // 5)
    chosen: List[Dict[str, Any]] = []
    for d in domains:
        cand = [it for it in items if it["field"] == field_id and it["domain"] == d]
        if cand:
            chosen.extend(random.sample(cand, k=min(per_domain, len(cand))))
    rest = n - len(chosen)
    cand_all = [it for it in items if it["field"] == field_id]
    if rest > 0 and cand_all:
        chosen.extend(random.sample(cand_all, k=min(rest, len(cand_all))))
    random.shuffle(chosen)
    return chosen[:n]

def pick_items_adaptive(items: List[Dict[str, Any]],
                        profile: Dict[Tuple[str, str], Dict[str, Any]],
                        field_id: str,
                        already_seen: set,
                        k: int = 8) -> List[Dict[str, Any]]:
    dom_levels = {}
    for dom in ["OPS", "SPR", "KOG", "FACH"]:
        dom_levels[dom] = profile.get((field_id, dom), {}).get("level", 1)

    sorted_domains = sorted(dom_levels.items(), key=lambda x: x[1])  # low first
    dom_plan = []
    for dom, lvl in sorted_domains:
        dom_plan.extend([dom] * (4 - min(3, lvl)))  # lvl1 -> 3 slots, lvl2 -> 2, lvl3 ->1
    if not dom_plan:
        dom_plan = ["OPS","SPR","KOG","FACH"]

    picked = []
    for _ in range(k):
        dom = random.choice(dom_plan)
        target = dom_levels.get(dom, 1)
        pool = []
        for it in items:
            if it["field"] != field_id or it["domain"] != dom:
                continue
            dist = abs(int(it["difficulty"]) - int(target))
            seen_penalty = 0.6 if it["id"] in already_seen else 0.0
            score = dist + seen_penalty + random.random() * 0.2
            pool.append((score, it))
        pool.sort(key=lambda x: x[0])
        if pool:
            picked.append(pool[0][1])
            already_seen.add(pool[0][1]["id"])
    return picked[:k]

# =========================
# Rendering
# =========================
def render_header_card(field_id: str):
    st.markdown(
        f"""
        <div style="padding:14px;border-radius:14px;border:1px solid rgba(0,0,0,.12);">
          <div style="font-size:14px;opacity:.8;">Ausgewähltes Lernfeld</div>
          <div style="font-size:22px;font-weight:700;">{field_id} – {lf_name.get(field_id, field_id)}</div>
          <div style="margin-top:6px;opacity:.85;">1) Lernstand erheben · 2) Üben mit passenden Aufgaben</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_task_badge(item: Dict[str, Any]):
    label = TYPE_LABEL.get(item.get("type",""), "Aufgabe")
    dom = domain_name.get(item.get("domain",""), item.get("domain",""))
    diff = int(item.get("difficulty", 1))
    stars = "⭐" * diff
    st.caption(f"{label} · {dom} · {stars}")

def render_item(item: Dict[str, Any], easy_mode: bool, key_prefix: str) -> Optional[Dict[str, Any]]:
    prompt = item.get("prompt_easy") if easy_mode and item.get("prompt_easy") else item.get("prompt", "")
    render_task_badge(item)
    st.write(prompt)

    t = item["type"]

    if t in ("mcq", "case", "pattern"):
        choice = st.radio("Antwort:", item["options"], index=None, key=f"{key_prefix}{item['id']}_mcq")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            if choice is None:
                st.warning("Bitte wähle eine Option.")
                return None
            correct = (item["options"].index(choice) == item["answer"])
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": {"choice": choice}}

    if t == "cloze":
        choice = st.selectbox("Wort:", item["options"], index=None, key=f"{key_prefix}{item['id']}_cloze")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            if choice is None:
                st.warning("Bitte wähle ein Wort.")
                return None
            correct = (item["options"].index(choice) == item["answer"])
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": {"choice": choice}}

    if t == "order":
        st.caption("Tipp: schreibe z. B. 1-3-2-4")
        for i, s in enumerate(item["steps"], start=1):
            st.write(f"{i}. {s}")
        text = st.text_input("Reihenfolge:", key=f"{key_prefix}{item['id']}_order")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            try:
                parts = [int(p.strip()) for p in text.replace("–", "-").split("-")]
                idx = [p - 1 for p in parts]
                correct = (idx == item["correct_order"])
                st.success("Richtig ✅" if correct else "Nicht ganz ❌")
                return {"correct": correct, "response": {"order": parts}}
            except Exception:
                st.warning("Bitte als Zahlenfolge eingeben, z. B. 1-3-2-4.")
                return None

    if t == "match":
        st.caption("Ordne zu:")
        responses = {}
        right_options = [r for (_, r) in item["pairs"]]
        for left, _right in item["pairs"]:
            responses[left] = st.selectbox(left, right_options, index=None, key=f"{key_prefix}{item['id']}_{left}")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            correct = True
            for left, right in item["pairs"]:
                if responses.get(left) != right:
                    correct = False
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": responses}

    if t == "short":
        answer = st.text_area("Deine Antwort:", key=f"{key_prefix}{item['id']}_short")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            text = (answer or "").lower()
            kws = item.get("keywords", [])
            hits = sum(1 for kw in kws if kw.lower() in text)
            correct = hits >= max(1, len(kws) // 4) if kws else (len(text.strip()) > 10)
            st.success("Danke ✅")
            return {"correct": correct, "response": {"text": answer, "hits": hits}}

    st.info("Dieser Aufgabentyp ist noch nicht implementiert.")
    return None

# =========================
# App
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
    easy_mode = st.toggle("Einfache Sprache", value=False)
    if st.button("Einloggen"):
        upsert_user(conn, user_id, role, display_name, class_code)
        st.success("Eingeloggt.")

upsert_user(conn, user_id, role, display_name, class_code)

my_attempts = get_attempts(conn, user_id=user_id)
profile = compute_profile(my_attempts)
seen_ids = set(my_attempts["item_id"].tolist()) if not my_attempts.empty else set()

tabs = st.tabs(["Schüler:in", "Lehrkraft"])

with tabs[0]:
    st.subheader("Schülerbereich")

    st.markdown("### 1) Lernfeld auswählen")
    field_id = st.selectbox(
        "Wähle dein Lernfeld:",
        [x for (x, _n) in LEARN_FIELDS],
        format_func=lambda x: f"{x} – {lf_name.get(x, x)}"
    )
    render_header_card(field_id)

    st.markdown("### Dein aktueller Stand in diesem Lernfeld")
    lf_rows = []
    for dom in ["OPS", "SPR", "KOG", "FACH"]:
        v = profile.get((field_id, dom), {"level": 1, "accuracy": 0.0, "n": 0})
        lf_rows.append({
            "Bereich": domain_name.get(dom, dom),
            "Level": v["level"],
            "Trefferquote": v["accuracy"],
            "Aufgaben": v["n"]
        })
    st.dataframe(pd.DataFrame(lf_rows), use_container_width=True, hide_index=True)

    st.markdown("### 2) Lernstand im Lernfeld erheben")
    diag_len = st.slider("Anzahl Aufgaben (Diagnostik)", 8, 20, 12, 2)

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Lernstand starten"):
            diag_items = pick_items_for_diagnostic(items, field_id, diag_len)
            st.session_state["flow_mode"] = "diagnostic"
            st.session_state["flow_field"] = field_id
            st.session_state["flow_items"] = diag_items
            st.session_state["flow_i"] = 0
            st.rerun()

    with colB:
        if st.button("Diagnostik zurücksetzen (nur mich)"):
            conn.execute("DELETE FROM attempts WHERE user_id=? AND field_id=?", (user_id, field_id))
            conn.commit()
            st.success("Zurückgesetzt. Bitte Seite neu laden.")
            st.stop()

    flow_items = st.session_state.get("flow_items", [])
    flow_i = st.session_state.get("flow_i", 0)
    flow_mode = st.session_state.get("flow_mode", None)
    flow_field = st.session_state.get("flow_field", None)

    if flow_items and flow_field == field_id:
        st.markdown("---")
        st.markdown("### Aufgabe")
        st.progress((flow_i + 1) / len(flow_items))
        it = flow_items[flow_i]
        res = render_item(it, easy_mode=easy_mode, key_prefix=f"flow_{flow_mode}_")
        if res is not None:
            log_attempt(conn, user_id, class_code, it, res["correct"], res["response"], mode=flow_mode)
            if flow_i + 1 < len(flow_items):
                st.session_state["flow_i"] = flow_i + 1
                st.rerun()
            else:
                st.success("Fertig ✅")
                st.session_state["flow_items"] = []
                st.session_state["flow_i"] = 0
                st.session_state["flow_mode"] = None
                st.session_state["flow_field"] = None
                st.rerun()

    st.markdown("### 3) Passende Aufgaben üben")
    practice_len = st.slider("Übungsrunde", 5, 15, 8, 1)

    if st.button("Übungsrunde starten"):
        my_attempts2 = get_attempts(conn, user_id=user_id)
        profile2 = compute_profile(my_attempts2)
        seen2 = set(my_attempts2["item_id"].tolist()) if not my_attempts2.empty else set()
        chosen = pick_items_adaptive(items, profile2, field_id=field_id, already_seen=seen2, k=practice_len)
        st.session_state["flow_mode"] = "practice"
        st.session_state["flow_field"] = field_id
        st.session_state["flow_items"] = chosen
        st.session_state["flow_i"] = 0
        st.rerun()

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

    if class_users.empty:
        st.info("Noch keine Schüler:innen in dieser Klasse. (Sie loggen sich mit dem Klassen-Code ein.)")
    else:
        sid = st.selectbox("Schüler:in auswählen", class_users["user_id"].tolist())
        s_attempts = get_attempts(conn, user_id=sid)
        s_prof = compute_profile(s_attempts)

        st.write("**Kompetenzprofil (pro Lernfeld & Bereich)**")
        rows = []
        for (lf, _n) in LEARN_FIELDS:
            for dom in ["OPS","SPR","KOG","FACH"]:
                v = s_prof.get((lf, dom), {"level": 1, "accuracy": 0.0, "n": 0})
                rows.append({
                    "Lernfeld": f"{lf} – {lf_name.get(lf, lf)}",
                    "Bereich": domain_name.get(dom, dom),
                    "Level": v["level"],
                    "Trefferquote": v["accuracy"],
                    "Aufgaben": v["n"],
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("### Export (CSV)")
        csv_bytes = class_attempts.to_csv(index=False).encode("utf-8")
        st.download_button("CSV herunterladen", data=csv_bytes, file_name=f"export_{chosen_class}.csv", mime="text/csv")

st.caption("Prototype: Aufgabentypen werden schülerfreundlich benannt (Quiz/Zuordnen/…).")
