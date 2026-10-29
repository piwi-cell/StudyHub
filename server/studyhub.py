"""Daten für die StudyHub-Oberfläche (ui/studyhub) im Format der Mock-Daten (ui/studyhub/js/daten.js).

overview() baut aus Kursen, Dateien, KI-Ergebnissen, Tutor-Statistik und Lernplan-Status
genau die Struktur von DATEN und MODUL_DETAILS in ui/studyhub/js/daten.js. Die Oberfläche
kann die Mock-Daten damit 1:1 ersetzen.

Alle Texte sind HTML-maskiert, weil StudyHub sie direkt als HTML einsetzt (Dateinamen und
KI-Antworten dürfen kein Markup einschleusen). Formeln bekommen danach <sub>/<sup> für _ und ^.
"""

import html
import re
import time
import unicodedata
from pathlib import PurePosixPath

import ai
import cards as cardstore
import core
import uploads

STATE_FILE = core.APP_DIR / "studyhub.json"
EXAM_FILE = core.APP_DIR / "klausuren.json"  # Kursordner → Klausurdatum (YYYY-MM-DD), von Hand eingetragen
HIDDEN_FILE = core.APP_DIR / "ausgeblendet.json"  # relativer Pfad → Zeitpunkt; nur in der App ausgeblendet
STATUS = ("offen", "inArbeit", "erledigt", "nochmal")
NEU_TAGE = 3
SEMESTER = re.compile(r"\((HWS|FSS|HS|FS|WS|SS|WT|ST)\s*(\d{2,4})\)")
HERBST = {"HWS", "HS", "WS", "WT"}  # zweite Jahreshälfte
UEBUNG = re.compile(r"tutori|übung|uebung|aufgabe|exercise|tutorial|blatt", re.IGNORECASE)
VORLESUNG = re.compile(r"vorlesung|folien|skript|lecture|slides", re.IGNORECASE)

esc = html.escape


# --- Lernplan-Status (pro Datei: status, notiz) -------------------------------


def load_state() -> dict:
    return core.load_json(STATE_FILE, {})


def set_state(path: str, status: str | None = None, notiz: str | None = None) -> dict:
    state = load_state()
    entry = state.setdefault(path, {"status": "offen", "notiz": ""})
    if status is not None:
        if status not in STATUS:
            raise ValueError(f"Unbekannter Status {status}")
        entry["status"] = status
    if notiz is not None:
        entry["notiz"] = notiz[:2000]
    core.save_json(STATE_FILE, state)
    return entry


# --- In der App ausgeblendete Dateien (bleiben im Spiegel, im Zielordner und beim Abgleich) ------


def hidden_files() -> dict[str, float]:
    return core.load_json(HIDDEN_FILE, {})


def set_hidden(path: str, hidden: bool) -> None:
    files = hidden_files()
    if hidden:
        files[core.nfc(path)] = time.time()
    else:
        files.pop(core.nfc(path), None)
    core.save_json(HIDDEN_FILE, files)


def load_exams() -> dict:
    return core.load_json(EXAM_FILE, {})


def set_exam(course: str, date: str | None) -> dict:
    """Klausurdatum eines Kurses setzen (YYYY-MM-DD) oder mit None/"" löschen."""
    exams = load_exams()
    course = core.nfc(course)
    if date:
        try:
            time.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Datum bitte als JJJJ-MM-TT") from None
        exams[course] = date
    else:
        exams.pop(course, None)
    core.save_json(EXAM_FILE, exams)
    return exams


def _exam(date: str | None, now: float) -> dict | None:
    """{"datum", "tage"} für eine heutige oder künftige Klausur, sonst None."""
    if not date:
        return None
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    days = round((time.mktime(time.strptime(date, "%Y-%m-%d")) - time.mktime(time.strptime(today, "%Y-%m-%d")))
                 / 86400)
    return {"datum": date, "tage": days} if days >= 0 else None


# --- Eigene Zusammenfassungen ---------------------------------------------------

OWN_MAX_CHARS = 30_000  # so viel Text einer eigenen Zusammenfassung zeigt StudyHub
_own_texts: dict[str, tuple[float, int, str]] = {}  # Pfad → (mtime, Größe, Text): PDFs nicht bei jedem Laden lesen


def own_text(relative: str) -> str:
    """Text einer eigenen Zusammenfassung (Markdown, Text, PDF, Word, PowerPoint); leer, wenn unlesbar."""
    path = core.MIRROR_DIR / relative
    try:
        stat = path.stat()
    except OSError:
        return ""
    known = _own_texts.get(relative)
    if known and known[:2] == (stat.st_mtime, stat.st_size):
        return known[2]
    try:
        pages = ai.extract_pages(path)
    except ai.AIError:
        pages = []
    text = "\n\n".join(p.strip() for p in pages if p.strip())[:OWN_MAX_CHARS]
    _own_texts[relative] = (stat.st_mtime, stat.st_size, text)
    return text


def own_html(text: str) -> str:
    """Markdown-artige eigene Notizen: Überschriften fett, Absätze und Aufzählungen bleiben."""
    return paragraphs(re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", text, flags=re.MULTILINE))


# --- Hilfen -------------------------------------------------------------------


def slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "kurs"


def semester_of(title: str) -> tuple[str, int] | None:
    """("HWS 2026", Sortierschlüssel) aus einem ILIAS-Kurstitel."""
    match = SEMESTER.search(title)
    if not match:
        return None
    term, year = match.group(1), int(match.group(2))
    year = year + 2000 if year < 100 else year
    # ILIAS schreibt dasselbe Semester unterschiedlich (HWS, WT, WS …): eine Gruppe je Halbjahr
    herbst = term in HERBST
    return f"{'HWS' if herbst else 'FSS'} {year}", year * 2 + (1 if herbst else 0)


def formula(text: str) -> str:
    """Maskiert und macht aus x_n / x^2 / x_{ab} tief- bzw. hochgestellten Text."""
    out = esc(text)
    out = re.sub(r"_\{([^}]+)\}|_([\w]+)", lambda m: f"<sub>{m.group(1) or m.group(2)}</sub>", out)
    return re.sub(r"\^\{([^}]+)\}|\^([\w−+-]+)", lambda m: f"<sup>{m.group(1) or m.group(2)}</sup>", out)


def inline(text: str) -> str:
    """Maskiert Markdown-Text und übernimmt nur **fett**."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text.strip()))


def paragraphs(text: str) -> str:
    """Wie inline(), behält aber Absätze (Leerzeile) und Aufzählungen ("- …" → "• …") aus längeren Texten."""
    blocks = [block for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    return "<br><br>".join(
        "<br>".join(f"• {inline(_bullet(line))}" if re.match(r"^\s*[-*•]\s+", line) else inline(line)
                    for line in block.splitlines() if line.strip())
        for block in blocks)


def markdown_sections(markdown: str) -> dict[str, list[str]]:
    """'## Überschrift' → Zeilen darunter (ohne Leerzeilen)."""
    sections, current = {}, ""
    for line in markdown.splitlines():
        if heading := re.match(r"^#{1,4}\s+(.*)", line):
            current = heading.group(1).strip().lower()
            sections[current] = []
        elif line.strip():
            sections.setdefault(current, []).append(line.strip())
    return sections


def _section(sections: dict, *keywords: str) -> list[str]:
    for heading, lines in sections.items():
        if any(k in heading for k in keywords):
            return lines
    return []


def _bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line)


def from_summary(markdown: str) -> dict:
    """Notlösung, solange es kein strukturiertes Thema gibt: Abschnitte der Markdown-Zusammenfassung."""
    sections = markdown_sections(markdown)
    idea = " ".join(_section(sections, "worum")) or ""
    points = [_bullet(line) for line in _section(sections, "kernaussage")][:4]
    terms = []
    for line in _section(sections, "begriff"):
        name, sep, text = _bullet(line).replace("**", "").partition(":")
        if sep and name.strip() and text.strip():
            terms.append({"name": name.strip(), "text": text.strip()})
    exam = [_bullet(line) for line in _section(sections, "prüfung", "pruefung", "klausur")][:2]
    kernidee = inline(idea) + "".join(f"<br>• {inline(p)}" for p in points)
    return {"kernidee": kernidee, "terms": terms, "falle": "<br>".join(inline(e) for e in exam)}


# --- Aufbau -------------------------------------------------------------------


def _group_order(folder: str) -> tuple[int, str]:
    if not folder or VORLESUNG.search(folder):
        return 0, folder
    return (1 if "tutori" in folder.lower() else 2 if UEBUNG.search(folder) else 3), folder


def overview(config: dict, files: list[dict], ai_entries: dict[str, dict], tutor_stats: dict[str, dict],
             state: dict, now: float | None = None, karten: dict | None = None, exams: dict | None = None,
             hidden: list[dict] | None = None) -> dict:
    """files: wie /api/files; ai_entries: Pfad → KI-Cache-Eintrag; tutor_stats: Kursordner → tutor.stats();
    karten: Lernstand und eigene Karten (cards.load()); exams: Kursordner → Klausurdatum;
    hidden: ausgeblendete Dateien (wie files), nur zum Wieder-Einblenden im Tab „Dokumente“."""
    now = now or time.time()
    karten = karten or {"reviews": {}, "imported": {}}
    exams = exams or {}

    # Module = Kursordner (Übungsgruppen liegen als Unterordner darin), Semester aus dem ILIAS-Titel
    semester_by_name, modules = {}, {}
    for title, settings in config.get("courses", {}).items():
        name = settings["name"].split("/")[0]
        if settings.get("group") or "/" in settings["name"]:
            continue
        if settings.get("sync"):
            modules.setdefault(name, [])
        if sem := semester_of(title):
            semester_by_name[name] = sem
    for f in files:
        modules.setdefault(f["course"], []).append(f)

    ids, details, module_rows = {}, {}, {}
    for name in sorted(modules, key=str.casefold):
        base, n = slug(name), 2
        module_id = base
        while module_id in ids.values():
            module_id, n = f"{base}-{n}", n + 1
        ids[name] = module_id
        details[module_id], module_rows[name] = _module(name, module_id, modules[name], ai_entries,
                                                        tutor_stats.get(name, {}), state, now, karten,
                                                        _exam(exams.get(core.nfc(name)), now))
        details[module_id]["ausgeblendet"] = []
    for f in sorted(hidden or [], key=lambda f: f["name"].casefold()):
        if f["course"] in ids:
            details[ids[f["course"]]]["ausgeblendet"].append(
                {"pfad": f["path"], "name": esc(f["name"]), "ordner": esc(f["folder"] or "Allgemein")})

    # Semester gruppieren: das neueste ist "aktuell", Kurse ohne erkennbares Semester gehören dazu
    keys = {sem for sem in semester_by_name.values()}
    current = max(keys, key=lambda s: s[1]) if keys else ("Meine Kurse", 0)
    groups: dict[tuple, list] = {}
    for name in module_rows:
        groups.setdefault(semester_by_name.get(name, current), []).append(module_rows[name])
    semester = [
        {"id": slug(sem[0]), "name": sem[0], "status": "aktuell" if sem == current else "abgeschlossen",
         "module": groups[sem]}
        for sem in sorted(groups, key=lambda s: -s[1])
    ]

    uni_id = config.get("uni_id") or ""
    # Klausurtermine kennt ILIAS nicht; sie werden in StudyHub von Hand eingetragen
    upcoming = sorted((row["klausur"]["tage"], ids[name]) for name, row in module_rows.items() if row["klausur"])
    daten = {
        "nutzer": {"vorname": esc(uni_id or "du"), "initialen": esc((uni_id[:2] or "SH").upper())},
        "naechsteKlausur": {"modulId": upcoming[0][1], "tage": upcoming[0][0]} if upcoming else None,
        "heuteDran": _today(module_rows, ids),
        "semester": semester,
    }
    return {"daten": daten, "details": details}


def _card(cid: str, source: str, front: str, back: str, karten: dict, now: float, **extra) -> dict:
    return {"id": cid, "frage": esc(front), "antwort": esc(back), "formel": {"text": ""}, "quelle": esc(source),
            **cardstore.state_of(karten["reviews"].get(cid), now), **extra}


def _module(name: str, module_id: str, files: list[dict], ai_entries: dict, stats: dict, state: dict,
            now: float, karten: dict, klausur: dict | None) -> tuple[dict, dict]:
    files = sorted(files, key=lambda f: (_group_order(f["folder"]), f["name"].casefold()))
    status = {f["path"]: state.get(f["path"], {}) for f in files}

    def entry(f: dict, nr: str) -> dict:
        s = status[f["path"]]
        return {"id": f["path"], "nr": nr, "titel": esc(PurePosixPath(f["name"]).stem),
                "status": s.get("status", "offen"), "notiz": esc(s.get("notiz", ""))}

    # Lernplan: Vorlesungsordner als Kapitel, Tutorien/Übungen als Bereiche mit Aufgaben
    kapitel, bereiche, dokumente = [], [], []
    folders: dict[str, list] = {}
    for f in files:
        folders.setdefault(f["folder"], []).append(f)
    i = 0
    for folder, group in sorted(folders.items(), key=lambda kv: _group_order(kv[0])):
        label = esc(folder or "Allgemein")
        if folder == uploads.SUMMARY_FOLDER:
            pass  # eigene Zusammenfassungen sind Lernhilfen, keine Lernplan-Einträge
        elif UEBUNG.search(folder or ""):
            art = "Tutorium" if "tutori" in folder.lower() else "Übung"
            bereiche.append({"id": f"{module_id}-{slug(folder)}", "art": art, "titel": label,
                             "aufgaben": [entry(f, f"A{n}") for n, f in enumerate(group, 1)]})
        else:
            i += 1
            kapitel.append({"nr": i, "titel": label,
                            "eintraege": [entry(f, f"{i}.{n}") for n, f in enumerate(group, 1)]})
        dokumente.append({"gruppe": label, "dateien": [{
            "name": esc(f["name"]), "pfad": f["path"], "datum": time.strftime("%Y-%m-%d", time.localtime(f["mtime"])),
            "seiten": None, "groesse": f["size"], "typ": esc(f["ext"].upper() or "Datei"),
            "zusammengefasst": bool(f["ai"]["summary"]) or bool((ai_entries.get(f["path"]) or {}).get("thema")),
            "neu": now - f["mtime"] < NEU_TAGE * 86400,
        } for f in group]})

    all_entries = [e for k in kapitel for e in k["eintraege"]] + [a for b in bereiche for a in b["aufgaben"]]
    count = {s: sum(1 for e in all_entries if e["status"] == s) for s in STATUS}
    gesamt = len(all_entries)
    basis = {"erledigt": count["erledigt"], "gesamt": gesamt, "nochmal": count["nochmal"],
             "offen": gesamt - count["erledigt"] - count["nochmal"]}

    # Themen (Zusammenfassung) und Karten aus den KI-Ergebnissen, in Lernplan-Reihenfolge
    themen, stapel, glossar = [], [], []
    for f in files:
        ai = ai_entries.get(f["path"]) or {}
        thema = (ai.get("thema") or {}).get("output")
        summary = (ai.get("summary") or {}).get("output")
        cards = ((ai.get("flashcards") or {}).get("output") or {}).get("cards", [])
        own = f["folder"] == uploads.SUMMARY_FOLDER
        if not (thema or summary or cards or own):
            continue
        nr = len(themen) + 1
        stem = esc(PurePosixPath(f["name"]).stem)
        st = status[f["path"]].get("status", "offen")
        stand = {"erledigt": "sitzt", "nochmal": "unsicher", "inArbeit": "unsicher"}.get(st, "offen")
        fallback = from_summary(summary) if summary else {"kernidee": "", "terms": [], "falle": ""}
        if thema:
            formeln = [{"name": esc(x["name"]), "text": formula(x["text"])} for x in thema.get("formeln", [])][:5]
            seite = thema.get("seite")
        else:
            formeln = [{"name": esc(t["name"]), "text": esc(t["text"])} for t in fallback["terms"]][:5]
            seite = None
        if own:  # eigene Zusammenfassung: der eigene Text statt KI-Auswertung
            text = own_text(f["path"])
            themen.append({
                "nr": nr, "titel": stem, "stand": "sitzt", "eigene": True,
                "kernidee": own_html(text) if text else "Text nicht lesbar: Datei mit „Original öffnen“ ansehen.",
                "einfacher": "", "formeln": [], "falle": "", "quelle": f"Meine Zusammenfassung · {esc(f['name'])}",
                "pfad": f["path"], "strukturiert": False, "zusammenfassung": True,
            })
            stapel += [_card(cardstore.card_id(f["path"], c["front"]), f["name"], c["front"], c["back"], karten,
                             now, thema=nr, lernplan=None, pfad=f["path"]) for c in cards]
            continue
        themen.append({
            "nr": nr, "titel": esc(thema["titel"]) if thema else stem, "stand": stand,
            "kernidee": paragraphs(thema["kernidee"]) if thema else (fallback["kernidee"] or
                                                                     "Noch keine Zusammenfassung für dieses Dokument."),
            "einfacher": paragraphs(thema["einfacher"]) if thema else "",
            "formeln": formeln,
            "falle": paragraphs(thema["falle"]) if thema else fallback["falle"],
            "quelle": f"{esc(f['name'])}, S. {seite}" if seite else esc(f["name"]),
            "pfad": f["path"], "strukturiert": bool(thema), "zusammenfassung": bool(summary),
        })
        glossar += [{"begriff": esc(t["name"]), "text": esc(t["text"])} for t in fallback["terms"]]
        stapel += [_card(cardstore.card_id(f["path"], c["front"]), f["name"], c["front"], c["back"], karten, now,
                         thema=nr, lernplan=f["path"], pfad=f["path"]) for c in cards]

    # Eigene Karten (Anki-Import, Textdatei) ohne Thema und ohne Lernplan-Eintrag
    stapel += [_card(c["id"], c["quelle"], c["front"], c["back"], karten, now, thema=0, lernplan=None, pfad=None)
               for c in cardstore.course_cards(name, karten)]
    # Fällige zuerst (wiederholte vor neuen), danach nach nächstem Termin
    stapel.sort(key=lambda k: (not k["faellig"], k["neu"], k["inTagen"]))
    faellig = sum(1 for k in stapel if k["faellig"])

    first = stapel[0] if stapel else None
    fortschritt = round(100 * basis["erledigt"] / gesamt) if gesamt else None
    neu = sum(1 for g in dokumente for d in g["dateien"] if d["neu"])
    info = (f"{faellig} Karten fällig" if faellig else "Zusammenfassung bereit" if themen
            else "Noch nicht gestartet" if gesamt else "Noch keine Dateien")
    row = {"id": module_id, "name": esc(name), "fortschritt": fortschritt, "info": info,
           "zeile": f"{basis['erledigt']} von {gesamt} Einträgen", "neu": neu, "kurs": name,
           "karten": faellig, "nochmal": stats.get("wrong", 0) + basis["nochmal"], "klausur": klausur}
    detail = {
        "zusammenfassungFertig": bool(themen),
        "lernplan": {"basis": basis, "kapitel": kapitel, "bereiche": bereiche},
        "dokumente": dokumente,
        "themen": themen,
        "karten": {"faellig": faellig, "gesamt": len(stapel),
                   "beispielFrage": first["frage"] if first else "Noch keine Karten",
                   "beispielThema": (f"Thema {first['thema']} · {themen[first['thema'] - 1]['titel']}"
                                     if first and first["thema"] else first["quelle"] if first else ""),
                   "runde": {"gewusst": 0, "nochmal": 0}, "liste": stapel,
                   "naechste": min((k["inTagen"] for k in stapel if not k["faellig"]), default=None)},
        "tutor": {"kurs": name, "fragen": stats.get("questions", 0), "beantwortet": stats.get("answered", 0),
                  "richtig": stats.get("correct", 0), "thema": themen[0]["nr"] if themen else None, "verlauf": []},
        "glossar": sorted({g["begriff"]: g for g in glossar}.values(), key=lambda g: g["begriff"].casefold()),
        "probeklausur": [],
    }
    return detail, row


def _today(rows: dict[str, dict], ids: dict[str, str]) -> list[dict]:
    """Chips für „Heute dran“: neue Dateien, fällige Karten, Wiederholen; höchstens drei."""
    chips = []
    for name, row in rows.items():
        if row["neu"]:
            dateien = "neue Datei" if row["neu"] == 1 else "neue Dateien"
            chips.append({"text": f"{row['neu']} {dateien} in {row['name']}", "modulId": ids[name],
                          "tab": "dokumente", "icon": "dokument"})
    for name, row in sorted(rows.items(), key=lambda kv: -kv[1]["karten"]):
        if row["karten"]:
            chips.append({"text": f"{row['karten']} Karteikarten fällig in {row['name']}", "modulId": ids[name],
                          "tab": "karteikarten", "icon": "karten"})
    for name, row in rows.items():
        if row["nochmal"]:
            chips.append({"text": f"{row['nochmal']}× nochmal üben in {row['name']}", "modulId": ids[name],
                          "tab": "lernplan", "icon": "wiederholen"})
    # Abwechslung: aus jeder Art zuerst eine
    ordered = sorted(chips, key=lambda c: ["dokument", "karten", "wiederholen"].index(c["icon"]))
    picked = []
    for icon in ("karten", "wiederholen", "dokument"):
        picked += [c for c in ordered if c["icon"] == icon][:1]
    picked += [c for c in ordered if c not in picked]
    return picked[:3]
