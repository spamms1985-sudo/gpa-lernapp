import sqlite3
import json
import random
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st

# =========================
# Config / Paths
# =========================
DB_ITEMS_PATH = "gpa_items_fachwissen_v1.db"   # must exist in repo
DB_DATA_PATH  = "gpa_app_data.db"              # created automatically (prototype storage)

APP_TITLE = "GPA Lernapp"
APP_SUBTITLE = "1) Basis-Diagnostik → 2) Lernfeld-Diagnostik → 3) Üben · Lehrkraft: Übersicht, Fehleranalyse, Förderung, Material"

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
lf_name = dict(LEARN_FIELDS)

# Domains: GLOBAL first, then LF-specific Fachkompetenz
GLOBAL_DOMAINS = [
    ("SPR","Sprache"),
    ("KOG","Kognitive Basis"),
    ("META","Meta-Kompetenzen"),
    ("MOT","Motivation & Lernen"),
]
LF_DOMAINS = [
    ("FACH","Fachwissen"),
]
ALL_DOMAINS = GLOBAL_DOMAINS + LF_DOMAINS

domain_name = dict(ALL_DOMAINS)

TYPE_LABEL = {
    "mcq": "Quiz",
    "case": "Fall",
    "cloze": "Lücke",
    "match": "Zuordnen",
    "order": "Reihenfolge",
    "short": "Kurzantwort",
    "scale": "Skala",
}

# -------------------------
# GLOBAL diagnostic items (in-code, not from book)
# -------------------------
def global_items() -> List[Dict[str, Any]]:
    G="GLOBAL"
    items=[]
    def add(dom, t, prompt, **kw):
        items.append({"id": f"{dom}_{len(items)+1:04d}", "field": G, "domain": dom, "difficulty": 1, "type": t, "topic": dom, "prompt": prompt, **kw})
    # SPR
    add("SPR","mcq","Welcher Satz ist am klarsten und am besten verständlich?",
        options=[
            "Bitte setzen Sie sich jetzt hin. Ich helfe Ihnen gleich.",
            "Es wäre opportun, sich zeitnah zu positionieren, um die Maßnahme zu initiieren.",
            "Wir werden perspektivisch eine Sitzgelegenheit evaluieren.",
            "Sitz, jetzt, sofort, sonst."
        ], answer=0, rationale="Kurze, klare Sätze ohne schwierige Wörter.")
    add("SPR","cloze","Dokumentation soll ________ sein (ohne Bewertung).",
        options=["objektiv","laut","witzig","ungefähr"], answer=0)
    add("SPR","short","Formuliere in 2 Sätzen in einfacher Sprache: Was machst du als Nächstes in der Körperpflege?",
        keywords=["ich","helfe","waschen","jetzt","bitte","sagen"])
    # KOG
    add("KOG","order","Bringe die Schritte in eine sinnvolle Reihenfolge: Du bemerkst ein Warnzeichen.",
        steps=["Sicherheit herstellen","Beobachtung konkret beschreiben","Dokumentieren","Melden/Übergabe"],
        correct_order=[0,1,2,3])
    add("KOG","mcq","Was bedeutet 'Priorität setzen' im Pflegealltag am ehesten?",
        options=[
            "Zuerst das tun, was sicherheitsrelevant ist.",
            "Alles gleichzeitig beginnen.",
            "Immer zuerst die einfachste Aufgabe.",
            "Nur das tun, was Spaß macht."
        ], answer=0)
    add("KOG","short","Du hast 3 Aufgaben: a) Sturzgefahr beseitigen, b) Bett machen, c) Wasser auffüllen. Welche zuerst – und warum?",
        keywords=["sturz","sicherheit","zuerst","weil"])
    # META (Selbstregulation / Lernen)
    add("META","mcq","Welche Strategie hilft am besten, wenn du beim Lernen nicht weiterkommst?",
        options=[
            "Kurz Pause, dann Aufgabe in Teilschritte zerlegen.",
            "Sofort aufgeben.",
            "Alles komplett neu anfangen ohne Plan.",
            "Nur noch Videos schauen und nichts notieren."
        ], answer=0)
    add("META","mcq","Welche Aussage beschreibt eine gute Lernplanung?",
        options=[
            "Ich plane kleine Einheiten und überprüfe mich danach kurz.",
            "Ich lerne nur am Abend vor der Prüfung.",
            "Ich mache keine Wiederholungen.",
            "Ich lerne immer irgendwas, aber ohne Ziel."
        ], answer=0)
    add("META","scale","Wie sicher fühlst du dich beim selbstständigen Lernen? (1=gar nicht, 5=sehr)", min=1, max=5)
    # MOT
    add("MOT","scale","Wie motiviert bist du aktuell, für die GPA-Prüfung zu üben? (1=gar nicht, 5=sehr)", min=1, max=5)
    add("MOT","mcq","Was hilft dir am ehesten, dranzubleiben?",
        options=[
            "Kleine Ziele + sichtbarer Fortschritt.",
            "Sehr schwere Aufgaben ohne Rückmeldung.",
            "Nur lange Lernsessions (2–3 Stunden).",
            "Ohne Pausen lernen."
        ], answer=0)
    add("MOT","short","Was wäre ein realistisches Lernziel für diese Woche? (1–2 Sätze)",
        keywords=["ich","werde","diese","woche"])
    return items

GLOBAL_ITEMS = global_items()

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
    c.execute("""CREATE TABLE IF NOT EXISTS topic_texts(
        field_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        level INTEGER NOT NULL,
        text TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(field_id, topic, level)
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

def get_topic_text(c: sqlite3.Connection, field_id: str, topic: str, level: int) -> Optional[str]:
    row = c.execute(
        "SELECT text FROM topic_texts WHERE field_id=? AND topic=? AND level=?",
        (field_id, topic, int(level))
    ).fetchone()
    return row[0] if row else None

def upsert_topic_text(c: sqlite3.Connection, field_id: str, topic: str, level: int, text: str):
    c.execute("""
    INSERT INTO topic_texts(field_id, topic, level, text, updated_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(field_id, topic, level) DO UPDATE SET
        text=excluded.text,
        updated_at=excluded.updated_at
    """, (field_id, topic, int(level), text, datetime.utcnow().isoformat()))
    c.commit()

def list_topics(c_items: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT payload_json FROM items", c_items)
    items = [json.loads(x) for x in df["payload_json"].tolist()]
    rows=[]
    for it in items:
        f=it.get("field"); tp=(it.get("topic") or "").strip()
        if f and tp:
            rows.append({"field_id": f, "topic": tp, "type": (it.get("type") or "").strip()})
    d=pd.DataFrame(rows)
    if d.empty:
        return d
    return d.groupby(["field_id","topic"]).agg(
        items=("topic","count"),
        types=("type", lambda s: ", ".join(sorted(set([x for x in s if x]))))
    ).reset_index().sort_values(["field_id","topic"])

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

def student_overview(users_df: pd.DataFrame, attempts_df: pd.DataFrame) -> pd.DataFrame:
    if users_df.empty:
        return pd.DataFrame()
    if attempts_df.empty:
        out = users_df.copy()
        out["attempts_total"] = 0
        out["accuracy"] = None
        out["last_activity"] = None
        out["fields_started"] = 0
        out["learnfields"] = ""
        out["global_done"] = False
        return out[["user_id","display_name","class_code","attempts_total","accuracy","last_activity","fields_started","learnfields","global_done"]]

    a = attempts_df.copy()
    a["created_at"] = pd.to_datetime(a["created_at"], errors="coerce")

    g = a.groupby("user_id").agg(
        attempts_total=("attempt_id","count"),
        correct_total=("correct","sum"),
        last_activity=("created_at","max"),
        fields_started=("field_id", lambda s: len(set([x for x in s if x != "GLOBAL"]))),
    ).reset_index()
    g["accuracy"] = (g["correct_total"] / g["attempts_total"]).round(2)

    lf_list = a[a["field_id"] != "GLOBAL"].groupby("user_id")["field_id"].apply(lambda s: ", ".join(sorted(set(s)))).reset_index(name="learnfields")
    glob = a[a["field_id"] == "GLOBAL"].groupby("user_id")["attempt_id"].count().reset_index(name="global_attempts")
    glob["global_done"] = glob["global_attempts"] >= 8  # approx full global check

    out = users_df.merge(g, on="user_id", how="left").merge(lf_list, on="user_id", how="left").merge(glob[["user_id","global_done"]], on="user_id", how="left")
    out["attempts_total"] = out["attempts_total"].fillna(0).astype(int)
    out["accuracy"] = out["accuracy"].astype("float")
    out["fields_started"] = out["fields_started"].fillna(0).astype(int)
    out["last_activity"] = pd.to_datetime(out["last_activity"], errors="coerce")
    out["display_name"] = out["display_name"].fillna("")
    out["learnfields"] = out["learnfields"].fillna("")
    out["global_done"] = out["global_done"].fillna(False)
    return out[["user_id","display_name","class_code","attempts_total","accuracy","last_activity","fields_started","learnfields","global_done"]]

def weakest_areas(attempts_df: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
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
    if field_id == "GLOBAL":
        if domain_id == "SPR":
            rec += ["Kurze Sätze, 1 Schritt pro Satz, wichtige Wörter wiederholen.",
                    "Fachwort + einfache Erklärung (Karteikarten).",
                    "Dokumentation: 'Was genau?' statt Bewertung."]
        elif domain_id == "KOG":
            rec += ["Abläufe als 4-Schritte-Checkliste (Sicherheit→Beobachten→Dokumentieren→Melden).",
                    "Prioritäten: Sicherheit zuerst."]
        elif domain_id == "META":
            rec += ["Lernen in 10–15 Minuten-Blöcken, danach Mini-Test.",
                    "Teilschritte & Häkchenliste statt 'alles auf einmal'."]
        else:
            rec += ["Ziel klein machen (5–10 Min/Tag), Fortschritt sichtbar (Streak/Checkliste)."]
        return rec
    # LF recommendations
    if domain_id == "FACH":
        rec += [
            "Kurz wiederholen: Definition → Warnzeichen → Beobachtung → Meldeweg.",
            "Mit Fallbeispielen üben (erste sichere Handlung + Dokumentation).",
            "Typische Fehler besprechen (Distraktoren).",
        ]
        if level == 1:
            rec += ["Basis: Lücke/Zuordnung → kurze Fälle."]
        elif level == 2:
            rec += ["Aufbau: gemischte Fälle, Prioritäten."]
        else:
            rec += ["Prüfungsnah: komplexe Fälle, Transfer."]
    return rec[:6]


def infer_language_level(profile: Dict[Tuple[str,str], Dict[str,Any]], easy_mode: bool) -> int:
    """Returns 1 (einfach/A2), 2 (standard/B1), 3 (prüfungsnah/B2)."""
    if easy_mode:
        return 1
    v = profile.get(("GLOBAL","SPR"), {})
    lvl = int(v.get("level", 2) or 2)
    return max(1, min(3, lvl))

def language_label(level: int) -> str:
    return {1:"einfach", 2:"standard", 3:"prüfungsnah"}.get(level, "standard")

def generate_topic_intro(field_id: str, topic: str, level: int) -> str:
    """Dynamic intro text (template-based). Replace later with curated book-based snippets if desired."""
    if level == 1:
        return (
            f"**Thema: {topic}**\n\n"
            "Du lernst die wichtigsten Wörter und Schritte.\n"
            "Achte auf: **Was beobachte ich? Was mache ich zuerst? Wen informiere ich?**\n\n"
            "Merke:\n"
            "- Sicherheit geht vor.\n"
            "- Beobachte konkret (was, wie, wann).\n"
            "- Dokumentiere kurz und objektiv.\n"
        )
    if level == 2:
        return (
            f"**Thema: {topic}**\n\n"
            "Du übst Fachwissen und Entscheidungen im Alltag.\n"
            "Fokus: **Warnzeichen erkennen**, **Prioritäten setzen**, **Meldeweg/Übergabe** und **Dokumentation**.\n\n"
            "Merke:\n"
            "- Erst Sicherheit, dann Maßnahmen.\n"
            "- Beobachtung + Begründung trennen.\n"
            "- Übergabe: klar, kurz, vollständig.\n"
        )
    return (
        f"**Thema: {topic}**\n\n"
        "Prüfungsnah: Du verbindest Fachwissen mit Fällen.\n"
        "Achte auf **Begründungen**, **Abwägungen** und **professionelle Kommunikation**.\n\n"
        "Merke:\n"
        "- Warnzeichen/Risiken strukturiert benennen.\n"
        "- Handlungsplan + Dokumentation/Übergabe.\n"
        "- Grenzen kennen: Wann muss ich eskalieren?\n"
    )

def pick_topic_for_practice(items: List[Dict[str, Any]], attempts_df: pd.DataFrame, field_id: str) -> str:
    """Choose a topic to practice. Prefer weakest topic from past attempts; otherwise random."""
    cand = [it.get("topic","") for it in items if it.get("field")==field_id and it.get("domain")=="FACH" and it.get("topic")]
    cand = sorted(set([c for c in cand if str(c).strip()]))
    if not cand:
        return "Allgemein"
    if attempts_df.empty:
        return random.choice(cand)
    a = attempts_df[attempts_df["field_id"]==field_id].copy()
    if a.empty:
        return random.choice(cand)
    item_map = {it["id"]: it for it in items if it.get("field")==field_id}
    rows=[]
    for _, r in a.iterrows():
        it = item_map.get(r["item_id"])
        if not it:
            continue
        tp = it.get("topic") or ""
        if not tp:
            continue
        rows.append({"topic": tp, "correct": int(r["correct"])})
    if not rows:
        return random.choice(cand)
    df = pd.DataFrame(rows).groupby("topic").agg(acc=("correct","mean"), n=("correct","count")).reset_index()
    df = df.sort_values(["acc","n"], ascending=[True, False])
    weakest = df.iloc[0]["topic"]
    return weakest if weakest in cand else random.choice(cand)

def pick_practice_sequence(items: List[Dict[str, Any]], profile: Dict[Tuple[str,str], Dict[str,Any]], attempts_df: pd.DataFrame,
                           field_id: str, topic: str, k: int) -> List[Dict[str, Any]]:
    """Pick a mixed sequence for a topic and end with a case item if available."""
    seen = set(attempts_df["item_id"].tolist()) if not attempts_df.empty else set()

    pool = [it for it in items if it.get("field")==field_id and it.get("domain")=="FACH" and (it.get("topic")==topic)]
    if not pool:
        pool = [it for it in items if it.get("field")==field_id and it.get("domain")=="FACH"]
    if not pool:
        return []

    target = profile.get((field_id, "FACH"), {}).get("level", 1)
    target = max(1, min(3, int(target)))

    cases = [it for it in pool if it.get("type","").lower().strip() == "case"]
    non_cases = [it for it in pool if it not in cases]

    def score(it):
        dist = abs(int(it.get("difficulty",1)) - target)
        penalty = 0.6 if it.get("id") in seen else 0.0
        return dist + penalty + random.random()*0.2

    non_cases = sorted(non_cases, key=score)

    picked=[]
    used_types=set()
    need = max(1, k-1)
    for it in non_cases:
        if len(picked) >= need:
            break
        t = it.get("type","").lower().strip()
        if t in used_types and len(used_types) < 4:
            continue
        picked.append(it); used_types.add(t); seen.add(it["id"])

    if len(picked) < need:
        for it in non_cases:
            if len(picked) >= need:
                break
            if it in picked:
                continue
            picked.append(it); seen.add(it["id"])

    last = None
    if cases:
        last = sorted(cases, key=score)[0]
    else:
        rest = [it for it in pool if it not in picked]
        if rest:
            last = sorted(rest, key=lambda it: (-(int(it.get("difficulty",1))), score(it)))[0]

    if last:
        picked = picked[:need] + [last]
    return picked[:k]

# =========================
# Selection
# =========================
def pick_global(dom: str, n: int) -> List[Dict[str, Any]]:
    cand=[it for it in GLOBAL_ITEMS if it["domain"]==dom]
    return random.sample(cand, k=min(n, len(cand)))

def pick_lf(items: List[Dict[str, Any]], field_id: str, n: int) -> List[Dict[str, Any]]:
    cand=[it for it in items if it.get("field")==field_id and it.get("domain")=="FACH"]
    return random.sample(cand, k=min(n, len(cand))) if cand else []

def pick_adaptive(items: List[Dict[str, Any]], profile: Dict[Tuple[str,str], Dict[str,Any]], field_id: str, seen: set, k: int) -> List[Dict[str, Any]]:
    target = profile.get((field_id, "FACH"), {}).get("level", 1)
    pool=[]
    for it in items:
        if it.get("field")!=field_id or it.get("domain")!="FACH":
            continue
        dist=abs(int(it.get("difficulty",1)) - int(target))
        penalty=0.6 if it.get("id") in seen else 0.0
        pool.append((dist+penalty+random.random()*0.2, it))
    pool.sort(key=lambda x:x[0])
    chosen=[it for _,it in pool[:k]]
    return chosen

# =========================
# Rendering (stable forms)
# =========================
def badge(item: Dict[str, Any]):
    label = TYPE_LABEL.get(item.get("type","").lower().strip(), "Aufgabe")
    dom = domain_name.get(item.get("domain",""), item.get("domain",""))
    stars = "⭐" * int(item.get("difficulty",1))
    st.caption(f"{label} · {dom} · {stars}")

def render_item(item: Dict[str, Any], key_prefix: str, easy_mode: bool=False) -> Optional[Dict[str, Any]]:
    screen = f"{key_prefix}{item.get('id','')}_{st.session_state.get('flow_i',0)}_{st.session_state.get('flow_mode','')}"
    form_key = f"form_{screen}"

    badge(item)
    st.write(item.get("prompt",""))
    t=item.get("type","").lower().strip()

    def select_with_placeholder(label, options, key):
        opts=["— bitte wählen —"] + list(options)
        choice = st.selectbox(label, opts, index=0, key=key)
        return None if choice=="— bitte wählen —" else choice

    with st.form(key=form_key, clear_on_submit=False):
        response={}
        if t in ("mcq","case","pattern"):
            choice=select_with_placeholder("Antwort:", item["options"], key=f"{screen}_mcq")
            response={"choice": choice}
        elif t=="cloze":
            choice=select_with_placeholder("Wort:", item["options"], key=f"{screen}_cloze")
            response={"choice": choice}
        elif t=="order":
            steps=list(item["steps"])
            chosen=[]
            for pos in range(len(steps)):
                ch=select_with_placeholder(f"Position {pos+1}", steps, key=f"{screen}_pos_{pos}")
                chosen.append(ch)
            response={"order_steps": chosen}
        elif t=="match":
            right=[r for _,r in item["pairs"]]
            resp={}
            for idx,(left,_r) in enumerate(item["pairs"]):
                resp[left]=select_with_placeholder(left, right, key=f"{screen}_match_{idx}")
            response=resp
        elif t=="scale":
            val = st.slider("Wert", int(item.get("min",1)), int(item.get("max",5)), int(item.get("min",1)), key=f"{screen}_scale")
            response={"value": int(val)}
        else:
            txt = st.text_area("Deine Antwort:", key=f"{screen}_short")
            response={"text": txt}

        submitted=st.form_submit_button("Weiter")

    if not submitted:
        return None

    # Evaluate
    correct=True
    if t in ("mcq","case","pattern","cloze"):
        choice=response.get("choice")
        if choice is None:
            st.warning("Bitte auswählen.")
            return None
        correct = (item["options"].index(choice) == item["answer"])
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
        if item.get("rationale") and not correct:
            st.info(item["rationale"])
    elif t=="order":
        chosen=response.get("order_steps",[])
        if any(c is None for c in chosen):
            st.warning("Bitte alle Positionen ausfüllen.")
            return None
        if len(set(chosen))!=len(chosen):
            st.warning("Jeder Schritt nur einmal.")
            return None
        steps=list(item["steps"])
        idx=[steps.index(s) for s in chosen]
        correct = (idx == item["correct_order"])
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
        response={"order_steps": chosen, "order_idx": idx}
    elif t=="match":
        if any(v is None for v in response.values()):
            st.warning("Bitte alles zuordnen.")
            return None
        correct=True
        for left,rightv in item["pairs"]:
            if response.get(left)!=rightv:
                correct=False
        st.success("Richtig ✅" if correct else "Nicht ganz ❌")
    elif t=="short":
        txt=(response.get("text") or "").lower()
        kws=item.get("keywords",[])
        hits=sum(1 for kw in kws if kw.lower() in txt)
        correct = hits >= max(1, len(kws)//4) if kws else (len(txt.strip())>10)
        st.success("Gespeichert ✅")
        response={"text": response.get("text"), "hits": hits}
    else:
        # scale: always "valid"
        st.success("Gespeichert ✅")
        correct=True

    return {"correct": correct, "response": response}

# =========================
# App
# =========================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

ci=conn_items()
cd=conn_data()
ensure_data_tables(cd)
lf_items = load_items(ci)

# Sidebar login with auto IDs
with st.sidebar:
    st.header("Start")
    role_ui = st.selectbox("Rolle", ["Schüler:in","Lehrkraft"])
    role = "student" if role_ui=="Schüler:in" else "teacher"

    default_uid = "demo_schueler" if role=="student" else "demo_lehrkraft"
    uid_input = st.text_input("Kürzel/ID (ohne Klarnamen)", value=default_uid)

    if role=="student":
        if (not uid_input.strip()) or uid_input.strip()=="demo_schueler":
            if "auto_student_id" not in st.session_state:
                st.session_state["auto_student_id"]=f"S-{random.randint(100000,999999)}"
            user_id = st.session_state["auto_student_id"]
            st.info(f"Deine automatische ID: {user_id} (bitte merken)")
        else:
            user_id = uid_input.strip()
            st.session_state["auto_student_id"]=user_id
    else:
        user_id = uid_input.strip() if uid_input.strip() else default_uid

    display_name = st.text_input("Anzeigename (optional, ohne Klarnamen)", value="")
    class_code = st.text_input("Klasse/Kurs", value="GPA-TEST")
    easy_mode = st.toggle("Einfache Sprache", value=False)

upsert_user(cd, user_id, role, display_name, class_code)

tabs = st.tabs(["Schüler:in","Lehrkraft"])

# =========================
# Student view (structured flow)
# =========================
with tabs[0]:
    st.subheader("Schülerbereich")

    attempts = get_attempts(cd, user_id=user_id)
    prof = compute_profile(attempts)
    global_attempts = attempts[attempts["field_id"]=="GLOBAL"]
    global_done = len(global_attempts) >= 8  # approx full global set

    # Stepper
    step = 0 if not global_done else 1
    st.markdown("### Ablauf")
    st.write("**1)** Basis-Diagnostik (Sprache/Kognition/Meta/Motivation)  →  **2)** Lernfeld wählen + Fachdiagnostik  →  **3)** Üben")

    # --------- Step 1: GLOBAL diagnostic
    st.markdown("## 1) Basis-Diagnostik")
    if global_done:
        st.success("Basis-Diagnostik ist erledigt ✅")
        # show summary
        rows=[]
        for dom,_ in GLOBAL_DOMAINS:
            v = prof.get(("GLOBAL", dom), {"level":1,"accuracy":0.0,"n":0})
            rows.append({"Bereich": domain_name.get(dom, dom), "Level": v["level"], "Trefferquote": v["accuracy"], "Aufgaben": v["n"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Bitte zuerst die Basis-Diagnostik durchführen. Danach werden die Lernfelder freigeschaltet.")
        cols = st.columns(4)
        for i,(dom,label) in enumerate(GLOBAL_DOMAINS):
            with cols[i]:
                st.markdown(f"**{label}**")
                if st.button("Start", key=f"gstart_{dom}"):
                    chosen = pick_global(dom, n=3 if dom in ("SPR","KOG") else 2)
                    st.session_state["flow_items"]=chosen
                    st.session_state["flow_i"]=0
                    st.session_state["flow_mode"]=f"global_{dom}"
                    st.session_state["flow_field"]="GLOBAL"
                    st.session_state["flow_dom"]=dom
                    st.rerun()

    # Run any flow
    flow_items = st.session_state.get("flow_items", [])
    if flow_items:
        i = st.session_state.get("flow_i", 0)
        st.markdown("---")
        st.markdown(f"### Aufgabe {i+1}/{len(flow_items)}")
        st.progress((i+1)/len(flow_items))
        # Practice intro (topic + language level) shown once at start
        if st.session_state.get("flow_mode") == "practice" and i == 0:
            topic = st.session_state.get("practice_topic", "Allgemein")
            lvl = int(st.session_state.get("practice_lang_level", 2) or 2)
            st.markdown("---")
            custom = get_topic_text(cd, st.session_state.get("flow_field",""), topic, lvl)
            if custom and str(custom).strip():
                st.markdown(custom)
            else:
                st.markdown(generate_topic_intro(st.session_state.get("flow_field", ""), topic, lvl))
            st.caption(f"Sprachebene: {language_label(lvl)} · Abschluss immer mit einem Fall.")
            st.markdown("---")
        it = flow_items[i]
        res = render_item(it, key_prefix=f"flow_{st.session_state.get('flow_mode')}_", easy_mode=easy_mode)
        if res is not None:
            log_attempt(cd, user_id, class_code, it, res["correct"], res["response"], mode=st.session_state.get("flow_mode","diag"))
            if i+1 < len(flow_items):
                st.session_state["flow_i"]=i+1
                st.rerun()
            else:
                st.success("Fertig ✅")
                st.session_state["flow_items"]=[]
                st.session_state["flow_i"]=0
                st.session_state["flow_mode"]=None
                st.session_state["flow_field"]=None
                st.session_state["flow_dom"]=None
                st.rerun()

    st.markdown("---")

    # --------- Step 2: Lernfeld + Fachdiagnostik (locked until global_done)
    st.markdown("## 2) Fachdiagnostik nach Lernfeldern")
    if not global_done:
        st.warning("Lernfelder sind noch gesperrt, bis die Basis-Diagnostik abgeschlossen ist.")
    else:
        field_id = st.selectbox("Lernfeld wählen:", [x for x,_ in LEARN_FIELDS], format_func=lambda x: f"{x} – {lf_name.get(x,x)}")
        st.caption("Tipp: Starte kurz mit einer Fachdiagnostik, dann übe adaptiv.")

        # Thema für die Übungsrunde (optional)
        topics = sorted(set([ (it.get("topic") or "").strip() for it in lf_items if it.get("field")==field_id and it.get("domain")=="FACH" and (it.get("topic") or "").strip() ]))
        topic_choice = st.selectbox("Thema (Übung):", ["Auto (schwächstes Thema)"] + topics, index=0)
        chosen_topic = None if topic_choice.startswith("Auto") else topic_choice

        # teacher materials visible to students
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

        # compact snapshot for this LF
        prof2 = compute_profile(get_attempts(cd, user_id=user_id))
        v = prof2.get((field_id, "FACH"), {"level":1,"accuracy":0.0,"n":0})
        st.write(f"**Dein Stand in {field_id} (Fachwissen):** Level {v['level']} · Trefferquote {v['accuracy']} · Aufgaben {v['n']}")

        c1,c2 = st.columns([1,1])
        with c1:
            if st.button("Fachdiagnostik starten", key="start_fachdiag"):
                chosen = pick_lf(lf_items, field_id, n=6)
                st.session_state["flow_items"]=chosen
                st.session_state["flow_i"]=0
                st.session_state["flow_mode"]="lf_diag"
                st.session_state["flow_field"]=field_id
                st.session_state["flow_dom"]="FACH"
                st.rerun()
        with c2:
            if st.button("Üben (adaptiv) starten", key="start_practice"):
                at = get_attempts(cd, user_id=user_id)
                p = compute_profile(at)
                lvl = infer_language_level(p, easy_mode)
                topic = chosen_topic or pick_topic_for_practice(lf_items, at, field_id)
                chosen = pick_practice_sequence(lf_items, p, at, field_id, topic, k=10)

                st.session_state["practice_topic"] = topic
                st.session_state["practice_lang_level"] = lvl

                st.session_state["flow_items"]=chosen
                st.session_state["flow_i"]=0
                st.session_state["flow_mode"]="practice"
                st.session_state["flow_field"]=field_id
                st.session_state["flow_dom"]="FACH"
                st.rerun()

# =========================
# Teacher view (clear dashboards)
# =========================
with tabs[1]:
    st.subheader("Lehrkraft-Dashboard")

    users = get_users(cd)
    class_options = sorted([c for c in users["class_code"].dropna().unique().tolist() if c])
    chosen_class = st.selectbox("Klasse/Kurs", class_options if class_options else [class_code])

    class_users = users[(users["class_code"]==chosen_class) & (users["role"]=="student")]
    class_attempts = get_attempts(cd, class_code=chosen_class)

    c1,c2,c3 = st.columns(3)
    c1.metric("Schüler:innen", int(len(class_users)))
    c2.metric("Versuche", int(len(class_attempts)))
    c3.metric("Aufgabenbank", len(lf_items))

    # 1) Student overview
    st.markdown("### 1) Schülerübersicht")
    ov = student_overview(class_users, class_attempts)
    if ov.empty:
        st.info("Noch keine Schüler:innen in dieser Klasse.")
    else:
        ov_show = ov.copy()
        ov_show["last_activity"] = ov_show["last_activity"].dt.strftime("%Y-%m-%d %H:%M").fillna("—")
        ov_show["global_done"] = ov_show["global_done"].apply(lambda x: "✅" if x else "—")
        ov_show = ov_show.rename(columns={
            "user_id":"ID",
            "display_name":"Name",
            "attempts_total":"Aufgaben",
            "accuracy":"Trefferquote",
            "last_activity":"Letzte Aktivität",
            "fields_started":"Lernfelder gestartet",
            "learnfields":"Lernfelder",
            "global_done":"Basis-Diagnostik"
        })
        st.dataframe(ov_show[["ID","Name","Basis-Diagnostik","Aufgaben","Trefferquote","Letzte Aktivität","Lernfelder gestartet","Lernfelder"]],
                     use_container_width=True, hide_index=True)

    # 2) Where are the difficulties (GLOBAL + LF)
    st.markdown("### 2) Schwierigkeiten (Klasse)")
    if class_attempts.empty:
        st.info("Noch keine Daten.")
    else:
        wa = weakest_areas(class_attempts, top_n=12)
        wa_show=wa.copy()
        wa_show["Bereich"] = wa_show["domain_id"].apply(lambda x: domain_name.get(x,x))
        wa_show["Lernfeld"] = wa_show["field_id"].apply(lambda x: "Basis" if x=="GLOBAL" else f"{x} – {lf_name.get(x,x)}")
        st.dataframe(wa_show[["Lernfeld","Bereich","accuracy","attempts","level"]], use_container_width=True, hide_index=True)

    # 3) Per student: clean error analysis + recommendations
    st.markdown("### 3) Einzelanalyse (Fehler & Förderung)")
    if class_users.empty:
        st.info("Keine Schüler:innen gefunden.")
    else:
        sid = st.selectbox("Schüler:in auswählen (ID)", class_users["user_id"].tolist())
        s_attempts = get_attempts(cd, user_id=sid)
        s_prof = compute_profile(s_attempts)

        # A) Summary tiles
        colA,colB = st.columns([1,1])
        with colA:
            st.markdown("**Basis-Diagnostik (GLOBAL)**")
            rows=[]
            for dom,_ in GLOBAL_DOMAINS:
                v=s_prof.get(("GLOBAL",dom), {"level":1,"accuracy":0.0,"n":0})
                rows.append({"Bereich": domain_name[dom], "Level": v["level"], "Trefferquote": v["accuracy"], "Aufgaben": v["n"]})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        with colB:
            st.markdown("**Fachdiagnostik (Lernfelder)**")
            rows=[]
            for lf,_ in LEARN_FIELDS:
                v=s_prof.get((lf,"FACH"), {"level":1,"accuracy":0.0,"n":0})
                if v["n"]>0:
                    rows.append({"Lernfeld": f"{lf} – {lf_name.get(lf,lf)}", "Level": v["level"], "Trefferquote": v["accuracy"], "Aufgaben": v["n"]})
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption("Noch keine Fachdiagnostik bearbeitet.")

        # B) Priorities with recommendations
        st.markdown("**Förder-Schwerpunkte (Top 6)**")
        wa_s = weakest_areas(s_attempts, top_n=6)
        if wa_s.empty:
            st.caption("Noch nicht genug Daten.")
        else:
            for _, r in wa_s.iterrows():
                f=r["field_id"]; d=r["domain_id"]; lvl=int(r["level"])
                title = ("Basis" if f=="GLOBAL" else f"{f} – {lf_name.get(f,f)}") + f" / {domain_name.get(d,d)}"
                st.markdown(f"- **{title}** · Level {lvl} · Trefferquote {r['accuracy']}")
                for rec in recommend_support(f,d,lvl):
                    st.caption(f"• {rec}")

        # C) Error table: last incorrect answers with student's response & correct answer
        st.markdown("**Konkrete Fehler (letzte 20 falsche Antworten)**")
        wrong = s_attempts[s_attempts["correct"]==0].head(20)
        if wrong.empty:
            st.caption("Keine falschen Antworten gespeichert.")
        else:
            # build item map (LF + GLOBAL)
            item_map = {it["id"]: it for it in lf_items}
            item_map.update({it["id"]: it for it in GLOBAL_ITEMS})

            rows=[]
            for _, row in wrong.iterrows():
                it=item_map.get(row["item_id"])
                if not it:
                    continue
                resp=json.loads(row["response_json"] or "{}")
                student_answer = resp.get("choice") or resp.get("text") or resp.get("value") or resp.get("order_steps") or resp
                correct_answer = None
                t=it.get("type","").lower().strip()
                if t in ("mcq","case","pattern","cloze"):
                    correct_answer = it["options"][it.get("answer",0)]
                elif t=="order":
                    correct_answer = " → ".join([it["steps"][i] for i in it.get("correct_order",[])])
                elif t=="match":
                    correct_answer = "; ".join([f"{l}={r}" for l,r in it.get("pairs",[])])
                else:
                    correct_answer = "—"
                lf_label = "Basis" if row["field_id"]=="GLOBAL" else row["field_id"]
                rows.append({
                    "Zeit": str(row["created_at"])[:16],
                    "Lernfeld": lf_label,
                    "Bereich": domain_name.get(row["domain_id"], row["domain_id"]),
                    "Thema": it.get("topic",""),
                    "Aufgabe": it.get("prompt","")[:120] + ("…" if len(it.get("prompt",""))>120 else ""),
                    "Antwort Schüler:in": str(student_answer)[:120],
                    "Korrekt": str(correct_answer)[:120],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # D) Optional: topic heatmap summary for wrong items
        st.markdown("**Fehlerhäufigkeiten nach Themen**")
        if not wrong.empty:
            item_map = {it["id"]: it for it in lf_items}
            item_map.update({it["id"]: it for it in GLOBAL_ITEMS})
            tmp=[]
            for _, row in wrong.iterrows():
                it=item_map.get(row["item_id"])
                if it:
                    tmp.append({
                        "Lernfeld": "Basis" if row["field_id"]=="GLOBAL" else row["field_id"],
                        "Bereich": domain_name.get(row["domain_id"], row["domain_id"]),
                        "Thema": it.get("topic",""),
                    })
            df=pd.DataFrame(tmp)
            if not df.empty:
                summ = df.groupby(["Lernfeld","Bereich","Thema"]).size().reset_index(name="Fehler")
                summ = summ.sort_values("Fehler", ascending=False).head(15)
                st.dataframe(summ, use_container_width=True, hide_index=True)

    # 4) Materials
    st.markdown("### 4) Thementexte (Infotexte) bearbeiten")
        st.caption("Hier kannst du pro Lernfeld + Thema kurze Infotexte in drei Sprachebenen hinterlegen. Diese werden im adaptiven Üben vor den Aufgaben angezeigt.")
        topics_df = list_topics(ci)
        if topics_df.empty:
            st.info("Keine Themen gefunden.")
        else:
            lf_sel = st.selectbox("Lernfeld (Thementexte)", sorted(topics_df["field_id"].unique().tolist(), key=lambda x:int(x[2:])))
            topic_opts = topics_df[topics_df["field_id"]==lf_sel].sort_values("topic")["topic"].tolist()
            topic_sel = st.selectbox("Thema", topic_opts)
            lvl_sel = st.selectbox("Sprachebene", [1,2,3], format_func=lambda x: f"{x} – {language_label(x)}")
            default_text = get_topic_text(cd, lf_sel, topic_sel, int(lvl_sel)) or ""
            st.caption("Hinweis: Bitte in eigenen Worten formulieren (keine langen Buch-Zitate).")
            new_text = st.text_area("Infotext", value=default_text, height=220)
            if st.button("Infotext speichern", key="save_topic_text"):
                upsert_topic_text(cd, lf_sel, topic_sel, int(lvl_sel), new_text.strip())
                st.success("Gespeichert ✅")

            with st.expander("Themenübersicht (Anzahl Items & Typen)"):
                show = topics_df[topics_df["field_id"]==lf_sel].copy()
                st.dataframe(show, use_container_width=True, hide_index=True)


### 5) Material hochladen (für Schüler:innen)")
    st.caption("Nur eigenes / frei nutzbares Material hochladen. Keine Klarnamen im Dateinamen (Prototyp speichert in lokaler DB).")
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

st.caption("Prototyp. Für echten Betrieb: Rollen, Datenschutz, Hosting, Backups, Rechtekonzept.")
