// =====================================================
// Beispieldaten (Mock-Daten) für die Demo.
// Später kommen diese Daten aus ILIAS bzw. von der KI.
// =====================================================

const DATEN = {
  nutzer: { vorname: "Alex", initialen: "AL" },

  naechsteKlausur: { modulId: "fima", tage: 23 },

  // "Heute dran"-Leiste auf der Startseite
  heuteDran: [
    { text: "12 Karteikarten fällig", modulId: "fima", tab: "karteikarten", icon: "karten" },
    { text: "Kapitel 3.6 wiederholen", modulId: "fima", tab: "lernplan", icon: "wiederholen" },
    { text: "Tutorium 5 ist neu", modulId: "fima", tab: "dokumente", icon: "dokument" },
  ],

  // Semester mit Modulen. fortschritt = Lernstand in Prozent (null = noch nicht gestartet)
  semester: [
    {
      id: "hws26",
      name: "HWS 2026",
      status: "aktuell",
      module: [
        { id: "fima", name: "Finanzmathematik", fortschritt: 24, info: "12 Karten fällig", zeile: "52 von 217 Einträgen", neu: 3 },
        { id: "stat1", name: "Statistik I", fortschritt: 41, info: "5 Karten fällig", zeile: "38 von 92 Einträgen", neu: 1 },
        { id: "mikro", name: "Mikroökonomik", fortschritt: 12, info: "Kapitel 2 wartet", zeile: "9 von 74 Einträgen", neu: 0 },
        { id: "winf", name: "Wirtschaftsinformatik", fortschritt: null, info: "Noch nicht gestartet", zeile: "Dokumente importiert", neu: 0 },
      ],
    },
    {
      id: "fss26",
      name: "FSS 2026",
      status: "abgeschlossen",
      module: [
        { id: "buchf", name: "Buchführung", fortschritt: 100, info: "Abgeschlossen", zeile: "Klausur bestanden", neu: 0 },
        { id: "mathe", name: "Mathematik für Ökonomen", fortschritt: 100, info: "Abgeschlossen", zeile: "Klausur bestanden", neu: 0 },
        { id: "bwl", name: "Einführung BWL", fortschritt: 100, info: "Abgeschlossen", zeile: "Klausur bestanden", neu: 0 },
      ],
    },
  ],
};

// Erzeugt die Aufgaben eines Tutoriums/einer Übung: Aufgabe 1 … n.
// Die ersten "erledigt" Aufgaben sind erledigt, Nummern in "nochmal" stehen auf "nochmal üben".
function aufgabenListe(bereichId, anzahl, erledigt, nochmal = []) {
  return Array.from({ length: anzahl }, (_, i) => {
    const nr = i + 1;
    let status = nr <= erledigt ? "erledigt" : "offen";
    if (nochmal.includes(nr)) status = "nochmal";
    return { id: `${bereichId}-${nr}`, nr: `A${nr}`, titel: `Aufgabe ${nr}`, status, notiz: "" };
  });
}

// Kurzschreibweise für einen Lernplan-Eintrag der Vorlesung
const eintrag = (nr, titel, status, notiz = "") => ({ id: nr, nr, titel, status, notiz });

// Ausführliche Daten pro Modul. Für die Demo ist nur Finanzmathematik ausgearbeitet.
const MODUL_DETAILS = {
  fima: {
    zusammenfassungFertig: true,

    // ---------- Lernplan ----------
    lernplan: {
      // Gesamtzahlen des ganzen Moduls (es sind nicht alle 217 Einträge unten ausgeschrieben)
      basis: { erledigt: 52, gesamt: 217, offen: 135, nochmal: 30 },

      kapitel: [
        {
          nr: 1, titel: "Grundlagen",
          eintraege: [
            eintrag("1.1", "Zahlungsströme", "offen"),
            eintrag("1.2", "Zeitrechnung", "erledigt"),
            eintrag("1.3", "Typische Finanzinstrumente", "erledigt"),
          ],
        },
        {
          nr: 2, titel: "Zeitwert des Geldes",
          eintraege: [
            eintrag("2.1", "Einführung", "erledigt"),
            eintrag("2.2", "Zinsen", "erledigt"),
            eintrag("2.3", "Endwert", "erledigt"),
            eintrag("2.4", "Barwert", "erledigt"),
            eintrag("2.5", "Unterjährige Verzinsung", "erledigt"),
            eintrag("2.6", "Kapitalwert", "erledigt"),
          ],
        },
        {
          nr: 3, titel: "Werte von Renten",
          eintraege: [
            eintrag("3.1", "Endwert einer Rente", "erledigt"),
            eintrag("3.2", "Barwert einer Rente", "erledigt"),
            eintrag("3.3", "Ewige Rente", "erledigt"),
            eintrag("3.4", "Wachsende Rente", "erledigt"),
            eintrag("3.5", "Annuitätendarlehen", "erledigt"),
            eintrag("3.6", "Fairer Preis eines Wertpapiers", "nochmal", "Kurs und fairen Preis verwechselt – Folie 31 nochmal ansehen."),
          ],
        },
        {
          nr: 4, titel: "Renditerechnung",
          eintraege: [
            eintrag("4.1", "Vergleichen von Renditen", "nochmal"),
            eintrag("4.2", "Interne Rendite", "nochmal"),
          ],
        },
      ],

      // Tutorien und Übungen: aufklappbare Zeilen mit Mini-Fortschrittsbalken
      bereiche: [
        { id: "tut1", art: "Tutorium", titel: "Tutorium 1 · Zahlungsströme", aufgaben: aufgabenListe("tut1", 5, 4) },
        { id: "tut2", art: "Tutorium", titel: "Tutorium 2 · Unterjährige Verzinsung", aufgaben: aufgabenListe("tut2", 5, 2, [3]) },
        { id: "tut3", art: "Tutorium", titel: "Tutorium 3 · Rentenrechnung", aufgaben: aufgabenListe("tut3", 9, 6, [7]) },
        { id: "ueb1", art: "Übung", titel: "Übung 1 · Bar- und Endwert", aufgaben: aufgabenListe("ueb1", 6, 6) },
        { id: "ueb2", art: "Übung", titel: "Übung 2 · Zinssätze & Kapitalwert", aufgaben: aufgabenListe("ueb2", 7, 4) },
        { id: "ueb4", art: "Übung", titel: "Übung 4 · Tilgung, Kurse, Unternehmenswert", aufgaben: aufgabenListe("ueb4", 18, 0) },
      ],
    },

    // ---------- Dokumente ----------
    dokumente: [
      {
        gruppe: "Vorlesung",
        dateien: [
          { name: "FiMa_Kap1_Grundlagen.pdf", datum: "2026-09-02", seiten: 24, zusammengefasst: true },
          { name: "FiMa_Kap2_Zeitwert_des_Geldes.pdf", datum: "2026-09-16", seiten: 38, zusammengefasst: true },
          { name: "FiMa_Kap3_Renten.pdf", datum: "2026-10-07", seiten: 42, zusammengefasst: true },
          { name: "FiMa_Kap4_Renditerechnung.pdf", datum: "2026-10-21", seiten: 31, neu: true },
        ],
      },
      {
        gruppe: "Tutorium",
        dateien: [
          { name: "Tutorium_1_Zahlungsstroeme.pdf", datum: "2026-09-10", seiten: 6 },
          { name: "Tutorium_2_Unterjaehrige_Verzinsung.pdf", datum: "2026-09-24", seiten: 7 },
          { name: "Tutorium_3_Rentenrechnung.pdf", datum: "2026-10-08", seiten: 9 },
          { name: "Tutorium_4_Annuitaeten.pdf", datum: "2026-10-15", seiten: 8 },
          { name: "Tutorium_5_Kursrechnung.pdf", datum: "2026-10-22", seiten: 7, neu: true },
        ],
      },
      {
        gruppe: "Übung & Zusatz",
        dateien: [
          { name: "Uebung_1_Bar_und_Endwert.pdf", datum: "2026-09-12", seiten: 4 },
          { name: "Uebung_2_Zinssaetze_Kapitalwert.pdf", datum: "2026-09-26", seiten: 5 },
          { name: "Uebung_3_Renten_Immobilienkauf.pdf", datum: "2026-10-10", seiten: 6 },
          { name: "Zusatzaufgaben_1.pdf", datum: "2026-10-12", seiten: 3 },
          { name: "Altklausur_HWS2025.pdf", datum: "2026-10-23", seiten: 12, neu: true },
        ],
      },
    ],

    // ---------- Zusammenfassung ----------
    // stand = Ampel: sitzt / unsicher / offen
    // Formeln: entweder "text" (darf <sub>/<sup> enthalten) oder "vor" + "bruch" [Zähler, Nenner]
    themen: [
      {
        nr: 1, titel: "Grundlagen", stand: "sitzt",
        kernidee: "Finanzmathematik bewertet Zahlungsströme: wer wann wie viel zahlt oder bekommt. Jeder Zahlungsstrom lässt sich als Zeitstrahl mit Ein- und Auszahlungen zeichnen. Erst wenn alle Zahlungen auf denselben Zeitpunkt gebracht sind, darf man sie vergleichen oder addieren.",
        einfacher: "Stell dir einen Zeitstrahl vor: Auf jedem Jahr steht, wie viel Geld rein- oder rausgeht. Rechnen darfst du erst, wenn alle Beträge auf denselben Tag umgerechnet sind.",
        formeln: [
          { name: "Aufzinsungsfaktor", text: "q = 1 + i" },
          { name: "Zinsen für ein Jahr", text: "Z = K · i" },
        ],
        falle: "Zeitpunkte genau lesen: „Ende Jahr 1“ ist t = 1, „Anfang Jahr 1“ ist t = 0.",
        quelle: "FiMa_Kap1_Grundlagen.pdf, Folie 6",
      },
      {
        nr: 2, titel: "Zeitwert des Geldes", stand: "sitzt",
        kernidee: "Ein Euro heute ist mehr wert als ein Euro morgen, weil er bis dahin Zinsen bringen kann. Aufzinsen bringt Beträge in die Zukunft, Abzinsen holt sie in die Gegenwart. Der Kapitalwert fasst alle Zahlungen einer Investition auf heute zusammen.",
        einfacher: "Geld wächst mit der Zeit durch Zinsen. Deshalb musst du Beträge aus verschiedenen Jahren erst „umrechnen“, bevor du sie vergleichst – wie Währungen.",
        formeln: [
          { name: "Endwert", text: "K<sub>n</sub> = K<sub>0</sub> · q<sup>n</sup>" },
          { name: "Barwert", vor: "K<sub>0</sub> =", bruch: ["K<sub>n</sub>", "q<sup>n</sup>"] },
          { name: "Kapitalwert", text: "C<sub>0</sub> = −A<sub>0</sub> + Σ Z<sub>t</sub> · q<sup>−t</sup>" },
        ],
        falle: "Bei unterjähriger Verzinsung den Zinssatz durch m teilen und die Laufzeit mit m multiplizieren.",
        quelle: "FiMa_Kap2_Zeitwert_des_Geldes.pdf, Folie 11",
      },
      {
        nr: 3, titel: "Werte von Renten", stand: "unsicher",
        kernidee: "Eine Rente ist eine Folge gleich hoher Zahlungen R in festen Abständen. Statt jede Zahlung einzeln auf- oder abzuzinsen, fasst ein Faktor alle n Zahlungen in einem Schritt zusammen. Hier gilt q = 1 + i und nachschüssige Zahlung, also immer am Periodenende.",
        einfacher: "Du bekommst zum Beispiel 10 Jahre lang jedes Jahresende 1.000 €. Der Barwert sagt, wie viel all diese Zahlungen heute zusammen wert sind – weniger als 10.000 €, weil spätere Zahlungen weniger wert sind. Der Rentenbarwertfaktor rechnet das in einem Schritt aus.",
        formeln: [
          { name: "Endwert einer Rente", vor: "EW = R ·", bruch: ["q<sup>n</sup> − 1", "q − 1"] },
          { name: "Barwert einer Rente", vor: "BW = R ·", bruch: ["q<sup>n</sup> − 1", "q<sup>n</sup> · (q − 1)"] },
          { name: "Ewige Rente", vor: "BW =", bruch: ["R", "i"] },
          { name: "Annuität", vor: "A = K<sub>0</sub> ·", bruch: ["q<sup>n</sup> · (q − 1)", "q<sup>n</sup> − 1"] },
        ],
        falle: "Bei vorschüssigen Zahlungen (am Periodenanfang) zusätzlich mit q multiplizieren.",
        quelle: "FiMa_Kap3_Renten.pdf, Folie 14",
      },
      {
        nr: 4, titel: "Renditerechnung", stand: "offen",
        kernidee: "Die Rendite misst, wie stark sich eine Geldanlage pro Jahr verzinst. Der interne Zinsfuß ist genau der Zinssatz, bei dem der Kapitalwert null wird. Um Anlagen mit unterschiedlicher Verzinsung zu vergleichen, rechnet man auf den Effektivzins um.",
        einfacher: "Die Rendite ist der „echte“ Jahreszins einer Anlage. Der interne Zinsfuß ist der Zinssatz, bei dem sich eine Investition gerade so lohnt – nicht mehr, nicht weniger.",
        formeln: [
          { name: "Interner Zinsfuß r", text: "0 = −A<sub>0</sub> + Σ Z<sub>t</sub> · (1 + r)<sup>−t</sup>" },
          { name: "Effektivzins", text: "i<sub>eff</sub> = (1 + i / m)<sup>m</sup> − 1" },
        ],
        falle: "Den internen Zinsfuß kann man meist nicht direkt auflösen: zwei Zinssätze ausprobieren und dazwischen interpolieren.",
        quelle: "FiMa_Kap4_Renditerechnung.pdf, Folie 9",
      },
    ],

    // ---------- Karteikarten ----------
    karten: {
      faellig: 12,
      gesamt: 24,
      beispielFrage: "Wie berechnet man den Barwert einer nachschüssigen Rente?",
      // Stand dieser Runde, bevor die Demo beginnt (→ „Karte 7 von 24“)
      runde: { gewusst: 4, nochmal: 2 },
      liste: [
        {
          thema: 3, lernplan: "3.2", quelle: "Kap. 3.2, Folie 14",
          frage: "Wie berechnet man den Barwert einer nachschüssigen Rente?",
          formel: { vor: "BW = R ·", bruch: ["q<sup>n</sup> − 1", "q<sup>n</sup> · (q − 1)"] },
          antwort: "Alle n Zahlungen R werden auf heute abgezinst und addiert. Der Bruch heißt Rentenbarwertfaktor.",
        },
        {
          thema: 3, lernplan: "3.3", quelle: "Kap. 3.3, Folie 18",
          frage: "Wie hoch ist der Barwert einer ewigen Rente?",
          formel: { vor: "BW =", bruch: ["R", "i"] },
          antwort: "Die Zahlungen laufen unendlich lange. Im Rentenbarwertfaktor geht qⁿ gegen unendlich, übrig bleibt 1 / i.",
        },
        {
          thema: 3, lernplan: "3.1", quelle: "Kap. 3.1, Folie 12",
          frage: "Was ändert sich, wenn eine Rente vorschüssig statt nachschüssig gezahlt wird?",
          formel: { text: "BW<sub>vor</sub> = BW<sub>nach</sub> · q" },
          antwort: "Jede Zahlung kommt eine Periode früher. Deshalb wird das Ergebnis zusätzlich mit q multipliziert.",
        },
        {
          thema: 3, lernplan: "3.5", quelle: "Kap. 3.5, Folie 27",
          frage: "Wie berechnet man die Annuität eines Darlehens?",
          formel: { vor: "A = K<sub>0</sub> ·", bruch: ["q<sup>n</sup> · (q − 1)", "q<sup>n</sup> − 1"] },
          antwort: "Die Annuität ist die gleichbleibende Rate aus Zins und Tilgung. Der Bruch heißt Annuitätenfaktor.",
        },
        {
          thema: 3, lernplan: "3.6", quelle: "Kap. 3.6, Folie 31",
          frage: "Wann ist der Preis eines Wertpapiers fair?",
          formel: { text: "Preis = Barwert aller künftigen Zahlungen" },
          antwort: "Wenn er genau dem Barwert aller künftigen Zinszahlungen plus Rückzahlung entspricht – abgezinst mit dem Marktzins.",
        },
        {
          thema: 2, lernplan: "2.3", quelle: "Kap. 2.3, Folie 9",
          frage: "Wie viel ist ein Kapital K₀ nach n Jahren wert?",
          formel: { text: "K<sub>n</sub> = K<sub>0</sub> · q<sup>n</sup>" },
          antwort: "Das Kapital wird n-mal mit dem Aufzinsungsfaktor q = 1 + i multipliziert (Zinseszins).",
        },
        {
          thema: 2, lernplan: "2.6", quelle: "Kap. 2.6, Folie 21",
          frage: "Wann lohnt sich eine Investition laut Kapitalwert?",
          formel: { text: "C<sub>0</sub> > 0" },
          antwort: "Wenn der Kapitalwert positiv ist: Die abgezinsten Rückflüsse sind größer als die Anfangsauszahlung.",
        },
        {
          thema: 4, lernplan: "4.2", quelle: "Kap. 4.2, Folie 9",
          frage: "Was ist der interne Zinsfuß?",
          formel: { text: "C<sub>0</sub>(r) = 0" },
          antwort: "Der Zinssatz, bei dem der Kapitalwert einer Investition genau null ist.",
        },
        {
          thema: 1, lernplan: "1.2", quelle: "Kap. 1.2, Folie 6",
          frage: "Wofür steht der Aufzinsungsfaktor q?",
          formel: { text: "q = 1 + i" },
          antwort: "Er gibt an, auf das Wievielfache ein Betrag in einer Periode wächst.",
        },
      ],
    },

    // ---------- Sprachtutor ----------
    // Vorgefertigtes Demo-Gespräch (ohne laufende App); mit App spricht der Sprachtutor.
    tutor: {
      thema: 3,
      verlauf: [
        { von: "tutor", text: "Hallo Alex! Wir wiederholen Thema 3, Werte von Renten. Erste Frage: Was ist der Unterschied zwischen dem Endwert und dem Barwert einer Rente?" },
        { von: "du", text: "Der Endwert ist, was alle Zahlungen am Ende wert sind. Der Barwert ist, was sie heute wert sind." },
        { von: "tutor", text: "Genau richtig! Nächste Frage: Du bekommst fünf Jahre lang am Jahresende 1.000 Euro, der Zins liegt bei 5 Prozent. Wie berechnest du den Barwert?" },
        { von: "du", text: "Ich nehme den Rentenbarwertfaktor, also q hoch 5 minus 1 durch q hoch 5 mal q minus 1, und multipliziere mit 1.000." },
        { von: "tutor", text: "Sehr gut, das ergibt rund 4.329 Euro. Achtung, typische Klausurfalle: Kämen die Zahlungen am Jahresanfang, müsstest du noch mit q multiplizieren. Ich lege dir dazu eine Karteikarte an." },
      ],
    },

    // ---------- Daten für Skills, die man über „+“ hinzufügen kann ----------
    glossar: [
      { begriff: "Annuität", text: "Gleichbleibende Rate aus Zins und Tilgung eines Darlehens." },
      { begriff: "Barwert", text: "Wert künftiger Zahlungen heute, also abgezinst auf t = 0." },
      { begriff: "Effektivzins", text: "Tatsächlicher Jahreszins, wenn unterjährig verzinst wird." },
      { begriff: "Endwert", text: "Wert aller Zahlungen am Ende der Laufzeit, aufgezinst auf t = n." },
      { begriff: "Interner Zinsfuß", text: "Zinssatz, bei dem der Kapitalwert genau null ist." },
      { begriff: "Kapitalwert", text: "Summe aller abgezinsten Ein- und Auszahlungen einer Investition." },
      { begriff: "Rentenbarwertfaktor", text: "Faktor, der n gleich hohe Zahlungen in einem Schritt auf heute abzinst." },
    ],
    probeklausur: [
      { punkte: 8, thema: 2, text: "Ein Kapital von 5.000 € wird 6 Jahre zu 3 % angelegt. Berechnen Sie den Endwert." },
      { punkte: 12, thema: 3, text: "Ein Sparer zahlt 10 Jahre lang jeweils am Jahresende 1.200 € ein (i = 4 %). Wie hoch ist der Endwert?" },
      { punkte: 14, thema: 3, text: "Ein Darlehen über 200.000 € wird in 20 Jahren annuitätisch getilgt (i = 3,5 %). Bestimmen Sie die Annuität." },
      { punkte: 16, thema: 4, text: "Bestimmen Sie den internen Zinsfuß einer Investition mit A₀ = 10.000 € und Rückflüssen von 6.000 € in t = 1 und t = 2." },
    ],
  },
};

// Katalog der Skills, die man über „+“ hinzufügen kann.
// brauchtZusammenfassung = ausgegraut, solange es noch keine Zusammenfassung gibt
const SKILL_KATALOG = [
  { id: "probeklausur", name: "Probeklausur", icon: "probeklausur", text: "Klausurnahe Aufgaben mit Punkten und Lösungsweg.", nutzt: "nutzt Zusammenfassung + Altklausuren", brauchtZusammenfassung: true },
  { id: "formelsammlung", name: "Formelsammlung", icon: "formel", text: "Alle Formeln des Moduls auf einen Blick.", nutzt: "nutzt Zusammenfassung", brauchtZusammenfassung: true },
  { id: "mindmap", name: "Mindmap", icon: "mindmap", text: "Themen und Zusammenhänge als Übersicht.", nutzt: "nutzt Zusammenfassung", brauchtZusammenfassung: true },
  { id: "glossar", name: "Glossar", icon: "glossar", text: "Fachbegriffe kurz und verständlich erklärt.", nutzt: "nutzt Zusammenfassung", brauchtZusammenfassung: true },
  { id: "uebungsaufgaben", name: "Übungsaufgaben", icon: "lernplan", text: "Aufgaben aus Übungen und Tutorien gesammelt.", nutzt: "nutzt Dokumente", brauchtZusammenfassung: false },
];
