
import sqlite3
import random
import json
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional

import streamlit as st

APP_TITLE = "GPA Lernapp (Prototyp)"
APP_SUBTITLE = "Lernfeld auswählen → kurze Diagnostik → passende Aufgaben"

DB_PATH = "gpa_lernapp.db"  # will be auto-created

# -----------------------------
# Curriculum scaffolding (Hamburg GPA Bildungsplan)
# We avoid copying book text verbatim; items are newly formulated practice tasks aligned to topics.
# -----------------------------

LEARN_FIELDS: List[Tuple[str, str]] = [
    ("LF1", "Sich im Berufsfeld orientieren"),
    ("LF2", "Gesundheit erhalten und fördern"),
    ("LF3", "Häusliche Pflege und hauswirtschaftliche Abläufe mitgestalten"),
    ("LF4", "Bei der Körperpflege anleiten und unterstützen"),
    ("LF5", "Menschen bei der Nahrungsaufnahme und Ausscheidung anleiten und unterstützen"),
    ("LF6", "Die Mobilität erhalten und fördern"),
    ("LF7", "Menschen bei der Bewältigung von Krisen unterstützen"),
    ("LF8", "Menschen in besonderen Lebenssituationen unterstützen"),
    ("LF9", "Menschen mit körperlichen und geistigen Beeinträchtigungen unterstützen"),
    ("LF10", "Menschen in der Endphase des Lebens begleiten und pflegen"),
]

# Per Lernfeld: areas that make sense for separate diagnostics (instead of one huge list)
LF_AREAS: Dict[str, List[Dict[str, str]]] = {
    "LF1": [
        {"key": "rolle_team", "label": "Rolle, Team, Kommunikation"},
        {"key": "recht_ethik", "label": "Recht, Schweigepflicht, Ethik"},
        {"key": "hygiene_sicherheit", "label": "Arbeitsschutz, Hygiene-Basics"},
    ],
    "LF2": [
        {"key": "gesundheit_praevention", "label": "Gesundheit, Prävention, Gesundheitsförderung"},
        {"key": "vitalzeichen", "label": "Vitalzeichen & Beobachtung"},
        {"key": "infekt_prophylaxe", "label": "Infektionszeichen & Prophylaxen"},
    ],
    "LF3": [
        {"key": "haushalt_org", "label": "Arbeitsorganisation & Haushaltsführung"},
        {"key": "lebensmittelhygiene", "label": "Lebensmittelhygiene & Desinfektion"},
        {"key": "umwelt_wirtschaft", "label": "Wirtschaftlichkeit & Umweltschutz"},
    ],
    "LF4": [
        {"key": "haut_grundlagen", "label": "Haut: Anatomie/Beobachtung"},
        {"key": "koerperpflege", "label": "Körperpflege: Durchführung/Anleitung"},
        {"key": "prophylaxen", "label": "Dekubitus/Intertrigo: Risiken & Prophylaxe"},
        {"key": "sinnesorgane", "label": "Augen/Ohren: Pflege & Hilfsmittel"},
        {"key": "doku_pflegeprozess", "label": "Pflegeprozess & Dokumentation"},
    ],
    "LF5": [
        {"key": "ernaehrung", "label": "Ernährung, Essenreichen, Atmosphäre"},
        {"key": "fluessigkeit_bilanz", "label": "Flüssigkeit, Bilanzierung, Dehydration"},
        {"key": "schluckstoerung_sonde", "label": "Schluckstörung & Nahrungssonde"},
        {"key": "ausscheidung", "label": "Ausscheidung & Inkontinenz"},
        {"key": "prophylaxen", "label": "Soor/Parotitis/Obstipation: Prophylaxen"},
    ],
    "LF6": [
        {"key": "bewegungsapparat", "label": "Bewegungsapparat: Grundlagen"},
        {"key": "mobilisation_transfer", "label": "Mobilisation, Lagerung, Transfer (Ergonomie)"},
        {"key": "sturzrisiko", "label": "Sturzrisiko: Einschätzung & Prävention"},
        {"key": "prophylaxen", "label": "Kontrakturen-/Thrombose-/Pneumonieprophylaxe"},
        {"key": "beispiele", "label": "Beispielhafte Krankheitsbilder (z.B. Arthrose/TEP)"},
    ],
    "LF7": [
        {"key": "herz_kreislauf", "label": "Herz-Kreislauf: Grundlagen"},
        {"key": "notfallbilder", "label": "Akute Notfälle (z.B. Herzinfarkt, hypertensive Krise)"},
        {"key": "thrombose_embolie", "label": "Thrombose/Embolie: Zeichen & Maßnahmen"},
        {"key": "schmerz", "label": "Schmerz: Beobachtung, Dokumentation, nicht-medikamentös"},
        {"key": "wunden_injektion", "label": "Wunden/Wundheilung & s.c. Injektion (Heparin/Insulin)"},
    ],
    "LF8": [
        {"key": "chronisch", "label": "Chronische Erkrankungen & Umgang"},
        {"key": "diabetes", "label": "Diabetes: Beobachtung, BZ, Insulin (unter Anleitung)"},
        {"key": "herzinsuff", "label": "Herzinsuffizienz: Symptome, Beobachtung, Alltag"},
        {"key": "medikamente", "label": "Medikamente: Wirkung/Nebenwirkung beobachten"},
    ],
    "LF9": [
        {"key": "beeintraechtigung", "label": "Beeinträchtigungen: Ressourcen & Aktivierung"},
        {"key": "demenz_kommunikation", "label": "Demenz & Kommunikation (Validation, Basale Stimulation)"},
        {"key": "hilfsmittel", "label": "Hilfsmittel & rehabilitative Unterstützung"},
    ],
    "LF10": [
        {"key": "palliativ", "label": "Palliative Grundhaltung & Bedürfnisse"},
        {"key": "zeichen_sterben", "label": "Zeichen des nahenden Todes & Beobachtung"},
        {"key": "angehoerige", "label": "Angehörige begleiten & Kommunikation"},
        {"key": "nach_tod", "label": "Maßnahmen nach Eintritt des Todes (Rollenklarheit)"},
    ],
}

# -----------------------------
# Question bank
# Each item is authored (paraphrased/new), aligned to topics from Bildungsplan & provided books.
# Types implemented: mcq, multi, tf, cloze, order, match, case_mcq, short
# -----------------------------

def _mcq(q, options, answer, explanation="", tags=None):
    return {"type": "mcq", "q": q, "options": options, "answer": answer, "explanation": explanation, "tags": tags or []}

def _multi(q, options, answers, explanation="", tags=None):
    return {"type": "multi", "q": q, "options": options, "answers": answers, "explanation": explanation, "tags": tags or []}

def _tf(q, answer, explanation="", tags=None):
    return {"type": "tf", "q": q, "answer": bool(answer), "explanation": explanation, "tags": tags or []}

def _cloze(q, answer, hints=None, explanation="", tags=None):
    return {"type": "cloze", "q": q, "answer": answer, "hints": hints or [], "explanation": explanation, "tags": tags or []}

def _order(q, items, solution, explanation="", tags=None):
    return {"type": "order", "q": q, "items": items, "solution": solution, "explanation": explanation, "tags": tags or []}

def _match(q, left, right, solution, explanation="", tags=None):
    return {"type": "match", "q": q, "left": left, "right": right, "solution": solution, "explanation": explanation, "tags": tags or []}

def _case_mcq(stem, question, options, answer, explanation="", tags=None):
    return {"type": "case_mcq", "stem": stem, "q": question, "options": options, "answer": answer, "explanation": explanation, "tags": tags or []}

def _short(q, rubric, keywords=None, tags=None):
    return {"type": "short", "q": q, "rubric": rubric, "keywords": keywords or [], "tags": tags or []}


QUESTION_BANK: Dict[str, Dict[str, Dict[int, List[Dict[str, Any]]]]] = {}

def add_item(lf: str, area: str, level: int, item: Dict[str, Any]):
    QUESTION_BANK.setdefault(lf, {}).setdefault(area, {}).setdefault(level, []).append(item)

def seed_questions():
    # ---- LF4 Körperpflege / Haut / Prophylaxen / Doku ----
    lf = "LF4"
    add_item(lf, "haut_grundlagen", 1, _mcq(
        "Welche Aufgabe der Haut trifft am ehesten zu?",
        ["Wärmeregulation und Schutz", "Blutzuckerproduktion", "Gasaustausch wie in der Lunge", "Bildung von Gelenkflüssigkeit"],
        "Wärmeregulation und Schutz",
        "Die Haut schützt (Barriere) und hilft bei der Thermoregulation."
    ))
    add_item(lf, "haut_grundlagen", 2, _case_mcq(
        "Frau K. hat sehr trockene, dünne Altershaut. Nach dem Waschen spannt die Haut, es zeigen sich kleine Risse.",
        "Was ist eine passende pflegerische Maßnahme?",
        ["Mit alkoholhaltigem Desinfektionsmittel einreiben", "Sanft abtrocknen und rückfettende Pflege anwenden", "Haut kräftig rubbeln, damit sie 'durchblutet'", "So heiß wie möglich duschen"],
        "Sanft abtrocknen und rückfettende Pflege anwenden",
        "Schonend vorgehen, Hautbarriere schützen und pflegende Produkte passend auswählen."
    ))
    add_item(lf, "koerperpflege", 1, _multi(
        "Welche Punkte gehören zur Vorbereitung einer Ganzwaschung im Bett? (Mehrfachauswahl)",
        ["Raumtemperatur prüfen / Zugluft vermeiden", "Material bereitstellen", "Klient:in über Vorgehen informieren", "Scham/Intimsphäre ignorieren"],
        ["Raumtemperatur prüfen / Zugluft vermeiden", "Material bereitstellen", "Klient:in über Vorgehen informieren"],
        "Vorbereitung umfasst Schutz der Intimsphäre, Information und Material/Umgebung."
    ))
    add_item(lf, "prophylaxen", 1, _mcq(
        "Was ist ein typischer Risikofaktor für Dekubitus?",
        ["Lange Immobilität", "Viel Bewegung", "Kurze Duschen", "Hoher Obstkonsum"],
        "Lange Immobilität",
        "Druck/Schubkräfte bei Immobilität erhöhen das Dekubitusrisiko."
    ))
    add_item(lf, "prophylaxen", 2, _case_mcq(
        "Bei Herrn S. fallen gerötete, feuchte Hautstellen in einer Hautfalte auf, es riecht leicht säuerlich.",
        "Was passt am besten?",
        ["Intertrigo – Hautfalte trocken halten, Reibung reduzieren", "Pneumonie – Atemübungen", "Thrombose – Kompressionsstrümpfe anziehen", "Dehydration – Trinkprotokoll starten"],
        "Intertrigo – Hautfalte trocken halten, Reibung reduzieren",
        "Intertrigo entsteht häufig in Hautfalten durch Feuchtigkeit/Reibung; Prophylaxe: trocken, luftdurchlässig, Schutz."
    ))
    add_item(lf, "sinnesorgane", 1, _tf(
        "Hörgeräte dürfen bei der Körperpflege grundsätzlich nicht herausgenommen werden.",
        False,
        "Je nach Situation werden Hörgeräte geschützt/entnommen; Ziel ist sichere Pflege ohne Beschädigung, aber Kommunikation ermöglichen."
    ))
    add_item(lf, "doku_pflegeprozess", 2, _cloze(
        "Im Pflegeprozess werden Beobachtungen und durchgeführte Maßnahmen im ______________ festgehalten.",
        "Dokumentationssystem",
        hints=["Pflegedokumentation", "Doku"],
        explanation="Der Bildungsplan betont Pflegeprozess und Dokumentation als Kernbestandteil in LF4."
    ))
    add_item(lf, "doku_pflegeprozess", 3, _short(
        "Nenne 3 Beobachtungspunkte, die du bei der Hautbeobachtung dokumentieren würdest.",
        rubric="Beispiele: Farbe/Rötung, Temperatur, Feuchtigkeit, Läsionen/Wunden, Schmerzen/Juckreiz, Druckstellen, Schwellung.",
        keywords=["röt", "farbe", "wärm", "feucht", "wunde", "druck", "schmerz", "juck", "schwell"]
    ))

    # ---- LF5 Essen/Trinken/Ausscheidung ----
    lf = "LF5"
    add_item(lf, "fluessigkeit_bilanz", 1, _mcq(
        "Wofür steht eine 'Flüssigkeitsbilanz' am ehesten?",
        ["Vergleich von Einfuhr und Ausfuhr", "Nur Getränkemenge ohne Ausscheidung", "Nur Blutdruckmessung", "Nur Gewichtskontrolle"],
        "Vergleich von Einfuhr und Ausfuhr",
        "Bilanzierung vergleicht Aufnahme und Ausscheidung."
    ))
    add_item(lf, "fluessigkeit_bilanz", 2, _case_mcq(
        "Eine Klientin wirkt schläfrig, die Schleimhäute sind trocken, der Urin ist sehr dunkel.",
        "Welche Beobachtung passt am ehesten zu Dehydration?",
        ["Erhöhter Speichelfluss", "Trockene Schleimhäute und konzentrierter Urin", "Vermehrter klarer Urin", "Hohes Fieber mit Husten"],
        "Trockene Schleimhäute und konzentrierter Urin",
        "Typische Hinweise sind trockene Schleimhäute, Durst, dunkler Urin."
    ))
    add_item(lf, "schluckstoerung_sonde", 2, _multi(
        "Welche Maßnahmen sind bei Schluckstörung sinnvoll? (Mehrfachauswahl)",
        ["Aufrechte Sitzposition", "Langsam füttern, kleine Bissen", "Während des Essens hinlegen", "Auf Anzeichen von Husten/Würgen achten"],
        ["Aufrechte Sitzposition", "Langsam füttern, kleine Bissen", "Auf Anzeichen von Husten/Würgen achten"],
        "Sicherheit/Asprirationsprophylaxe: aufrecht, langsam, beobachten."
    ))
    add_item(lf, "ausscheidung", 1, _mcq(
        "Was bedeutet 'Inkontinenz'?",
        ["Unwillkürlicher Urin- oder Stuhlverlust", "Fieber über 39°C", "Schluckstörung", "Erhöhter Blutzucker"],
        "Unwillkürlicher Urin- oder Stuhlverlust",
        "Inkontinenz betrifft die Kontrolle über Ausscheidung."
    ))
    add_item(lf, "prophylaxen", 2, _match(
        "Ordne zu: Prophylaxe ↔ Ziel",
        left=["Soorprophylaxe", "Parotitisprophylaxe", "Obstipationsprophylaxe"],
        right=["Speichelfluss anregen / Mundpflege", "Mundschleimhaut schützen", "Stuhlgang fördern"],
        solution={"Soorprophylaxe": "Mundschleimhaut schützen",
                  "Parotitisprophylaxe": "Speichelfluss anregen / Mundpflege",
                  "Obstipationsprophylaxe": "Stuhlgang fördern"},
        explanation="Zuordnung entlang typischer Ziele in LF5."
    ))
    add_item(lf, "ernaehrung", 3, _short(
        "Wie würdest du eine angenehme Atmosphäre beim Essenreichen herstellen? Nenne 4 Punkte.",
        rubric="Beispiele: Ruhe, Sitzposition, Zeit lassen, Vorlieben beachten, kleine Portionen, Blickkontakt/Ansprache, Hilfsmittel nutzen.",
        keywords=["ruhe", "zeit", "aufrecht", "vorlieb", "portion", "hilfe", "ansprech", "hygien"]
    ))

    # ---- LF6 Mobilität / Prophylaxen / Sturz ----
    lf = "LF6"
    add_item(lf, "bewegungsapparat", 1, _mcq(
        "Welche Aussage passt am besten?",
        ["Bewegung unterstützt Kreislauf, Atmung und Wohlbefinden", "Immobilität hat keine Folgen", "Nur Sportler:innen brauchen Mobilisation", "Lagerung ist unwichtig"],
        "Bewegung unterstützt Kreislauf, Atmung und Wohlbefinden",
        "Der Bildungsplan betont die Bedeutung von Bewegung und den Umgang mit Immobilität."
    ))
    add_item(lf, "sturzrisiko", 1, _multi(
        "Welche Faktoren können das Sturzrisiko erhöhen? (Mehrfachauswahl)",
        ["Schwindel", "Schlecht sitzende Schuhe", "Gute Beleuchtung", "Muskelschwäche"],
        ["Schwindel", "Schlecht sitzende Schuhe", "Muskelschwäche"],
        "Typische Risikofaktoren: Schwindel, unsicheres Schuhwerk, Muskelschwäche."
    ))
    add_item(lf, "prophylaxen", 2, _case_mcq(
        "Ein bettlägeriger Patient atmet flach und hustet kaum. Er ist wenig mobil.",
        "Welche Prophylaxe ist besonders relevant?",
        ["Pneumonieprophylaxe", "Soorprophylaxe", "Parotitisprophylaxe", "Inkontinenztraining"],
        "Pneumonieprophylaxe",
        "Bei Immobilität sind Kontrakturen-, Thrombose- und Pneumonieprophylaxe zentrale Themen."
    ))
    add_item(lf, "beispiele", 2, _mcq(
        "Welche Beschwerde passt typisch zu Arthrose?",
        ["Anlaufschmerz nach Ruhephasen", "Plötzliche Lähmung", "Hoher Hustenreiz mit Auswurf", "Sofortige Bewusstlosigkeit"],
        "Anlaufschmerz nach Ruhephasen",
        "Arthrose zeigt häufig Anlaufschmerz; später auch Ruhe-/Nachtschmerz."
    ))
    add_item(lf, "mobilisation_transfer", 3, _order(
        "Bringe die Schritte in eine sinnvolle Reihenfolge (Transfer Bett → Stuhl, mit Sicherheit im Blick):",
        items=["Bremse am Stuhl", "Klient:in informieren", "Hilfsmittel prüfen (z.B. Rutschbrett)", "Stand/Stabilität sichern", "Nach dem Transfer bequem positionieren"],
        solution=["Klient:in informieren", "Bremse am Stuhl", "Hilfsmittel prüfen (z.B. Rutschbrett)", "Stand/Stabilität sichern", "Nach dem Transfer bequem positionieren"],
        explanation="Reihenfolge: Kommunikation + Sicherheit (Bremsen) vor Durchführung; danach Positionierung."
    ))

    # ---- LF7 Krisen/Notfall/Schmerz/Wunden/Injektion ----
    lf = "LF7"
    add_item(lf, "herz_kreislauf", 1, _mcq(
        "Was ist Tachykardie?",
        ["Erhöhter Puls", "Erniedrigter Blutzucker", "Blauer Hautausschlag", "Erhöhter Speichelfluss"],
        "Erhöhter Puls",
        "Tachykardie = schneller Herzschlag."
    ))
    add_item(lf, "notfallbilder", 2, _case_mcq(
        "Ein Patient klagt plötzlich über starken Druck auf der Brust, ist blass und schweißig, wirkt ängstlich.",
        "Was ist als erstes angemessen?",
        ["Allein lassen, damit er ruht", "Pflegefachkraft/Notruf informieren und beruhigen, Vitalzeichen beobachten", "Sofort Essen anbieten", "Wunde verbinden"],
        "Pflegefachkraft/Notruf informieren und beruhigen, Vitalzeichen beobachten",
        "Bei Verdacht auf akuten Notfall: Hilfe holen, beruhigen, beobachten, nach Vorgaben handeln."
    ))
    add_item(lf, "thrombose_embolie", 2, _mcq(
        "Welche Situation passt eher zu einer tiefen Beinvenenthrombose?",
        ["Einseitig geschwollenes, schmerzhaftes Bein nach Immobilität", "Husten mit gelbem Auswurf", "Juckende Hautfalte", "Zahnfleischbluten beim Putzen"],
        "Einseitig geschwollenes, schmerzhaftes Bein nach Immobilität",
        "Einseitige Schwellung/Schmerz nach Immobilität ist ein Warnzeichen – immer weiterleiten."
    ))
    add_item(lf, "schmerz", 1, _multi(
        "Welche nicht-medikamentösen Maßnahmen können Schmerzen lindern? (Mehrfachauswahl)",
        ["Wärme/Kälte (je nach Situation)", "Ablenkung/Entspannung", "Ruhige Lagerung", "Zwang zu Bewegung bei starken Schmerzen"],
        ["Wärme/Kälte (je nach Situation)", "Ablenkung/Entspannung", "Ruhige Lagerung"],
        "Nicht-medikamentös: z.B. Lagerung, Entspannung, Wärme/Kälte – immer nach Plan/Absprache."
    ))
    add_item(lf, "wunden_injektion", 2, _tf(
        "Bei der Wundversorgung ist Hygiene (z.B. Händedesinfektion) optional, wenn man Handschuhe trägt.",
        False,
        "Handschuhe ersetzen keine Händehygiene."
    ))
    add_item(lf, "wunden_injektion", 3, _short(
        "Nenne 3 sichere und 3 unsichere Frakturzeichen.",
        rubric="Sichere: Fehlstellung, abnorme Beweglichkeit, Krepitation, sichtbare Fragmente. Unsichere: Schmerz, Schwellung, Hämatom, Bewegungseinschränkung, eingeschränkte Belastbarkeit.",
        keywords=["fehl", "abnorm", "knirsch", "fragment", "schmerz", "schwell", "hämat", "beweg"]
    ))

    # ---- LF8 Chronisch / Diabetes / Herzinsuffizienz ----
    lf = "LF8"
    add_item(lf, "chronisch", 1, _mcq(
        "Was kann im Umgang mit chronisch kranken Menschen besonders wichtig sein?",
        ["Ressourcen stärken und Selbstständigkeit unterstützen", "Alle Entscheidungen abnehmen, um zu entlasten", "Keine Gespräche führen", "Nur auf Symptome schauen"],
        "Ressourcen stärken und Selbstständigkeit unterstützen",
        "Aktivierend unterstützen und Bewältigungsstrategien berücksichtigen."
    ))
    add_item(lf, "diabetes", 2, _case_mcq(
        "Bei einer Person mit Diabetes sollst du unter Anleitung den Blutzucker messen.",
        "Was ist dabei wichtig?",
        ["Messwert dokumentieren und Auffälligkeiten weiterleiten", "Messwert geheim halten", "Immer sofort Insulin spritzen ohne Rücksprache", "Nur schätzen statt messen"],
        "Messwert dokumentieren und Auffälligkeiten weiterleiten",
        "Dokumentation und Weiterleitung an Pflegefachkraft sind zentral."
    ))
    add_item(lf, "herzinsuff", 2, _mcq(
        "Herzinsuffizienz bedeutet am ehesten…",
        ["Das Herz kann den Körper nicht ausreichend mit Blut versorgen", "Die Lunge produziert zu viel Schleim", "Die Haut ist entzündet", "Ein Knochen ist gebrochen"],
        "Das Herz kann den Körper nicht ausreichend mit Blut versorgen",
        "Herzinsuffizienz = unzureichende Pumpfunktion."
    ))
    add_item(lf, "medikamente", 3, _short(
        "Wie würdest du Nebenwirkungen von Medikamenten beobachten und weiterleiten? Nenne 4 Punkte.",
        rubric="Beispiele: Symptome beschreiben (was/wann/wie stark), Vitalzeichen, zeitlicher Zusammenhang, Dokumentation, sofortige Weiterleitung bei Warnzeichen.",
        keywords=["doku", "vital", "zeit", "symptom", "weiter", "beob"]
    ))

    # ---- LF2/3/9/10: light but usable ----
    lf = "LF2"
    add_item(lf, "vitalzeichen", 1, _match(
        "Ordne Vitalzeichen ↔ Beispiel",
        left=["Puls", "Atmung", "Temperatur", "Blutdruck"],
        right=["z.B. 80/min", "z.B. 16/min", "z.B. 37,2 °C", "z.B. 120/80 mmHg"],
        solution={"Puls": "z.B. 80/min", "Atmung": "z.B. 16/min", "Temperatur": "z.B. 37,2 °C", "Blutdruck": "z.B. 120/80 mmHg"},
        explanation="Grundlagen für Beobachtung und Dokumentation."
    ))
    add_item(lf, "infekt_prophylaxe", 2, _case_mcq(
        "Ein Patient hat hohes Fieber, Schüttelfrost und Luftnot.",
        "Welche Erkrankung ist als Möglichkeit naheliegend und muss ärztlich abgeklärt werden?",
        ["Pneumonie", "Arthrose", "Intertrigo", "Inkontinenz"],
        "Pneumonie",
        "Akut mit Fieber/Schüttelfrost und Luftnot: mögliche Pneumonie – weiterleiten."
    ))

    lf = "LF3"
    add_item(lf, "lebensmittelhygiene", 1, _tf(
        "Getrennte Schneidebretter für rohes Fleisch und Brot/Gemüse senken das Infektionsrisiko.",
        True,
        "Kreuzkontamination vermeiden."
    ))
    add_item(lf, "haushalt_org", 2, _mcq(
        "Was unterstützt eine gute Arbeitsorganisation am ehesten?",
        ["Material und Schritte vorab planen", "Alles spontan machen", "Mehrfach unterbrechen", "Dokumentation weglassen"],
        "Material und Schritte vorab planen",
        "Planung und klare Abläufe sparen Zeit und erhöhen Sicherheit."
    ))

    lf = "LF9"
    add_item(lf, "demenz_kommunikation", 2, _mcq(
        "Was ist im Kontakt mit Menschen mit Demenz häufig hilfreich?",
        ["Kurze Sätze, klare Struktur, wertschätzender Ton", "Ironie und viele Themenwechsel", "Laut werden bei Widerstand", "Nur mit Angehörigen reden"],
        "Kurze Sätze, klare Struktur, wertschätzender Ton",
        "Kommunikation anpassen, Sicherheit geben."
    ))

    lf = "LF10"
    add_item(lf, "palliativ", 1, _tf(
        "Palliative Begleitung bedeutet immer, 'nichts mehr zu tun'.",
        False,
        "Palliativ heißt: Lebensqualität, Symptomlinderung, Begleitung – aktiv und bedürfnisorientiert."
    ))
    add_item(lf, "angehoerige", 2, _short(
        "Welche 3 Dinge kannst du Angehörigen in einer belastenden Situation anbieten (ohne falsche Versprechen)?",
        rubric="Beispiele: zuhören, Informationen weitergeben/Ansprechpersonen nennen, ruhigen Raum anbieten, praktische Unterstützung organisieren, Präsenz.",
        keywords=["zuhör", "raum", "info", "ansprech", "unterstütz", "da"]
    ))


# -----------------------------
# DB
# -----------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY,
        created_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS diag_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        lf TEXT,
        area TEXT,
        level INTEGER,
        score REAL,
        max_score REAL,
        created_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS practice_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        lf TEXT,
        area TEXT,
        level INTEGER,
        qtype TEXT,
        correct INTEGER,
        created_at TEXT
    )
    """)
    conn.commit()

def ensure_student(conn: sqlite3.Connection, student_id: str):
    cur = conn.cursor()
    cur.execute("SELECT student_id FROM students WHERE student_id=?", (student_id,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO students(student_id, created_at) VALUES (?,?)", (student_id, datetime.utcnow().isoformat()))
        conn.commit()

def log_diag(conn: sqlite3.Connection, student_id: str, lf: str, area: str, level: int, score: float, max_score: float):
    conn.execute(
        "INSERT INTO diag_attempts(student_id, lf, area, level, score, max_score, created_at) VALUES (?,?,?,?,?,?,?)",
        (student_id, lf, area, level, score, max_score, datetime.utcnow().isoformat()),
    )
    conn.commit()

def log_practice(conn: sqlite3.Connection, student_id: str, lf: str, area: str, level: int, qtype: str, correct: bool):
    conn.execute(
        "INSERT INTO practice_attempts(student_id, lf, area, level, qtype, correct, created_at) VALUES (?,?,?,?,?,?,?)",
        (student_id, lf, area, level, qtype, 1 if correct else 0, datetime.utcnow().isoformat()),
    )
    conn.commit()

# -----------------------------
# Adaptive helpers
# -----------------------------

LEVEL_LABEL = {1: "Basis", 2: "Sicher", 3: "Prüfungsnah"}

def choose_diag_level(prev_ratio: Optional[float]) -> int:
    """Adaptive step-up/down: start at 2, go down if very low, up if very high."""
    if prev_ratio is None:
        return 2
    if prev_ratio >= 0.8:
        return 3
    if prev_ratio <= 0.4:
        return 1
    return 2

def compute_recommendation(conn: sqlite3.Connection, student_id: str, lf: str) -> Dict[str, int]:
    """Per area: use latest diag ratio to recommend practice level."""
    rec: Dict[str, int] = {}
    for a in LF_AREAS[lf]:
        area = a["key"]
        row = conn.execute(
            "SELECT score, max_score FROM diag_attempts WHERE student_id=? AND lf=? AND area=? ORDER BY id DESC LIMIT 1",
            (student_id, lf, area)
        ).fetchone()
        ratio = None
        if row and row["max_score"]:
            ratio = float(row["score"]) / float(row["max_score"])
        rec[area] = choose_diag_level(ratio)
    return rec

def pick_questions(lf: str, area: str, level: int, n: int) -> List[Dict[str, Any]]:
    pool = QUESTION_BANK.get(lf, {}).get(area, {}).get(level, [])
    if not pool:
        # fall back: any level in that area
        for alt in (2, 1, 3):
            pool = QUESTION_BANK.get(lf, {}).get(area, {}).get(alt, [])
            if pool:
                break
    if not pool:
        return []
    return random.sample(pool, k=min(n, len(pool)))

# -----------------------------
# UI: styling
# -----------------------------

def inject_css():
    st.markdown("""
    <style>
      .app-hero{
        padding: 18px 18px 14px 18px;
        border-radius: 18px;
        background: linear-gradient(135deg, rgba(46,125,50,.12), rgba(33,150,243,.10));
        border: 1px solid rgba(0,0,0,.06);
        margin-bottom: 14px;
      }
      .badge{
        display:inline-block;
        padding:2px 10px;
        border-radius:999px;
        border:1px solid rgba(0,0,0,.10);
        font-size:12px;
        margin-right:8px;
        background: rgba(255,255,255,.6);
      }
      .card{
        border: 1px solid rgba(0,0,0,.08);
        border-radius: 16px;
        padding: 14px 14px 10px 14px;
        background: rgba(255,255,255,.55);
      }
      .muted{ color: rgba(0,0,0,.6); }
      .tiny{ font-size: 12px; color: rgba(0,0,0,.55); }
      .hr{ height:1px; background:rgba(0,0,0,.08); margin:10px 0 12px 0;}
    </style>
    """, unsafe_allow_html=True)

def header(step: str, lf_label: str = ""):
    st.markdown(f"""
    <div class="app-hero">
      <div class="badge">{step}</div>
      <div class="badge">{lf_label}</div>
      <div style="font-size:26px; font-weight:750; margin-top:6px;">{APP_TITLE}</div>
      <div class="muted">{APP_SUBTITLE}</div>
    </div>
    """, unsafe_allow_html=True)

# -----------------------------
# Render question types
# -----------------------------

def render_item(item: Dict[str, Any], key_prefix: str) -> Tuple[bool, float, float]:
    """
    Returns: (submitted, score, max_score) for this single item.
    """
    qtype = item["type"]
    st.markdown(f"<div class='card'><div class='tiny'>{qtype.upper()}</div>", unsafe_allow_html=True)
    if qtype == "case_mcq":
        st.markdown(f"**Fall:** {item['stem']}")
        st.write(item["q"])
        choice = st.radio("Antwort", item["options"], key=f"{key_prefix}_choice")
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            correct = (choice == item["answer"])
            st.success("Richtig ✅" if correct else "Noch nicht ❌")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, 1.0 if correct else 0.0, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "mcq":
        st.write(item["q"])
        choice = st.radio("Antwort", item["options"], key=f"{key_prefix}_choice")
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            correct = (choice == item["answer"])
            st.success("Richtig ✅" if correct else "Noch nicht ❌")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, 1.0 if correct else 0.0, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "multi":
        st.write(item["q"])
        selected = st.multiselect("Wähle alle passenden Antworten", item["options"], key=f"{key_prefix}_sel")
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            gold = set(item["answers"])
            got = set(selected)
            correct = (gold == got)
            # partial credit
            score = len(gold & got) - len(got - gold)
            score = max(0.0, float(score)) / float(max(1, len(gold)))
            st.success("Perfekt ✅" if correct else "Teilweise ✅/❌")
            st.write(f"Punkte: {score:.2f} / 1.00")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, score, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "tf":
        st.write(item["q"])
        choice = st.radio("Wahr oder Falsch?", ["Wahr", "Falsch"], key=f"{key_prefix}_tf")
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            got = (choice == "Wahr")
            correct = (got == item["answer"])
            st.success("Richtig ✅" if correct else "Noch nicht ❌")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, 1.0 if correct else 0.0, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "cloze":
        st.write(item["q"])
        if item.get("hints"):
            st.caption("Hinweise: " + ", ".join(item["hints"]))
        ans = st.text_input("Deine Antwort", key=f"{key_prefix}_cloze")
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            gold = str(item["answer"]).strip().lower()
            got = str(ans).strip().lower()
            correct = (gold == got)
            # allow contains for longer answers
            if not correct and (gold in got or got in gold) and len(gold) >= 6:
                correct = True
            st.success("Richtig ✅" if correct else f"Noch nicht ❌ (Lösung: {item['answer']})")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, 1.0 if correct else 0.0, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "order":
        st.write(item["q"])
        st.caption("Ziehe die Reihenfolge gedanklich – hier wählst du die Reihenfolge über Dropdowns.")
        items = item["items"]
        chosen = []
        cols = st.columns(min(5, len(items)))
        for i in range(len(items)):
            with cols[i % len(cols)]:
                chosen.append(st.selectbox(f"Schritt {i+1}", ["—"] + items, key=f"{key_prefix}_s{i}"))
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            got = [x for x in chosen if x != "—"]
            # score by position match
            sol = item["solution"]
            m = sum(1 for i, x in enumerate(got[:len(sol)]) if i < len(sol) and x == sol[i])
            score = float(m) / float(len(sol))
            correct = (got == sol)
            st.success("Richtig ✅" if correct else "Fast ✅/❌")
            st.write(f"Punkte: {score:.2f} / 1.00")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, score, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "match":
        st.write(item["q"])
        st.caption("Ordne rechts passende Begriffe zu.")
        left = item["left"]
        right = item["right"]
        sol = item["solution"]
        chosen = {}
        for l in left:
            chosen[l] = st.selectbox(l, ["—"] + right, key=f"{key_prefix}_{l}")
        submitted = st.button("Antwort prüfen", key=f"{key_prefix}_check")
        if submitted:
            m = sum(1 for l in left if chosen.get(l) == sol.get(l))
            score = float(m) / float(len(left))
            correct = (m == len(left))
            st.success("Richtig ✅" if correct else "Teilweise ✅/❌")
            st.write(f"Punkte: {score:.2f} / 1.00")
            if item.get("explanation"):
                st.info(item["explanation"])
            st.markdown("</div>", unsafe_allow_html=True)
            return True, score, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    if qtype == "short":
        st.write(item["q"])
        ans = st.text_area("Deine Antwort (Stichpunkte reichen)", key=f"{key_prefix}_short")
        submitted = st.button("Antwort speichern", key=f"{key_prefix}_check")
        if submitted:
            # heuristic keyword match
            kw = [k.lower() for k in item.get("keywords", [])]
            got = ans.lower()
            hits = sum(1 for k in kw if k in got)
            score = 0.0
            if kw:
                score = min(1.0, hits / max(3, min(6, len(kw))))
            st.success("Gespeichert ✅")
            st.caption("Rückmeldung (automatisch, grob):")
            st.write(f"Punkte: {score:.2f} / 1.00")
            st.info("Musterlösung / Erwartung:\n\n" + item.get("rubric", ""))
            st.markdown("</div>", unsafe_allow_html=True)
            return True, score, 1.0
        st.markdown("</div>", unsafe_allow_html=True)
        return False, 0.0, 1.0

    st.markdown("</div>", unsafe_allow_html=True)
    st.warning(f"Unbekannter Aufgabentyp: {qtype}")
    return False, 0.0, 1.0


# -----------------------------
# App flow
# -----------------------------

def page_student(conn: sqlite3.Connection):
    header("Schüler:innenmodus", st.session_state.get("lf_label", ""))

    # Step 1: student id
    with st.sidebar:
        st.subheader("Profil")
        student_id = st.text_input("Kürzel (z.B. GPA12-07)", value=st.session_state.get("student_id", ""))
        if student_id:
            st.session_state["student_id"] = student_id.strip()
            ensure_student(conn, st.session_state["student_id"])
        st.markdown("<div class='hr'></div>", unsafe_allow_html=True)

        # Step 2: LF selection
        st.subheader("Lernfeld")
        lf = st.selectbox("Wähle dein Lernfeld", LEARN_FIELDS, format_func=lambda x: f"{x[0]} – {x[1]}", index=0)
        st.session_state["lf"] = lf[0]
        st.session_state["lf_label"] = f"{lf[0]} – {lf[1]}"

        st.subheader("Navigation")
        step = st.radio("Schritt", ["1) Lernstand", "2) Aufgaben"], index=0)
        st.session_state["step"] = step

    if not st.session_state.get("student_id"):
        st.info("Bitte zuerst ein Kürzel eintragen (Sidebar).")
        return

    lf_code = st.session_state["lf"]
    areas = LF_AREAS[lf_code]

    if st.session_state["step"].startswith("1"):
        st.markdown("### 1) Lernstandserhebung (kurz, je Bereich)")
        st.caption("Du machst pro Bereich 1–2 Aufgaben. Danach bekommst du passende Übungsaufgaben.")

        # Choose an area to diagnose
        area_label_map = {a["label"]: a["key"] for a in areas}
        area_label = st.selectbox("Bereich auswählen", list(area_label_map.keys()))
        area_key = area_label_map[area_label]

        # determine adaptive level based on latest result
        row = conn.execute(
            "SELECT score, max_score FROM diag_attempts WHERE student_id=? AND lf=? AND area=? ORDER BY id DESC LIMIT 1",
            (st.session_state["student_id"], lf_code, area_key)
        ).fetchone()
        ratio = None
        if row and row["max_score"]:
            ratio = float(row["score"]) / float(row["max_score"])
        level = choose_diag_level(ratio)

        st.markdown(f"<div class='card'><b>Diagnostik-Level:</b> {LEVEL_LABEL[level]} (Stufe {level})</div>", unsafe_allow_html=True)
        items = pick_questions(lf_code, area_key, level, n=2)

        if not items:
            st.warning("Für diesen Bereich sind noch keine Aufgaben hinterlegt. (Im Prototyp ergänzbar.)")
            return

        total_score, total_max = 0.0, 0.0
        submitted_any = False
        for i, it in enumerate(items):
            submitted, score, mx = render_item(it, key_prefix=f"diag_{lf_code}_{area_key}_{i}")
            if submitted:
                submitted_any = True
                total_score += score
                total_max += mx

        if submitted_any:
            if st.button("Diagnostik-Ergebnis speichern", key=f"save_diag_{lf_code}_{area_key}_{level}"):
                log_diag(conn, st.session_state["student_id"], lf_code, area_key, level, total_score, total_max)
                st.success(f"Gespeichert. Ergebnis: {total_score:.2f}/{total_max:.2f}")

        st.markdown("### Überblick Lernstand (dieses Lernfeld)")
        rec = compute_recommendation(conn, st.session_state["student_id"], lf_code)
        for a in areas:
            k = a["key"]
            row = conn.execute(
                "SELECT score, max_score, created_at FROM diag_attempts WHERE student_id=? AND lf=? AND area=? ORDER BY id DESC LIMIT 1",
                (st.session_state["student_id"], lf_code, k)
            ).fetchone()
            if row and row["max_score"]:
                ratio = float(row["score"]) / float(row["max_score"])
                st.markdown(
                    f"<div class='card'><b>{a['label']}</b><br>"
                    f"<span class='muted'>Letztes Ergebnis:</span> {ratio:.0%} &nbsp; • &nbsp; "
                    f"<span class='muted'>Empfohlen:</span> {LEVEL_LABEL[rec[k]]}</div>",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"<div class='card'><b>{a['label']}</b><br><span class='muted'>Noch keine Diagnostik.</span></div>",
                    unsafe_allow_html=True
                )

    else:
        st.markdown("### 2) Passende Aufgaben")
        rec = compute_recommendation(conn, st.session_state["student_id"], lf_code)

        area_label_map = {a["label"]: a["key"] for a in areas}
        area_label = st.selectbox("Bereich auswählen", ["Empfohlen (gemischt)"] + list(area_label_map.keys()))
        if area_label.startswith("Empfohlen"):
            # mix 1 item per area, at recommended level
            bundle: List[Tuple[str, Dict[str, Any]]] = []
            for a in areas:
                level = rec[a["key"]]
                items = pick_questions(lf_code, a["key"], level, n=1)
                if items:
                    bundle.append((a["key"], items[0]))
            random.shuffle(bundle)
        else:
            area_key = area_label_map[area_label]
            level = rec[area_key]
            picked = pick_questions(lf_code, area_key, level, n=3)
            bundle = [(area_key, it) for it in picked]

        if not bundle:
            st.warning("Noch keine Aufgaben in diesem Bereich vorhanden.")
            return

        st.markdown(f"<div class='card'><b>Dein Übungs-Level:</b> {LEVEL_LABEL[ rec[bundle[0][0]] if bundle else 2 ]}</div>", unsafe_allow_html=True)

        for i, (area_key, it) in enumerate(bundle):
            st.markdown(f"<div class='tiny'>Bereich: {next(a['label'] for a in areas if a['key']==area_key)}</div>", unsafe_allow_html=True)
            submitted, score, mx = render_item(it, key_prefix=f"prac_{lf_code}_{area_key}_{i}")
            if submitted:
                correct = (score >= 0.999)
                log_practice(conn, st.session_state["student_id"], lf_code, area_key, rec[area_key], it["type"], correct)

        st.caption("Tipp: Wenn etwas schwer ist, mach im Schritt „Lernstand“ erst die Diagnostik in diesem Bereich.")


def page_teacher(conn: sqlite3.Connection):
    header("Lehrkraftmodus")

    st.markdown("### Übersicht (anonymisiert möglich)")
    st.caption("Prototyp: einfache Auswertung. Für echten Einsatz: Rollen/Passwort + DSGVO-Konzept ergänzen.")

    # Simple filter
    lf = st.selectbox("Lernfeld", LEARN_FIELDS, format_func=lambda x: f"{x[0]} – {x[1]}", index=3)
    lf_code = lf[0]
    areas = LF_AREAS[lf_code]

    # Latest diag per student x area
    students = [r["student_id"] for r in conn.execute("SELECT student_id FROM students ORDER BY student_id").fetchall()]
    if not students:
        st.info("Noch keine Daten vorhanden. Sobald Schüler:innen starten, erscheint hier die Übersicht.")
        return

    area_names = {a["key"]: a["label"] for a in areas}

    rows = []
    for sid in students:
        for a in areas:
            row = conn.execute(
                "SELECT score, max_score, created_at FROM diag_attempts WHERE student_id=? AND lf=? AND area=? ORDER BY id DESC LIMIT 1",
                (sid, lf_code, a["key"])
            ).fetchone()
            if row and row["max_score"]:
                ratio = float(row["score"]) / float(row["max_score"])
                rows.append({
                    "Schüler:in": sid,
                    "Bereich": area_names[a["key"]],
                    "Quote": ratio,
                    "Zeit": row["created_at"][:19].replace("T", " "),
                })

    if not rows:
        st.warning("Zu diesem Lernfeld gibt es noch keine Diagnostikdaten.")
        return

    # Render as simple table without pandas dependency
    rows_sorted = sorted(rows, key=lambda x: (x["Schüler:in"], x["Bereich"]))
    st.dataframe(rows_sorted, use_container_width=True, hide_index=True)

    st.markdown("### Häufige Übungsaktivitäten")
    prac = conn.execute(
        "SELECT lf, area, qtype, SUM(correct) as correct, COUNT(*) as total FROM practice_attempts WHERE lf=? GROUP BY lf, area, qtype ORDER BY total DESC LIMIT 50",
        (lf_code,)
    ).fetchall()
    if prac:
        table = []
        for r in prac:
            label = area_names.get(r["area"], r["area"])
            total = int(r["total"])
            corr = int(r["correct"])
            table.append({
                "Bereich": label,
                "Aufgabentyp": r["qtype"],
                "Versuche": total,
                "Richtig": corr,
                "Quote": (corr / total) if total else 0.0,
            })
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.caption("Noch keine Übungsdaten vorhanden.")


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🩺", layout="wide")
    inject_css()

    # seed bank once
    if "bank_seeded" not in st.session_state:
        seed_questions()
        st.session_state["bank_seeded"] = True

    conn = db()
    init_db(conn)

    with st.sidebar:
        st.subheader("Modus")
        mode = st.radio("", ["Schüler:in", "Lehrkraft"], index=0)
        st.markdown("<div class='hr'></div>", unsafe_allow_html=True)
        st.caption("Prototyp – lokal/Streamlit Cloud")

    if mode == "Schüler:in":
        page_student(conn)
    else:
        page_teacher(conn)


if __name__ == "__main__":
    main()
