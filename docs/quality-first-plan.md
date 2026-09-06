# Qualitätsorientierter Entwicklungs- und Abnahmeplan

Stand: Entwicklungsmeilenstein v0.12.0. Dieses Dokument ist ein Arbeits- und Messplan, kein Live-Testbericht.

## Verbindliche Prioritäten

Ergebnisqualität vor Zuverlässigkeit, danach Geschwindigkeit und Tokenverbrauch. Weniger Tokens oder weniger Skills sind kein Erfolg, wenn Pflichtinformationen fehlen, Vorgaben verletzt werden oder mehr Nacharbeit entsteht. Keine neue Architektur ohne belegte Lücke; funktionierende Bestandteile weiterverwenden.

Vor jeder Aufgabe den tatsächlichen `main`-Stand, die zuletzt bearbeiteten Branches und offene PRs lesen. Frühere Berichte sind Hinweise. Funktionen getrennt als implementiert, commitbezogen getestet und im echten Betrieb nachgewiesen bewerten.

Neue Arbeitsbranches enthalten die Zielversion, beispielsweise `feat/v0.12.0-readiness-pipeline`; eine separate spätere Funktion erhält einen neuen versionierten Branch. Nicht auf bereits gemergten Branches weiterarbeiten. Nicht gemergte Vorarbeiten zuerst vergleichen und bewusst als Basis einbeziehen; keine parallele Arbeit überschreiben. Kein Force-Push. Manifest, Paket, Runtime, Skills und aktuelle Dokumentationsmarker gemeinsam aktualisieren; historische Versionen und unabhängige Formatversionen bleiben erhalten.

## 1. Readiness-Datenweg — aktueller Repository-Schritt

**Bestätigt am Ausgangsstand:** Der Scan erzeugte Readiness-2.0-Felder, die in neuen und wiederverwendeten Plänen verloren gingen. Setup wurde als Namensliste geliefert, aber als Objektliste angezeigt. Strukturierte Zusammenfassungen wurden als beliebige Dictionaries ausgegeben. Gleicher Katalog-Hash verhinderte die Ergänzung alter Snapshots.

**Umsetzung v0.12.0:** Gemeinsame Übernahme passiver Prüfdaten; Ergänzung alter Snapshots aus einem tatsächlichen regulären Scan; Aktualisierung unabhängig von Modell-Metadaten; Kennzeichnung ausgelassener Details bei Speicherverdichtung; kompatible Setup- und sichere Zählerdarstellung. Bestehende Readiness-Auswertung, Policy und Lifecycle-Mechanismen werden nicht neu gebaut.

**Abnahme im Repository:** Scan -> Plan -> Speicherung -> erneutes Laden -> inspect/Doctor -> Policy; Fälle ready, unknown, setup_required, dependency_missing; geänderte Voraussetzungen; Skill-Aktualisierung und Entfernung; keine zusätzliche Analyse bei unverändertem Skill-Inhalt; bestehendes Scan-Intervall; keine Konfigurationswerte in den geprüften Ausgaben. CI-Belege werden dem exakten Commit im PR zugeordnet. Ein echter Hermes-Lauf bleibt offen.

## 2. Native Skill-Nutzung ergänzen — offen

**Befund:** Der aktuelle Prompt verlangt bei jeder Empfehlung `skill_view` für alle gelisteten Skills. Tatsächliche unnötige Doppelaufrufe sind noch nicht im Live-Betrieb gemessen.

Bereits geladene und noch im Kontext vorhandene Skills berücksichtigen, Wiederladen nach Aktualisierung oder Kontextkompression weiterhin erlauben. Keine zweite konkurrierende Auswahl und keine widersprüchlichen Anweisungen. Bei Router-Ausfall, Timeout oder Deaktivierung die native Skill-Nutzung erhalten. Zusätzliche relevante Skills und Informationen dürfen jederzeit nachgeladen werden; Router-Metadaten sind keine Erlaubnis, Sicherheit, Benutzerwünsche oder Freigaben zu überschreiben.

**Abnahme:** Gezielte Fehler- und Wiederladefälle mit echten Hermes-Hooks; keine unnötigen Doppelaufrufe; kein Verlust berechtigter nativer Fähigkeiten; Sicherheits- und Freigabeprüfungen unverändert.

## 3. Vollständige Auswahl und Unsicherheit — offen

**Befund:** Runtime und Policy begrenzen derzeit eine Auswahl auf höchstens fünf Skills. Diese Grenze wird nicht innerhalb des Readiness-Fixes geändert.

Eine zurückhaltende Erstauswahl mit begründetem Nachladen prüfen. Notwendige Abhängigkeiten nicht still abschneiden; komplexe Aufgaben abschnittsweise vollständig bearbeiten. Irrelevante Zusatzskills vermeiden, aber einen relevanten unknown-Skill nicht allein wegen einer unpassenden ready-Alternative verdrängen. Explizite Wünsche berücksichtigen und fehlende Voraussetzungen erklären. Ressourcen-/Schleifenschutz beibehalten; nicht einfach unbegrenzt laden.

**Abnahme:** Einfache Aufgaben ohne Skill, keine passenden Skills, mehrere benötigte Fähigkeiten, sechs notwendige Skills, explizite Wünsche, Negation und Themenwechsel. Neben Fehl-Auswahl auch ausgelassene notwendige Skills messen. Endergebnisse sind wichtiger als Skill-Anzahl oder Router-Scores.

## 4. Profile, Lifecycle und Codebase Memory — Live-Prüfung offen

Die vorhandene physische/logische Profiltrennung und profilbezogenen Caches beibehalten. Nur im aktiven Profil freigegebene Skills, Werkzeuge und Berechtigungen verwenden. Bereits implementierte Lifecycle-Ereignisse und Scan-Gating gezielt gegen die tatsächlich installierte Hermes-Version prüfen; keine Vollscans bei jeder Nachricht.

Codebase Memory nur bei passenden Codeaufgaben einsetzen. Passive MCP-Konfiguration ist kein Beleg für Erreichbarkeit oder aktuellen Index. Autorisiertes Projekt, Indexstand und reale Suchantwort prüfen. Bei fehlendem/veraltetem Index oder MCP-Ausfall mit den erlaubten normalen Codewerkzeugen weiterarbeiten; Einschränkungen transparent machen. Kein Datenbank-Direktzugriff, kein automatischer Umbau gemeinsamer Dienste und keine ungefragte Aktivierung anderer Profile. OpenViking bleibt pausiert; Shadow Learning darf nicht ungeprüft produktiv wirken.

**Abnahme:** Neu installierte, aktualisierte und entfernte Skills; geänderte Abhängigkeiten; getrennte Sessions/Profile; Codebase-Memory-Index aktuell/fehlend/veraltet und MCP nicht erreichbar; nachvollziehbarer normaler Codesuch-Ausweichweg. Keine fremden Profilinformationen.

## 5. Ergebnisvergleich: natives Hermes gegen Router — Protokoll vorbereitet, nicht ausgeführt

Der bestehende 44-Fall-Benchmark vergleicht alte und neue Router-Logik anhand erwarteter Skill-Auswahl. Er bleibt ein Regressionstest und ist kein Vergleich fertiger Hermes-Ergebnisse.

Vorgesehener Pilot: 24 synthetische/anonymisierte Aufgaben, drei Wiederholungen je Variante, insgesamt 144 Läufe. Sechs Aufgabenfamilien mit je vier Fällen: Kundenmail/Übersetzung als Entwurf, Angebot/Rechnung, Recherche, Codeanalyse/Fehlerkorrektur, mehrteilige Workflows und Negativ-/Ausfallfälle. Sechs vorab festgelegte Fälle bleiben von der Abstimmung der Routing-Regeln ausgeschlossen. Die konkreten Aufgaben und ihre Pflichtkriterien müssen vor dem Pilot eingefroren werden; sie sind hier noch nicht als fertiger Testsatz implementiert.

A verwendet natives Hermes ohne Router, B dieselbe Umgebung mit Router. Fixieren: Hermes-Commit, Modell/Revision und Einstellungen, Skill-Versionen, autorisierte Werkzeuge, Ausgangsdateien und Kontextbudget. Auch gebündelte Skills müssen in beiden Varianten gleichermaßen verfügbar sein; unterschiedliche Kataloge machen den Vergleich ungültig. Neue getrennte Sessions, kein Verlaufsaustausch; keine ungeprüfte Cloud-Ausweichroute. Reihenfolge paarweise abwechseln/randomisieren, Warm-/Kaltcache getrennt ausweisen. Veränderliche Quellen möglichst fixieren oder Abweichungen dokumentieren.

Vorab Rubrik pro Aufgabe: Korrektheit, Vollständigkeit, Einhaltung der Vorgaben und notwendige Nacharbeit jeweils 0–4 plus konkrete Pflichtprüfungen. Kritische Fehler separat markieren, nicht mit Durchschnittswerten verrechnen. Ergebnisse und erzeugte Dateien möglichst verblindet bewerten; deterministische Prüfungen für überprüfbare Eigenschaften verwenden, unklare Fälle gesondert begutachten. Ein Modell-Urteil allein reicht bei Zweifeln nicht.

Erst danach: Ausfälle/Wiederholungen, Ende-zu-Ende-Laufzeit, Werkzeugaufrufe, erneut geladene Skills und gesamte Modell-Tokens inklusive Router-/Analyseaufwand vergleichen. Lokale Embedding-Laufzeit getrennt erfassen. Fehlende Tokenmessung als unbekannt kennzeichnen, Schätzungen nicht mit Messungen mischen. Fallweise gepaarte Unterschiede, Streuung, Stichprobengröße und Nacharbeit offenlegen. Der Pilot belegt keine allgemeine Überlegenheit; Grenzfälle erfordern zusätzliche Läufe.

## 6. Freigabe und Rollback — offen

Zunächst das bereits vorbereitete isolierte Entwicklungs-/Testprofil prüfen und verwenden, kein produktives Profil als Ersatz. Vor Änderungen exakt betroffenen Plugin-/Router-Zustand sichern. Kandidaten-Commit pinnen, tatsächlich geladene Identität dokumentieren; technische Prüfungen bündeln und nur notwendige Rückfragen stellen.

Breitere Aktivierung nur bei belegtem Nutzen ohne relevante Qualitätsverschlechterung. Pflichtauslassungen, Sicherheits-/Freigabeverletzungen oder falsche Ergebnisse können nicht durch Tokenersparnis kompensiert werden. Bei gemischten Ergebnissen ausschließlich die nachgewiesen geeigneten Aufgaben/Profile empfehlen. Bei fehlenden oder widersprüchlichen Belegen bleibt die Freigabe offen.

Profilbezogenes Deaktivieren, Rückkehr zum vorigen geprüften Commit und Wiederherstellen des gesicherten Router-Zustands praktisch prüfen. Keine fremden Profile oder globalen Gateway-Dienste zurücksetzen. Repository-Merge, Release und produktive Aktivierung sind getrennte Entscheidungen; eine grüne CI ersetzt weder Live-Abnahme noch Rollout-Freigabe.
