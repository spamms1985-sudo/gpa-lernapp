import sqlite3
import json
import random
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st

DB_PATH = "gpa_items_fachwissen_v1.db"  # put this DB in the repo next to app.py

APP_TITLE = "GPA Lernapp"
APP_SUBTITLE = "Fachwissen im Fokus · Lernfeld → Diagnose je Bereich → Üben"

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

lf_name = dict(LEARN_FIELDS)
domain_name = dict(DOMAINS)

TYPE_LABEL = {
    "mcq": "Quiz",
    "case": "Fall",
    "cloze": "Lücke",
    "match": "Zuordnen",
    "order": "Reihenfolge",
    "short": "Kurzantwort",
    "pattern": "Quiz",
}

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def load_items(conn) -> List[Dict[str, Any]]:
    df = pd.read_sql_query("SELECT payload_json FROM items", conn)
    return [json.loads(x) for x in df["payload_json"].tolist()]

# attempts stored in same db for simplicity
def ensure_attempt_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        display_name TEXT NOT NULL,
        class_code TEXT,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
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

def upsert_user(conn, user_id, role, display_name, class_code):
    conn.execute("""
    INSERT INTO users(user_id, role, display_name, class_code, created_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET
        role=excluded.role,
        display_name=excluded.display_name,
        class_code=excluded.class_code
    """, (user_id, role, display_name, class_code, datetime.utcnow().isoformat()))
    conn.commit()

def log_attempt(conn, user_id, class_code, item, correct, response, mode):
    conn.execute("""
    INSERT INTO attempts(user_id, class_code, item_id, field_id, domain_id, difficulty, correct, response_json, created_at)
    VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        user_id, class_code, item["id"], item["field"], item["domain"], int(item["difficulty"]),
        int(bool(correct)), json.dumps({"mode": mode, **response}, ensure_ascii=False), datetime.utcnow().isoformat()
    ))
    conn.commit()

def get_attempts(conn, user_id=None, class_code=None):
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
    return pd.read_sql_query(q, conn, params=params)

def compute_profile(attempts_df: pd.DataFrame):
    if attempts_df.empty:
        return {}
    agg={}
    for _, r in attempts_df.iterrows():
        key=(r["field_id"], r["domain_id"])
        w=WEIGHTS.get(int(r["difficulty"]), 1.0)
        agg.setdefault(key, {"w":0.0,"c":0.0,"n":0.0})
        agg[key]["w"] += w
        agg[key]["c"] += w*(1.0 if int(r["correct"])==1 else 0.0)
        agg[key]["n"] += 1.0
    out={}
    for key, v in agg.items():
        acc=v["c"]/max(v["w"],1e-9)
        lvl=1 if acc<0.45 else (2 if acc<0.75 else 3)
        out[key]={"accuracy": round(acc,2), "level": lvl, "n": int(v["n"])}
    return out

def pick(items, field_id, domain_id, n):
    cand=[it for it in items if it["field"]==field_id and it["domain"]==domain_id]
    if not cand:
        return []
    return random.sample(cand, k=min(n, len(cand)))

def pick_adaptive(items, profile, field_id, seen, k):
    dom_levels={dom: profile.get((field_id, dom), {}).get("level", 1) for dom,_ in DOMAINS}
    # focus on fach first
    dom_plan=[]
    for dom,_ in DOMAINS:
        lvl=dom_levels.get(dom,1)
        weight=4 - min(3,lvl)
        if dom=="FACH":
            weight += 2
        dom_plan.extend([dom]*max(1,weight))
    picked=[]
    tries=0
    while len(picked)<k and tries<k*20:
        tries+=1
        dom=random.choice(dom_plan)
        target=dom_levels.get(dom,1)
        pool=[]
        for it in items:
            if it["field"]!=field_id or it["domain"]!=dom:
                continue
            dist=abs(int(it["difficulty"])-int(target))
            penalty=0.6 if it["id"] in seen else 0.0
            pool.append((dist+penalty+random.random()*0.2, it))
        pool.sort(key=lambda x:x[0])
        if pool:
            it=pool[0][1]
            picked.append(it)
            seen.add(it["id"])
    return picked[:k]

def badge(item):
    label=TYPE_LABEL.get(item.get("type",""), "Aufgabe")
    dom=domain_name.get(item.get("domain",""), item.get("domain",""))
    stars="⭐"*int(item.get("difficulty",1))
    st.caption(f"{label} · {dom} · {stars}")

def render(item, easy_mode, key_prefix):
    badge(item)
    prompt=item.get("prompt_easy") if easy_mode and item.get("prompt_easy") else item.get("prompt","")
    st.write(prompt)

    t=item.get("type","").lower().strip()
    if t in ("mcq","case","pattern"):
        choice=st.radio("Antwort:", item["options"], index=None, key=f"{key_prefix}{item['id']}_mcq")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            if choice is None:
                st.warning("Bitte auswählen."); return None
            correct = (item["options"].index(choice)==item["answer"])
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            if item.get("rationale") and not correct:
                st.info(item["rationale"])
            return {"correct": correct, "response": {"choice": choice}}

    if t=="cloze":
        choice=st.selectbox("Wort:", item["options"], index=None, key=f"{key_prefix}{item['id']}_cloze")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            if choice is None:
                st.warning("Bitte auswählen."); return None
            correct=(item["options"].index(choice)==item["answer"])
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": {"choice": choice}}

    if t=="order":
        st.caption("Gib die Reihenfolge ein: z. B. 1-3-2-4")
        for i,s in enumerate(item["steps"], start=1):
            st.write(f"{i}. {s}")
        text=st.text_input("Reihenfolge:", key=f"{key_prefix}{item['id']}_order")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            try:
                parts=[int(p.strip()) for p in text.replace("–","-").split("-")]
                idx=[p-1 for p in parts]
                correct=(idx==item["correct_order"])
                st.success("Richtig ✅" if correct else "Nicht ganz ❌")
                return {"correct": correct, "response": {"order": parts}}
            except Exception:
                st.warning("Format: 1-3-2-4"); return None

    if t=="match":
        st.caption("Ordne zu:")
        responses={}
        right=[r for _,r in item["pairs"]]
        for left,_ in item["pairs"]:
            responses[left]=st.selectbox(left, right, index=None, key=f"{key_prefix}{item['id']}_{left}")
        if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
            correct=True
            for left,rightv in item["pairs"]:
                if responses.get(left)!=rightv:
                    correct=False
            st.success("Richtig ✅" if correct else "Nicht ganz ❌")
            return {"correct": correct, "response": responses}

    # short
    answer=st.text_area("Deine Antwort:", key=f"{key_prefix}{item['id']}_short")
    if st.button("Weiter", key=f"{key_prefix}{item['id']}_submit"):
        text=(answer or "").lower()
        kws=item.get("keywords",[])
        hits=sum(1 for kw in kws if kw.lower() in text)
        correct = hits >= max(1, len(kws)//4) if kws else (len(text.strip())>10)
        st.success("Gespeichert ✅")
        return {"correct": correct, "response": {"text": answer, "hits": hits}}

def card(title, body):
    st.markdown(f"""
    <div style="padding:14px;border-radius:16px;border:1px solid rgba(0,0,0,.12);margin-bottom:10px;">
      <div style="font-size:18px;font-weight:700;margin-bottom:4px;">{title}</div>
      <div style="opacity:.85;">{body}</div>
    </div>
    """, unsafe_allow_html=True)

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

conn=get_conn()
ensure_attempt_tables(conn)
items=load_items(conn)

with st.sidebar:
    st.header("Start")
    role_ui=st.selectbox("Rolle", ["Schüler:in","Lehrkraft"])
    role="student" if role_ui=="Schüler:in" else "teacher"
    user_id=st.text_input("Kürzel (z. B. MS12)", value="demo_schueler" if role=="student" else "demo_lehrkraft")
    display_name=st.text_input("Name (optional)", value="")
    class_code=st.text_input("Klasse/Kurs", value="GPA-TEST")
    easy_mode=st.toggle("Einfache Sprache", value=False)
    upsert_user(conn, user_id, role, display_name, class_code)

attempts=get_attempts(conn, user_id=user_id)
profile=compute_profile(attempts)
seen=set(attempts["item_id"].tolist()) if not attempts.empty else set()

tabs=st.tabs(["Schüler:in","Lehrkraft"])

with tabs[0]:
    st.markdown("### 1) Lernfeld auswählen")
    field_id=st.selectbox("Lernfeld:", [x for x,_ in LEARN_FIELDS], format_func=lambda x: f"{x} – {lf_name.get(x,x)}")
    card(f"{field_id} – {lf_name.get(field_id, field_id)}", "Diagnose je Bereich (Fachwissen zuerst) → dann Üben.")

    st.markdown("### 2) Lernstand erheben (je Bereich)")
    per_domain=st.slider("Aufgaben pro Bereich", 3, 10, 5, 1)

    cols=st.columns(4)
    for i,(dom,label) in enumerate(DOMAINS):
        with cols[i]:
            st.markdown(f"**{label}**")
            if st.button("Start", key=f"start_{dom}"):
                chosen=pick(items, field_id, dom, per_domain)
                st.session_state["flow_items"]=chosen
                st.session_state["flow_i"]=0
                st.session_state["flow_mode"]=f"diag_{dom}"
                st.session_state["flow_field"]=field_id
                st.session_state["flow_dom"]=dom
                st.rerun()

    flow_items=st.session_state.get("flow_items", [])
    if flow_items and st.session_state.get("flow_field")==field_id:
        i=st.session_state.get("flow_i",0)
        st.markdown("---")
        st.markdown(f"### Mini-Check: {domain_name.get(st.session_state.get('flow_dom'), st.session_state.get('flow_dom'))}")
        st.progress((i+1)/len(flow_items))
        it=flow_items[i]
        res=render(it, easy_mode, key_prefix=f"flow_{st.session_state.get('flow_mode')}_")
        if res is not None:
            log_attempt(conn, user_id, class_code, it, res["correct"], res["response"], mode=st.session_state.get("flow_mode","diag"))
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

    st.markdown("### 3) Passende Aufgaben üben")
    k=st.slider("Übungsrunde", 5, 15, 8, 1)
    if st.button("Übung starten"):
        attempts2=get_attempts(conn, user_id=user_id)
        prof2=compute_profile(attempts2)
        seen2=set(attempts2["item_id"].tolist()) if not attempts2.empty else set()
        chosen=pick_adaptive(items, prof2, field_id, seen2, k)
        st.session_state["flow_items"]=chosen
        st.session_state["flow_i"]=0
        st.session_state["flow_mode"]="practice"
        st.session_state["flow_field"]=field_id
        st.session_state["flow_dom"]=None
        st.rerun()

with tabs[1]:
    st.subheader("Lehrkraft")
    users=pd.read_sql_query("SELECT * FROM users ORDER BY created_at DESC", conn)
    classes=sorted([c for c in users["class_code"].dropna().unique().tolist() if c])
    chosen_class=st.selectbox("Klasse/Kurs", classes if classes else [class_code])
    class_users=users[(users["class_code"]==chosen_class) & (users["role"]=="student")]
    class_attempts=get_attempts(conn, class_code=chosen_class)

    c1,c2,c3=st.columns(3)
    c1.metric("Schüler:innen", int(len(class_users)))
    c2.metric("Versuche", int(len(class_attempts)))
    c3.metric("Items", len(items))

    if not class_users.empty:
        sid=st.selectbox("Schüler:in", class_users["user_id"].tolist())
        s_attempts=get_attempts(conn, user_id=sid)
        s_prof=compute_profile(s_attempts)

        rows=[]
        for lf,_ in LEARN_FIELDS:
            for dom,_ in DOMAINS:
                v=s_prof.get((lf, dom), {"level":1,"accuracy":0.0,"n":0})
                rows.append({"Lernfeld": lf, "Bereich": domain_name.get(dom,dom), "Level": v["level"], "Trefferquote": v["accuracy"], "Aufgaben": v["n"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        csv=class_attempts.to_csv(index=False).encode("utf-8")
        st.download_button("CSV export", data=csv, file_name=f"export_{chosen_class}.csv", mime="text/csv")
    else:
        st.info("Noch keine Schüler:innen-Daten in dieser Klasse.")

st.caption("Hinweis: Für Prototypen okay. Für echten Betrieb: Datenschutz, Rollen, Hosting & Persistenz planen.")
