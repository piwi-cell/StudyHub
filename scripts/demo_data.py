"""Legt Beispieldaten für die Demo an (ILIAS_SYNC_HOME, standardmäßig ./demo-data).

Die PDFs entstehen mit dem macOS-Druckfilter aus Text, damit die KI echten Inhalt hat.
Bereits vorhandene Daten bleiben unverändert.
"""

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path(os.environ.get("ILIAS_SYNC_HOME") or Path(__file__).resolve().parent.parent / "demo-data")
MIRROR = HOME / "Spiegel"

COURSES = {
    "ACC 300 Introduction to Financial Accounting [V] (HWS 2026)": "Financial Accounting",
    "VWL 101 Mikroökonomik A [V] (HWS 2026)": "Mikroökonomik A",
    "STA 201 Statistik I [V] (HWS 2026)": "Statistik I",
    "License Information": "License Information",
}

DOCS = {
    "Financial Accounting/Vorlesung/03 Die Bilanz.pdf": """Introduction to Financial Accounting - Vorlesung 3: Die Bilanz

1. Zweck der Bilanz
Die Bilanz ist eine Gegenüberstellung von Vermögen (Aktiva) und Kapital (Passiva) zu einem
Stichtag. Sie zeigt, welche Mittel ein Unternehmen besitzt (Mittelverwendung) und wie diese
finanziert sind (Mittelherkunft). Grundgleichung: Aktiva = Passiva, bzw.
Assets = Liabilities + Equity.

2. Aktivseite
Anlagevermögen: Vermögensgegenstände, die dem Geschäftsbetrieb dauerhaft dienen
(z. B. Grundstücke, Maschinen, Patente). Umlaufvermögen: Vermögensgegenstände, die
kurzfristig umgeschlagen werden (Vorräte, Forderungen aus Lieferungen und Leistungen,
Kasse und Bankguthaben). Die Gliederung erfolgt nach zunehmender Liquidität (HGB § 266).

3. Passivseite
Eigenkapital: gezeichnetes Kapital, Kapitalrücklage, Gewinnrücklagen, Jahresüberschuss.
Fremdkapital: Rückstellungen (ungewisse Verbindlichkeiten, z. B. Pensionsrückstellungen)
und Verbindlichkeiten (gegenüber Kreditinstituten, aus Lieferungen und Leistungen).
Die Gliederung erfolgt nach zunehmender Fristigkeit.

4. Bilanzveränderungen
Aktivtausch: Ein Aktivposten nimmt zu, ein anderer ab (Kauf einer Maschine bar).
Passivtausch: Umwandlung einer kurzfristigen Verbindlichkeit in ein Darlehen.
Aktiv-Passiv-Mehrung (Bilanzverlängerung): Kauf von Waren auf Ziel.
Aktiv-Passiv-Minderung (Bilanzverkürzung): Begleichung einer Verbindlichkeit per Bank.

5. Kennzahlen
Eigenkapitalquote = Eigenkapital / Gesamtkapital. Anlagendeckungsgrad I =
Eigenkapital / Anlagevermögen. Goldene Bilanzregel: Langfristiges Vermögen soll durch
langfristiges Kapital finanziert sein.

Beispiel: Die Muster GmbH hat Anlagevermögen von 600.000 EUR, Umlaufvermögen von
400.000 EUR, Eigenkapital von 350.000 EUR. Eigenkapitalquote = 35 %.
Anlagendeckungsgrad I = 58,3 %.

Prüfungshinweis: Bilanzveränderungen an Beispielen erkennen und Kennzahlen berechnen können.
""",
    "Financial Accounting/Übung/Übungsblatt 3.pdf": """Übungsblatt 3 - Bilanzveränderungen

Aufgabe 1: Ordnen Sie die folgenden Geschäftsvorfälle den vier Arten von
Bilanzveränderungen zu und geben Sie die betroffenen Bilanzposten an.
a) Kauf eines Firmenwagens für 30.000 EUR per Banküberweisung.
b) Aufnahme eines Bankdarlehens über 50.000 EUR, Gutschrift auf dem Bankkonto.
c) Ein Kunde begleicht eine Forderung über 4.000 EUR bar.
d) Eine Lieferantenverbindlichkeit über 10.000 EUR wird in ein Darlehen umgewandelt.
e) Tilgung eines Darlehens über 5.000 EUR per Bank.

Aufgabe 2: Berechnen Sie für die Beispiel AG die Eigenkapitalquote und den
Anlagendeckungsgrad I. Anlagevermögen 1,2 Mio. EUR, Umlaufvermögen 0,8 Mio. EUR,
Eigenkapital 0,9 Mio. EUR, langfristiges Fremdkapital 0,5 Mio. EUR.
Ist die goldene Bilanzregel erfüllt? Begründen Sie.
""",
    "Mikroökonomik A/Vorlesung/05 Marktgleichgewicht.pdf": """Mikroökonomik A - Kapitel 5: Marktgleichgewicht und Wohlfahrt

5.1 Gleichgewicht
Im Wettbewerbsmarkt bestimmt der Schnittpunkt von Angebots- und Nachfragekurve den
Gleichgewichtspreis p* und die Gleichgewichtsmenge q*. Bei p > p* entsteht ein
Angebotsüberschuss, bei p < p* ein Nachfrageüberschuss.
Beispiel: Nachfrage q = 100 - 2p, Angebot q = 3p - 25. Gleichgewicht: 100 - 2p = 3p - 25,
also p* = 25 und q* = 50.

5.2 Konsumenten- und Produzentenrente
Konsumentenrente (KR): Fläche zwischen Nachfragekurve und Preis, die Differenz zwischen
Zahlungsbereitschaft und tatsächlichem Preis. Produzentenrente (PR): Fläche zwischen
Preis und Angebotskurve. Gesamtwohlfahrt W = KR + PR. Im Beispiel: KR = 0,5 * 50 * (50 - 25)
= 625, PR = 0,5 * 50 * (25 - 8,33) = 416,7.

5.3 Eingriffe in den Markt
Höchstpreis unter p*: Nachfrageüberschuss, Rationierung, Wohlfahrtsverlust.
Mindestpreis über p*: Angebotsüberschuss. Mengensteuer t: Keil zwischen Konsumentenpreis
und Produzentenpreis; die Steuerlast tragen beide Seiten je nach Elastizität. Die Seite mit
der geringeren Preiselastizität trägt den größeren Teil der Steuerlast.
Der Wohlfahrtsverlust (Deadweight Loss) entspricht dem Harberger-Dreieck.

5.4 Elastizitäten
Preiselastizität der Nachfrage e = (dq/dp) * (p/q). Im Gleichgewicht des Beispiels:
e = -2 * 25/50 = -1 (einheitselastisch).
""",
    "Statistik I/Vorlesung/07 Hypothesentests.pdf": """Statistik I - Vorlesung 7: Hypothesentests

1. Grundidee
Ein Hypothesentest prüft anhand einer Stichprobe, ob eine Annahme über die Grundgesamtheit
(Nullhypothese H0) verworfen werden kann. Die Alternativhypothese H1 ist das, was man
zeigen möchte.

2. Fehlerarten
Fehler 1. Art (alpha-Fehler): H0 wird verworfen, obwohl sie wahr ist. Wahrscheinlichkeit
= Signifikanzniveau alpha, üblich 5 % oder 1 %. Fehler 2. Art (beta-Fehler): H0 wird
beibehalten, obwohl sie falsch ist. Die Teststärke (Power) ist 1 - beta.

3. Vorgehen
(1) H0 und H1 formulieren, (2) Signifikanzniveau festlegen, (3) Teststatistik wählen,
(4) kritischen Wert oder p-Wert bestimmen, (5) Entscheidung treffen und interpretieren.
p-Wert: Wahrscheinlichkeit, unter H0 ein mindestens so extremes Ergebnis zu beobachten.
H0 wird verworfen, wenn p-Wert < alpha.

4. Einstichproben-t-Test
Teststatistik t = (x_quer - mu0) / (s / sqrt(n)), t-verteilt mit n - 1 Freiheitsgraden.
Beispiel: n = 25, x_quer = 103, s = 10, mu0 = 100. t = 3 / 2 = 1,5. Kritischer Wert
(zweiseitig, alpha = 5 %, df = 24): 2,064. Da 1,5 < 2,064, wird H0 nicht verworfen.

5. Einseitig vs. zweiseitig
Zweiseitig: H1: mu != mu0. Einseitig: H1: mu > mu0 oder mu < mu0. Einseitige Tests haben
bei gleichem alpha eine höhere Power in der getesteten Richtung.
""",
}

LOG = [
    "ILIAS: abgeglichen, 0 neu, 0 geändert",
    "ILIAS: abgeglichen, 2 neu, 0 geändert",
    "Zielordner: 2 Dateien kopiert",
    "ILIAS: abgeglichen, 2 neu, 0 geändert",
    "Zielordner: 2 Dateien kopiert",
]


def make_pdf(text: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as source:
        source.write(text)
    with open(target, "wb") as out:
        subprocess.run(["cupsfilter", "-i", "text/plain", "-m", "application/pdf", source.name],
                       stdout=out, stderr=subprocess.DEVNULL, check=True)
    os.unlink(source.name)


def main() -> None:
    if (HOME / "config.json").exists():
        return
    HOME.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for number, (relative, text) in enumerate(DOCS.items()):
        path = MIRROR / relative
        make_pdf(text, path)
        os.utime(path, (now - number * 9000, now - number * 9000))
    config = {
        "uni_id": "demo", "target_dir": str(HOME / "Zielordner"), "interval_minutes": 30,
        "include_new_courses": True, "goodnotes": False, "telegram": False, "notion": {},
        "courses": {title: {"name": name, "sync": not title.startswith("License"),
                            "url": f"https://ilias.uni-mannheim.de/goto.php?target=crs_{n}", "group": False}
                    for n, (title, name) in enumerate(COURSES.items(), 1)},
    }
    (HOME / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    logs = HOME / "Logs"
    logs.mkdir(exist_ok=True)
    start = datetime.now() - timedelta(hours=len(LOG))
    (logs / "ILIAS-Sync.log").write_text(
        "".join(f"{start + timedelta(hours=i):%Y-%m-%d %H:%M:%S}  {line}\n" for i, line in enumerate(LOG)), encoding="utf-8")
    print(f"Demo-Daten angelegt: {HOME}")


if __name__ == "__main__":
    main()
