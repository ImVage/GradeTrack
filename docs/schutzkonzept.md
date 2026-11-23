# Schutzkonzept GradeTrack

GradeTrack verwaltet Prüfungsnoten. Studierende tragen Noten ein, das Prüfungsamt bestätigt
sie. Schützenswert sind vor allem die Integrität der Noten, Passwörter und API-Tokens sowie
die persönlichen Daten der Studierenden. Wie die App aufgebaut ist, steht im
[README](../README.md).

Vertiefen werden wir **Code Security** und **Dynamisches Testing**.

Pro Feld sind unten die Kriterien aus der Aufgabenstellung aufgeführt. Angehakt ist, was wir
umsetzen.

---

## 1. Building von Artefakten (mind. 1)

- [x] Das Repository beschreibt Build/Packaging in der Dokumentation.
- [x] Im Repository befindet sich ein Skript, das Build/Packaging maschinell durchführen
  kann. Die Nutzung des Skripts ist dokumentiert.
- [ ] *Vertiefung:* Ein Merge in einen Deployment-Branch baut und veröffentlicht das
  Artefakt automatisch.

**Warum das für uns wichtig ist:** Solange jeder die App bei sich selbst einrichtet, läuft sie
überall ein bisschen anders: andere Python-Version, andere Pakete, andere Einstellungen.
Fehler lassen sich dann schwer nachvollziehen, und getestet wird nicht unbedingt das, was
später läuft.

**Was wir machen:** Wir bauen GradeTrack als Docker-Image. Ein Skript erzeugt das Image mit
einem Befehl, und das README beschreibt, wie man es baut und startet. Das Image läuft als
normaler Benutzer statt als root und enthält keine Secrets. So testen und betreiben alle
exakt denselben Stand.

---

## 2. Code Security (mind. 1) – Vertiefung

- [x] Eingaben werden früh validiert und folgen dem „Fail Fast“-Prinzip. Zusätzlich nutzt
  das Repository automatisiert einen statischen Type Checker.
- [x] Die Anwendung setzt explizit sichere Defaults und behandelt mögliche Fehler explizit
  und sicher.
- [x] SAST und Secret Scanning werden automatisiert ausgeführt.
- [x] *Vertiefung:* Alle drei Punkte sind erfüllt, der Datenfluss ist dokumentiert, und für
  jedes Scan-Tool sowie für Fail Fast gibt es einen Positivtest.

**Warum das für uns wichtig ist:** Hier liegt bei GradeTrack das größte Risiko. Die App nimmt
viele Eingaben entgegen, schreibt in eine Datenbank und unterscheidet zwei Rollen. Im
Ausgangsstand stecken SQL-Injection, hartkodierte Secrets, schwach gehashte Passwörter und
fehlende Rechteprüfungen. Ein Student könnte so fremde Noten sehen, seine eigenen Noten
selbst bestätigen oder an die Tokens des Prüfungsamts kommen.

**Was wir machen:** Alle Eingaben werden am Eingang geprüft, und Ungültiges wird sofort
abgelehnt statt „repariert“. Ein Type Checker prüft den Code bei jedem Commit. Secrets
kommen aus Umgebungsvariablen, der Debug-Modus ist standardmäßig aus, und Fehler gehen nicht
mehr als Stacktrace an den Nutzer. SAST und Secret Scanning laufen automatisch vor jedem
Commit und in der CI, damit Lücken auffallen, bevor sie in `main` landen. Den Datenfluss
dokumentieren wir mit einem Diagramm. Für jedes Tool zeigen wir an unserem unsicheren
Ausgangsstand (Branch `vulnerable`), dass es ein echtes Problem findet.

---

## 3. Build & Supply Chain (mind. 2)

- [x] *(Immer Pflicht)* Genutzte Software-Versionen werden mit Release-Tag und Prüfsumme
  oder Commit-Hash referenziert.
- [ ] Eine SBOM wird automatisiert erzeugt und ist im oder über das Repository vorzeigbar.
- [x] Abhängigkeiten werden auf bekannte Sicherheitslücken geprüft.
- [ ] Ein Werkzeug unterstützt on-demand den automatisierten Update-Prozess von
  Abhängigkeiten.
- [ ] *Vertiefung:* Alle Punkte sind erfüllt, und die Doku verweist auf die Nachweise.

**Warum das für uns wichtig ist:** GradeTrack besteht nicht nur aus unserem Code, sondern
auch aus fremden Paketen wie Flask, Werkzeug und Jinja2. Wird eines davon manipuliert oder
hat es eine bekannte Lücke, betrifft uns das direkt, ohne dass wir selbst einen Fehler
gemacht haben. Ohne feste Versionen weiß außerdem niemand genau, was installiert ist.

**Was wir machen:** Alle Python-Pakete stehen mit exakter Version und SHA-256-Prüfsumme im
Lock-File `requirements.txt` und werden nur mit Hash-Prüfung installiert. Ein nachträglich
verändertes Paket fällt so sofort auf. Das Docker-Base-Image pinnen wir per Digest und die
GitHub Actions per Commit-SHA. Zusätzlich prüft die CI unsere Abhängigkeiten auf bekannte
Sicherheitslücken.

---

## 4. Logging & Betrieb (mind. 1)

- [x] Die Anwendung schreibt strukturierte, maschinenlesbare Logs in STDOUT oder eine Datei.
- [x] Für die Hauptanwendung ist ein sinnvoller Health Check konfiguriert.
- [ ] Ein separates Health-Check-Skript unterscheidet HEALTHY und UNHEALTHY.
- [ ] *Vertiefung:* Logs werden ausgewertet, um Verfügbarkeit und Fehlerquote zu ermitteln.

**Warum das für uns wichtig ist:** Im Ausgangsstand gibt GradeTrack nur unstrukturierte
`print`-Meldungen aus, und darin stehen sogar Klartext-Passwörter und Tokens. Gleichzeitig
meldet `/health` immer „ok“, auch wenn die Datenbank gar nicht erreichbar ist. Ob die App
wirklich funktioniert und wer wann was geändert hat, lässt sich so nicht nachvollziehen.

**Was wir machen:** Die App schreibt Logs als JSON nach STDOUT, mit Zeitpunkt, Ereignis,
Benutzer und Statuscode, aber ohne Passwörter oder Tokens. Damit lassen sich Logs von
Monitoring-Tools einlesen und Änderungen an Noten nachvollziehen. Der Health Check prüft
auch die Datenbankverbindung, und Docker nutzt ihn, um einen hängenden Container zu
erkennen.

---

## 5. Dynamisches Testing (mind. 1) – Vertiefung

- [x] Automatisierte Anwendungstests prüfen korrekte Funktionalität bei Codeänderungen und
  scheitern nachweislich bei einer fehlerhaften Änderung.
- [x] DAST kann bei Bedarf automatisiert ausgeführt werden. Zwei Positivtests zeigen, dass
  zwei verschiedenartige Probleme mit Schweregrad mindestens medium erkannt werden.
- [x] *Vertiefung:* Beide Punkte sind erfüllt, und im Repository liegt ein lesbarer Bericht
  des letzten Test- bzw. DAST-Laufs.

**Warum das für uns wichtig ist:** Manche Fehler sieht man erst, wenn die App läuft, etwa ob
ein Student wirklich keine fremden Noten abrufen kann oder ob eine Suchanfrage die Datenbank
manipuliert. Außerdem ändern wir im Rahmen von Code Security viel am Code. Ohne Tests merken
wir nicht, wenn dabei etwas kaputtgeht.

**Was wir machen:** Automatische Tests prüfen bei jeder Änderung die wichtigsten Funktionen
und vor allem die Rechte: Ein Student darf keine Noten bestätigen, keine fremden Noten sehen
und keine Tokens abrufen. Mit einem absichtlich fehlerhaften Pull Request zeigen wir, dass
die Tests dann anschlagen. Zusätzlich greift ein DAST-Scan mit OWASP ZAP die laufende App
an. Gegen den unsicheren Branch `vulnerable` findet er zwei verschiedene Lücken, zum
Beispiel SQL-Injection und XSS, und schlägt fehl. Gegen `main` läuft er durch. Der Bericht
des letzten Laufs liegt lesbar im Repository.

---

## Warum diese zwei Vertiefungen

Code Security und Dynamisches Testing ergänzen sich. Code Security findet Schwachstellen im
Quellcode, bevor die App läuft. Dynamisches Testing greift die laufende App an und zeigt,
was von außen tatsächlich ausnutzbar ist. Beide nutzen denselben unsicheren Ausgangsstand
für ihre Positivtests. So können wir für dieselben Lücken zeigen: Sie werden gefunden, sie
werden behoben, und die Tests halten den Fix fest.
