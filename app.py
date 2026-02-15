import sqlite3
import json
import random
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st

# =========================
# Paths / Config
# =========================
DB_ITEMS_PATH = "gpa_items_fachwissen_v1.db"   # must exist in repo
DB_DATA_PATH = "gpa_app_data.db"              # created automatically

APP_TITLE = "GPA Lernapp"
APP_SUBTITLE = "Lernfeld → Diagnose (Fachwissen) → Üben · Lehrkraft: Diagnose, Fehleranalyse, Förderung, Material"

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
    ("FACH","Fachwissen"),
    ("SPR","Sprache"),
    ("KOG","Denken & Reihenfolge"),
    ("OPS","Operatoren (kurz)"),
]

TYPE_LABEL = {
    "mcq": "Quiz",
    "case": "Fall",
    "cloze": "Lücke",
    "match": "Zuordnen",
    "order": "Reihenfolge",
    "short": "Kurzantwort",
    "pattern": "Quiz",
}

lf_name = dict(LEARN_FIELDS)
domain_name = dict(DOMAINS)

# =========================
# DB helpers
# =========================
def conn_items():
    return sqlite3.connect(DB_ITEMS_PATH, check_same_thread=False)

def conn_data():
    return sqlite3.connect(DB_DATA_PATH, check_same_thread=False)

def ensure_data_tables(c: sqlite3.Connection):
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        display_name TEXT,
        class_code TEXT,
        created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS attempts(
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
    c.execute("""CREATE TABLE IF NOT EXISTS materials(
        material_id INTEGER PRIMARY KEY AUTOINCREMENT,
        uploader_user_id TEXT NOT NULL,
        class_code TEXT,
        title TEXT NOT NULL,
        description TEXT,
        field_id TEXT,
        topic TEXT,
        mime TEXT,
        filename TEXT,
        content BLOB NOT NULL,
        created_at TEXT NOT NULL
    )""")
    c.commit()

def upsert_user(c: sqlite3.Connection, user_id: str, role: str, display_name: str, class_code: str):
    c.execute("""
    INSERT INTO users(user_id, role, display_name, class_code, created_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET
        role=excluded.role,
        display_name=excluded.display_name,
        class_code=excluded.class_code
    """, (user_id, role, display_name, class_code, datetime.utcnow().isoformat()))
    c.commit()

def log_attempt(c: sqlite3.Connection, user_id: str, class_code: str, item: Dict[str, Any], correct: bool, response: Dict[str, Any], mode: str):
    c.execute("""
    INSERT INTO attempts(user_id, class_code, item_id, field_id, domain_id, difficulty, correct, response_json, created_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        user_id,
        class_code,
        item["id"],
        item["field"],
        item["domain"],
        int(item.get("difficulty", 1)),
        int(bool(correct)),
        json.dumps({"mode": mode, **response}, ensure_ascii=False),
        datetime.utcnow().isoformat()
    ))
    c.commit()

def load_items(c: sqlite3.Connection) -> List[Dict[str, Any]]:
    df = pd.read_sql_query("SELECT payload_json FROM items", c)
    return [json.loads(x) for x in df["payload_json"].tolist()]

def get_attempts(c: sqlite3.Connection, user_id: Optional[str]=None, class_code: Optional[str]=None) -> pd.DataFrame:
    q = "SELECT * FROM attempts"
    params=[]
    conds=[]
    if user_id:
        conds.append("user_id=?"); params.append(user_id)
    if class_code:
        conds.append("class_code=?"); params.append(class_code)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY attempt_id DESC"
    return pd.read_sql_query(q, c, params=params)

def get_users(c: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM users ORDER BY created_at DESC", c)

def save_material(c: sqlite3.Connection, uploader_user_id: str, class_code: str, title: str, description: str,
                  field_id: Optional[str], topic: Optional[str], file_obj):
    data = file_obj.getvalue()
    c.execute("""
    INSERT INTO materials(uploader_user_id, class_code, title, description, field_id, topic, mime, filename, content, created_at)
    VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        uploader_user_id, class_code, title, description,
        field_id, topic,
        file_obj.type, file_obj.name, sqlite3.Binary(data),
        datetime.utcnow().isoformat()
    ))
    c.commit()

def get_materials(c: sqlite3.Connection, class_code: str, field_id: Optional[str]=None) -> pd.DataFrame:
    q = "SELECT material_id, title, description, field_id, topic, mime, filename, created_at FROM materials WHERE class_code=?"
    params=[class_code]
    if field_id:
        q += " AND (field_id=? OR field_id IS NULL)"
        params.append(field_id)
    q += " ORDER BY material_id DESC"
    return pd.read_sql_query(q, c, params=params)

def get_material_blob(c: sqlite3.Connection, material_id: int):
    return c.execute("SELECT mime, filename, content FROM materials WHERE material_id=?", (material_id,)).fetchone()

# =========================
# Analytics
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
    out = {}
    for key, v in agg.items():
        acc = v["c"] / max(v["w"], 1e-9)
        lvl = 1 if acc < 0.45 else (2 if acc < 0.75 else 3)
        out[key] = {"accuracy": round(acc, 2), "level": lvl, "n": int(v["n"])}
    return out

def weakest_areas(attempts_df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    if attempts_df.empty:
        return pd.DataFrame(columns=["field_id","domain_id","accuracy","attempts","level"])
    prof = compute_profile(attempts_df)
    rows=[]
    for (f,d), v in prof.items():
        rows.append({"field_id": f, "domain_id": d, "accuracy": v["accuracy"], "attempts": v["n"], "level": v["level"]})
    df = pd.DataFrame(rows)
    return df.sort_values(["accuracy","attempts"], ascending=[True, False]).head(top_n)

def recommend_support(field_id: str, domain_id: str, level: int) -> List[str]:
    rec=[]
    if domain_id == "FACH":
        rec += [
            "Kurz wiederholen: Definition → typische Warnzeichen → was du beobachtest → was du meldest.",
            "Mit Fallbeispielen üben (Situation → erste sichere Handlung → Dokumentation).",
            "Merksätze/Checklisten nutzen (Beobachtung: WAS? WIE? WANN? WO?).",
        ]
        if level == 1:
            rec += ["Basis: sehr kurze Aufgaben (Lücke/Zuordnen) → dann Fall-Quiz."]
        elif level == 2:
            rec += ["Aufbau: gemischte Fälle, typische Fehler bewusst besprechen."]
        else:
            rec += ["Prüfungsnah: komplexere Fälle, Transferfragen, Prioritäten setzen."]
    elif domain_id == "SPR":
        rec += ["Einfache Sprache: kurze Sätze, ein Schritt pro Satz, Nachfragen ermöglichen.",
                "Wortschatzkarten: Fachwörter + einfache Erklärung.",
                "Dokumentieren üben: objektiv, ohne Bewertung."]
    elif domain_id == "KOG":
        rec += ["Abläufe als Kärtchen/Reihenfolgen legen, dann in eigenen Worten erklären.",
                "Wenn-dann-Regeln: Warnzeichen → melden.",
                "Mini-Checklisten (Was zuerst?)."]
    else:
        rec += ["Operatoren kurz klären (nennen/beschreiben/erklären) und sofort mit Fachwissen verknüpfen."]
    return rec[:6]

# =========================
# Item selection
# =========================
def pick_items(items: List[Dict[str, Any]], field_id: str, domain_id: str, n: int) -> List[Dict[str, Any]]:
    cand = [it for it in items if it.get("field") == field_id and it.get("domain") == domain_id]
    if not cand:
        return []
    return random.sample(cand, k=min(n, len(cand)))

def pick_adaptive(items: List[Dict[str, Any]], profile: Dict[Tuple[str,str], Dict[str,Any]], field_id: str, seen: set, k: int) -> List[Dict[str, Any]]:
    dom_levels = {dom: profile.get((field_id, dom), {}).get("level", 1) for dom,_ in DOMAINS}
    dom_plan=[]
    for dom,_ in DOMAINS:
        lvl = dom_levels.get(dom, 1)
        w = max(1, 4 - min(3, lvl))
        if dom == "FACH":
            w += 2
        dom_plan.extend([dom]*w)

    picked=[]
    tries=0
    while len(picked) < k and tries < k*25:
        tries += 1
        dom = random.choice(dom_plan)
        target = dom_levels.get(dom, 1)
        pool=[]
        for it in items:
            if it.get("field") != field_id or it.get("domain") != dom:
                continue
            dist = abs(int(it.get("difficulty",1)) - int(target))
            penalty = 0.6 if it.get("id") in seen else 0.0
            pool.append((dist + penalty + random.random()*0.2, it))
        pool.sort(key=lambda x: x[0])
        if pool:
            it = pool[0][1]
            picked.append(it)
            seen.add(it["id"])
    return picked

# =========================
# UI helpers
# =========================
def card(title: str, body: str):
    st.markdown(f"""
    <div style="padding:14px;border-radius:16px;border:1px solid rgba(0,0,0,.12);margin-bottom:10px;background:rgba(255,255,255,.03);">
      <div style="font-size:18px;font-weight:700;margin-bottom:4px;">{title}</div>
      <div style="opacity:.88;line-height:1.35;">{body}</div>
    </div>
    """, unsafe_allow_html=True)

def badge(item: Dict[str, Any]):
    label = TYPE_LABEL.get(item.get("type","").lower().strip(), "Aufgabe")
    dom = domain_name.get(item.get("domain",""), item.get("domain",""))
    stars = "⭐" * int(item.get("difficulty",1))
    st.caption(f"{label} · {dom} · {stars}")

def render_item(item: Dict[str, Any], easy_mode: bool, key_prefix: str) -> Optional[Dict[str, Any]]:
    screen = f"{key_prefix}{item.get('id','')}_{st.session_state.get('flow_i',0)}_{st.session_state.get('flow_mode','')}"
    form_key = f"form_{screen}"

    badge(item)
    prompt = item.get("prompt_easy") if easy_mode and item.get("prompt_easy") else item.get("prompt","")
    st.write(prompt)

    t = item.get("type","").lower().strip()

    def select_with_placeholder(label, options, key):
        opts = ["— bitte wählen —"] + list(options)
        choice = st.selectbox(label, opts, index=0, key=key)
        return None if choice == "— bitte wählen —" else choice

    with st.form(key=form_key, clear_on_submit=False):
        response = {}
        if t in ("mcq","case","pattern"):
            choice = select_with_placeholder("Antwort:", item["options"], key=f"{screen}_mcq")
            response = {"choice": choice}
        elif t == "cloze":
            choice = select_with_placeholder("Wort:", item["options"], key=f"{screen}_cloze")
            response = {"choice": choice}
        elif t == "order":
            steps = list(item["steps"])
            st.caption("Reihenfolge: Wähle Position 1 → 2 → 3 → …")
            chosen_steps=[]
            for pos in range(len(steps)):
                ch = select_with_placeholder(f"Position {pos+1}", steps, key=f"{screen}_pos_{pos}")
                chosen_steps.append(ch)
            response = {"order_steps": chosen_steps}
        elif t == "match":
            st.caption("Ordne zu:")
            right = [r for _, r in item["pairs"]]
            resp = {}
            for idx, (left, _right) in enumerate(item["pairs"]):
                resp[left] = select_with_placeholder(left, right, key=f"{screen}_match_{idx}")
            response = resp
        else:
            answer = st.text_area("Deine Antwort:", key=f"{screen}_short")
            response = {"text": answer}

        submitted = st.form_submit_button("Weiter")

    if not submitted:
        return None

    if t in ("mcq","case","pattern"):
        choice = response.get("choice")
        if choice is None:
            st.warning("Bitte wähle eine Option.")
            return None
        correct = (item["options"].index(choice) == item["answer"])
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
        if item.get("rationale") and not correct:
            st.info(item["rationale"])
        return {"correct": correct, "response": response}

    if t == "cloze":
        choice = response.get("choice")
        if choice is None:
            st.warning("Bitte wähle ein Wort.")
            return None
        correct = (item["options"].index(choice) == item["answer"])
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
        return {"correct": correct, "response": response}

    if t == "order":
        chosen_steps = response.get("order_steps", [])
        if any(c is None for c in chosen_steps):
            st.warning("Bitte fülle alle Positionen aus.")
            return None
        if len(set(chosen_steps)) != len(chosen_steps):
            st.warning("Jeder Schritt darf nur einmal vorkommen.")
            return None
        steps = list(item["steps"])
        idx = [steps.index(s) for s in chosen_steps]
        correct = (idx == item["correct_order"])
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
        return {"correct": correct, "response": {"order_steps": chosen_steps, "order_idx": idx}}

    if t == "match":
        if any(v is None for v in response.values()):
            st.warning("Bitte ordne alle Begriffe zu.")
            return None
        correct = True
        for left, rightv in item["pairs"]:
            if response.get(left) != rightv:
                correct = False
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
        return {"correct": correct, "response": response}

    text = (response.get("text") or "").lower()
    kws = item.get("keywords", [])
    hits = sum(1 for kw in kws if kw.lower() in text)
    correct = hits >= max(1, len(kws)//4) if kws else (len(text.strip()) > 10)
    st.success("Gespeichert ✅")
    return {"correct": correct, "response": {"text": response.get("text"), "hits": hits}}

# =========================
# App
# =========================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

ci = conn_items()
cd = conn_data()
ensure_data_tables(cd)

items = load_items(ci)

with st.sidebar:
    st.header("Start")
    role_ui = st.selectbox("Rolle", ["Schüler:in", "Lehrkraft"])
    role = "student" if role_ui == "Schüler:in" else "teacher"
    user_id = st.text_input("Kürzel (ohne Klarnamen)", value="demo_schueler" if role=="student" else "demo_lehrkraft")
    display_name = st.text_input("Name (optional)", value="")
    class_code = st.text_input("Klasse/Kurs", value="GPA-TEST")
    easy_mode = st.toggle("Einfache Sprache", value=False)

upsert_user(cd, user_id, role, display_name, class_code)

tabs = st.tabs(["Schüler:in", "Lehrkraft"])

with tabs[0]:
    st.subheader("Schülerbereich")
    st.markdown("### 1) Lernfeld auswählen")
    field_id = st.selectbox("Lernfeld:", [x for x,_ in LEARN_FIELDS], format_func=lambda x: f"{x} – {lf_name.get(x,x)}")
    card(f"{field_id} – {lf_name.get(field_id, field_id)}",
         "Starte zuerst eine kurze Diagnostik (Fachwissen) und übe danach mit passenden Aufgaben.")

    mats = get_materials(cd, class_code=class_code, field_id=field_id)
    if not mats.empty:
        with st.expander("Material von der Lehrkraft (zum Lernfeld)"):
            for _, r in mats.iterrows():
                st.write(f"**{r['title']}**")
                if str(r.get("description") or "").strip():
                    st.caption(r["description"])
                blob = get_material_blob(cd, int(r["material_id"]))
                if blob:
                    mime, filename, content = blob
                    st.download_button("Download", data=content, file_name=filename, mime=mime, key=f"dl_{r['material_id']}")

    attempts = get_attempts(cd, user_id=user_id)
    profile = compute_profile(attempts)
    rows=[]
    for dom,_ in DOMAINS:
        v = profile.get((field_id, dom), {"level":1,"accuracy":0.0,"n":0})
        rows.append({"Bereich": domain_name.get(dom, dom), "Level": v["level"], "Trefferquote": v["accuracy"], "Aufgaben": v["n"]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("### 2) Diagnostik (je Bereich)")
    per_domain = st.slider("Aufgaben pro Bereich", 3, 10, 5, 1)

    cols = st.columns(4)
    for i,(dom,label) in enumerate(DOMAINS):
        with cols[i]:
            st.markdown(f"**{label}**")
            if st.button("Start", key=f"start_{dom}"):
                chosen = pick_items(items, field_id, dom, per_domain)
                st.session_state["flow_items"] = chosen
                st.session_state["flow_i"] = 0
                st.session_state["flow_mode"] = f"diag_{dom}"
                st.session_state["flow_field"] = field_id
                st.session_state["flow_dom"] = dom
                st.rerun()

    flow_items = st.session_state.get("flow_items", [])
    if flow_items and st.session_state.get("flow_field") == field_id:
        i = st.session_state.get("flow_i", 0)
        st.markdown("---")
        st.markdown(f"### Aufgabe {i+1}/{len(flow_items)}")
        st.progress((i+1)/len(flow_items))
        it = flow_items[i]
        res = render_item(it, easy_mode, key_prefix=f"flow_{st.session_state.get('flow_mode')}_")
        if res is not None:
            log_attempt(cd, user_id, class_code, it, res["correct"], res["response"], mode=st.session_state.get("flow_mode","diag"))
            if i+1 < len(flow_items):
                st.session_state["flow_i"] = i+1
                st.rerun()
            else:
                st.success("Fertig ✅")
                st.session_state["flow_items"] = []
                st.session_state["flow_i"] = 0
                st.session_state["flow_mode"] = None
                st.session_state["flow_field"] = None
                st.session_state["flow_dom"] = None
                st.rerun()

    st.markdown("### 3) Üben (angepasst)")
    k = st.slider("Übungsrunde", 5, 15, 8, 1)
    if st.button("Übung starten"):
        attempts2 = get_attempts(cd, user_id=user_id)
        prof2 = compute_profile(attempts2)
        seen = set(attempts2["item_id"].tolist()) if not attempts2.empty else set()
        chosen = pick_adaptive(items, prof2, field_id, seen, k)
        st.session_state["flow_items"] = chosen
        st.session_state["flow_i"] = 0
        st.session_state["flow_mode"] = "practice"
        st.session_state["flow_field"] = field_id
        st.session_state["flow_dom"] = None
        st.rerun()

with tabs[1]:
    st.subheader("Lehrkraft-Dashboard")

    users = get_users(cd)
    class_options = sorted([c for c in users["class_code"].dropna().unique().tolist() if c])
    chosen_class = st.selectbox("Klasse/Kurs", class_options if class_options else [class_code])

    class_users = users[(users["class_code"] == chosen_class) & (users["role"] == "student")]
    class_attempts = get_attempts(cd, class_code=chosen_class)

    c1, c2, c3 = st.columns(3)
    c1.metric("Schüler:innen", int(len(class_users)))
    c2.metric("Versuche", int(len(class_attempts)))
    c3.metric("Aufgabenbank", len(items))

    st.markdown("### 1) Übersicht: Wo liegen die größten Schwierigkeiten?")
    if class_attempts.empty:
        st.info("Noch keine Daten. Schüler:innen müssen erst Diagnostik/Übung bearbeiten.")
    else:
        wa = weakest_areas(class_attempts, top_n=8)
        if not wa.empty:
            wa_show = wa.copy()
            wa_show["Lernfeld"] = wa_show["field_id"].apply(lambda x: f"{x} – {lf_name.get(x,x)}")
            wa_show["Bereich"] = wa_show["domain_id"].apply(lambda x: domain_name.get(x,x))
            st.dataframe(wa_show[["Lernfeld","Bereich","accuracy","attempts","level"]], use_container_width=True, hide_index=True)

    st.markdown("### 2) Einzelanalyse: Fehler & Förderung pro Schüler:in")
    if class_users.empty:
        st.info("Noch keine Schüler:innen in dieser Klasse.")
    else:
        sid = st.selectbox("Schüler:in (Kürzel)", class_users["user_id"].tolist())
        s_attempts = get_attempts(cd, user_id=sid)
        s_prof = compute_profile(s_attempts)

        rows=[]
        for lf,_ in LEARN_FIELDS:
            for dom,_ in DOMAINS:
                v = s_prof.get((lf, dom), {"level":1,"accuracy":0.0,"n":0})
                rows.append({
                    "Lernfeld": f"{lf} – {lf_name.get(lf,lf)}",
                    "Bereich": domain_name.get(dom,dom),
                    "Level": v["level"],
                    "Trefferquote": v["accuracy"],
                    "Aufgaben": v["n"],
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("**Förder-Schwerpunkte (Top 5)**")
        wa_s = weakest_areas(s_attempts, top_n=5)
        if wa_s.empty:
            st.caption("Noch nicht genug Daten.")
        else:
            for _, r in wa_s.iterrows():
                lf = r["field_id"]; dom = r["domain_id"]; lvl = int(r["level"])
                st.markdown(f"- **{lf} – {lf_name.get(lf,lf)} / {domain_name.get(dom,dom)}** · Level {lvl} · Trefferquote {r['accuracy']}")
                for rec in recommend_support(lf, dom, lvl):
                    st.caption(f"• {rec}")

        st.markdown("**Konkrete Fehler (letzte 10 falsche Antworten)**")
        wrong = s_attempts[s_attempts["correct"] == 0].head(10)
        if wrong.empty:
            st.caption("Keine falschen Antworten gespeichert (oder noch keine Aufgaben).")
        else:
            item_map = {it["id"]: it for it in items}
            for _, row in wrong.iterrows():
                it = item_map.get(row["item_id"])
                if not it:
                    continue
                with st.expander(f"{row['field_id']} · {domain_name.get(row['domain_id'], row['domain_id'])} · Item {row['item_id']}"):
                    st.write(it.get("prompt",""))
                    t = it.get("type","").lower().strip()
                    if t in ("mcq","case","pattern","cloze") and "options" in it:
                        st.write("**Lösung:**")
                        for j,opt in enumerate(it["options"]):
                            mark = "✅" if j == it.get("answer") else ""
                            st.write(f"- {opt} {mark}")
                    if it.get("rationale"):
                        st.info(it["rationale"])

    st.markdown("### 3) Eigenes Material hochladen (für Schüler:innen)")
    st.caption("Nur eigenes / frei nutzbares Material hochladen. Keine Klarnamen in Dateinamen.")
    m_title = st.text_input("Titel", value="", key="m_title")
    m_desc = st.text_area("Kurzbeschreibung", value="", height=80, key="m_desc")
    m_field = st.selectbox("Zu Lernfeld (optional)", ["(alle)"] + [x for x,_ in LEARN_FIELDS],
                           format_func=lambda x: "(alle)" if x=="(alle)" else f"{x} – {lf_name.get(x,x)}", key="m_field")
    m_topic = st.text_input("Thema/Tag (optional)", value="", key="m_topic")
    file_obj = st.file_uploader("Datei hochladen (PDF, DOCX, PPTX, Bilder, …)", type=None, key="m_file")

    if st.button("Material speichern", key="m_save"):
        if not m_title.strip():
            st.warning("Bitte Titel angeben.")
        elif file_obj is None:
            st.warning("Bitte eine Datei auswählen.")
        else:
            fid = None if m_field == "(alle)" else m_field
            save_material(cd, uploader_user_id=user_id, class_code=chosen_class, title=m_title.strip(), description=m_desc.strip(),
                          field_id=fid, topic=(m_topic.strip() or None), file_obj=file_obj)
            st.success("Gespeichert ✅")

    mats = get_materials(cd, class_code=chosen_class, field_id=None)
    if not mats.empty:
        with st.expander("Materialübersicht (Klasse)"):
            st.dataframe(mats, use_container_width=True, hide_index=True)
            mid = st.number_input("Material-ID", min_value=0, step=1, value=0, key="m_mid")
            if st.button("Download Material-ID", key="m_dl"):
                if int(mid) > 0:
                    blob = get_material_blob(cd, int(mid))
                    if blob:
                        mime, filename, content = blob
                        st.download_button("Download starten", data=content, file_name=filename, mime=mime, key=f"dl_teacher_{mid}")
                    else:
                        st.warning("ID nicht gefunden.")

st.caption("Prototyp. Für echten Betrieb: Datenschutz, Rollen, Hosting, Backups, Rechtekonzept.")
