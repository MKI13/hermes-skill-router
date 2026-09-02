# Hermes Skill Router

Ein dauerhaft aktiver, profilspezifischer Skill-Planer für [Hermes Agent](https://github.com/NousResearch/hermes-agent) mit optionaler [OpenViking](https://github.com/volcengine/OpenViking)-Indexierung und semantischer Suche.

Das Plugin erfasst die tatsächlich verfügbaren Skills jedes Hermes-Profils, liest deren `SKILL.md`, erzeugt mit einem konfigurierbaren Hermes-Hilfsmodell einen Einsatzplan, spiegelt Katalog und Plan nach OpenViking und empfiehlt vor jeder Benutzeraufgabe die passenden Skills in der richtigen Reihenfolge. Die ausgewählten Anweisungen werden weiterhin über Hermes `skill_view` geladen.

> Status: frühe Community-Version (`0.1.0`). Vor unbeaufsichtigtem Einsatz mit den eigenen Hermes- und OpenViking-Versionen testen.

## Warum Plugin und Skill kombiniert werden

Eine einzelne `SKILL.md` wird nur bei Bedarf geladen. Sie kann nicht dauerhaft aktiv bleiben, Skill-Änderungen beobachten oder vor jeder Anfrage dynamische Empfehlungen einfügen. Dieses Repository enthält deshalb:

- ein Hermes-Plugin für Lebenszyklus, Planung, Speicherung, OpenViking-Synchronisierung und Routing;
- den Skill `skill-router:skill-router` für Bedienung und Diagnose;
- kein zusätzliches dauerhaftes Model-Tool-Schema.

## Ablauf

1. Das Plugin registriert einen kurzen dauerhaften Systemhinweis, Lifecycle-Hooks, Befehle und den Hilfsmodell-Task `skill_router_planner`.
2. `hermes skill-router refresh --wait` erstellt direkt nach der Installation den ersten vollständigen Plan. Ohne diesen Befehl erzeugt die erste neue Session einen Basisplan und startet die tiefere Analyse im Hintergrund.
3. Hermes liefert den effektiven Katalog aus vertrauenswürdigen Projekt-Skills, lokalen Profil-Skills, externen Verzeichnissen und aktiven Plugin-Skills.
4. Deklarierte Befehls-, Python-Modul-, Skill- und Konfigurationsanforderungen werden beim Katalog-Refresh passiv geprüft und mit dem Plan gespeichert. Der Router führt kein Setup aus.
5. Nur neue oder geänderte Skill-Dokumente werden erneut analysiert.
6. OpenViking erhält profilspezifische Skill-Spiegel und den Plan unter `viking://~/resources/hermes-skill-router/{profile}/plan.md`.
7. Vor jeder Aufgabe liefert OpenViking semantische Treffer. Das Hermes-Hilfsmodell wählt daraus und aus dem vollständigen Plan null bis fünf existierende Skills samt Reihenfolge.
8. Ein deterministisches Policy Gate prüft Katalog-Readiness, explizite Benutzerwünsche, Alternativen, deklarierte Skill-Abhängigkeiten, Rollen, Dependency-Reihenfolge und das Skill-Limit. Modellausgaben umgehen diese Schicht nicht.
9. Hermes erhält einen dynamischen `[Skill Router]`-Block und lädt die validierten Skills nativ mit `skill_view`.
10. Die öffentlichen Observer `post_tool_call` und `post_llm_call` ordnen erfolgreiche `skill_view`-Aufrufe passiv der validierten Routing-Entscheidung zu. Der Audit blockiert nichts, wiederholt nichts und verändert kein Ranking.
11. Erstellen, Installieren, Patchen, Bearbeiten, Archivieren und Wiederherstellen eines Skills löst eine inkrementelle Aktualisierung und nach dem 30-Sekunden-Cachefenster eine zweite Prüfung aus. Regelmäßige Fingerprint-Prüfungen erkennen weitere Änderungen.

Jedes Hermes-Profil besitzt einen eigenen Plan und eine begrenzte Audit-Historie in `ctx.state`. Ein Coding-Profil und ein Research-Profil beeinflussen sich nicht gegenseitig.

## Kompatibilität

Die Plugin-APIs wurden gegen Hermes-Main-Commit `d3e2ace1dde9f1d279f99c9ebc6bce2e761b025d` geprüft und mit `hermes plugins doctor` auf einem lokalen, von 2026.8.19 abgeleiteten Build validiert. OpenViking `0.4.17.1` ist die geprüfte API-Version. Vor dem Aktivieren auf einer anderen Hermes-Version `hermes plugins doctor . --ci` ausführen.

## Installation

Nach der Veröffentlichung `OWNER` durch den GitHub-Benutzernamen oder die Organisation ersetzen:

```bash
hermes plugins install OWNER/hermes-skill-router --enable
hermes skill-router refresh --wait
```

Für mehrere Profile:

```bash
hermes --profile coding plugins install OWNER/hermes-skill-router --enable
hermes --profile coding skill-router refresh --wait

hermes --profile research plugins install OWNER/hermes-skill-router --enable
hermes --profile research skill-router refresh --wait
```

## Lokales Planungsmodell konfigurieren

```bash
hermes model
```

Unter **Auxiliary models** den Eintrag **Skill Router planner** auswählen und mit dem gewünschten lokalen Provider beziehungsweise Endpoint verbinden.

Wichtig: Das OpenViking-Embedding-Modell, VLM und der optionale Query Planner gehören intern zu OpenViking. Hermes übernimmt diese Modelle nicht automatisch und OpenViking bietet sein konfiguriertes VLM nicht als allgemeine Completion-API an. Deshalb verwendet der Router:

- OpenViking für Indexierung, semantische Skill-Suche und Planspeicherung;
- Hermes `ctx.llm` über `auxiliary.skill_router_planner` für Analyse und endgültige Auswahl.

Beide Systeme können auf denselben lokalen Modellserver zeigen, müssen aber getrennt konfiguriert werden.

## OpenViking

```bash
openviking-server init
openviking-server doctor
openviking-server
hermes memory setup openviking
hermes memory status
```

Der eingebaute Hermes-OpenViking-Memory-Provider verarbeitet Erinnerungen und Gespräche. Er synchronisiert und routet Hermes-Skills jedoch nicht automatisch. Genau diese Aufgabe übernimmt dieses Plugin.

Verbindungsreihenfolge:

1. `plugins.entries.skill-router.settings.openviking_url`
2. `OPENVIKING_URL`
3. `OPENVIKING_ENDPOINT`
4. `http://127.0.0.1:1933`

Optional werden `OPENVIKING_API_KEY`, `OPENVIKING_ACCOUNT` und `OPENVIKING_USER` verwendet. Ist OpenViking nicht erreichbar, arbeitet Hermes mit dem lokalen Plan und dem deterministischen Fallback weiter.

## Bedienung

In einer Session:

```text
/skill-router status
/skill-router refresh
/skill-router plan
/skill-router inspect github
/skill-router audit
/skill-router audit last
/skill-router recommend Erstelle und prüfe einen GitHub Pull Request
```

Im Terminal:

```bash
hermes skill-router status
hermes skill-router refresh --wait
hermes skill-router plan
hermes skill-router inspect github
hermes skill-router audit
hermes skill-router audit last
hermes skill-router recommend Erstelle und prüfe einen GitHub Pull Request
```

## Readiness-Deklarationen

Ein Skill kann passive Anforderungen im Frontmatter seiner `SKILL.md` deklarieren:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  config: [GITHUB_TOKEN]
```

Die älteren Hermes-Felder `prerequisites.commands` und `prerequisites.env_vars` werden ebenfalls erkannt. Ohne Deklaration bleibt ein Skill `unknown`; er wird nicht automatisch als einsatzbereit betrachtet. Fehlende Befehle, Module oder Skills ergeben `dependency_missing`. Fehlende deklarierte Konfiguration oder `setup_required: true` ergeben `setup_required`. Der Router zeigt nur Namen und Verfügbarkeit an und gibt niemals konfigurierte Werte aus, installiert nichts, meldet sich nirgendwo an und verändert keine Konfiguration.

`/skill-router inspect <skill-name>` zeigt die gespeicherten Prüfergebnisse. Die Readiness wird beim Katalog-Refresh statt bei jedem Turn neu berechnet.

## Deterministische Routing-Policy

`skill_router_plugin/policy.py` validiert Modell- und deterministische Auswahlen, ohne semantisch neu zu ranken. Unbekannte Modellfelder werden ignoriert, höchstens eine Primary-Rolle bleibt erhalten und bei reinen Supporting-Auswahlen wird der erste gültige Skill Primary. Automatisch ausgewählte kaputte oder deaktivierte Skills werden entfernt. `setup_required` und `dependency_missing` bleiben nur nach den dokumentierten expliziten beziehungsweise Fallback-Regeln sichtbar. Ein explizit verlangter kaputter oder deaktivierter Skill ergibt `policy=blocked` ohne ausführbare Empfehlung; Hermes selbst arbeitet normal weiter.

Deklarierte `requirements.skills` werden transitiv ergänzt und vor dem abhängigen Skill geladen, während dieser seine Primary-Rolle behält. Erforderliche Dependencies verdrängen optionale Supporting-Skills am Limit. Fehlende oder unbrauchbare Dependencies blockieren den betroffenen Primary. Zyklen ergeben eine degradierte deterministische Reihenfolge mit Warnung. Deklarierte Alternativen werden nach explizitem Wunsch, Readiness und ursprünglicher Auswahlposition aufgelöst. Policy-Statuswerte sind `valid`, `adjusted`, `degraded` und `blocked`.

## Routing-Ausführungs-Audit

Für jeden gerouteten Turn speichert der Router Task-Hash, undurchsichtige Hermes-Task-/Turn-/Session-IDs, Routing-Methode, Policy-Status, finale validierte Skill-Namen und Rollen, erfolgreiche oder fehlgeschlagene `skill_view`-Beobachtungen, Ergebnis und den Ladezustand des Primary-Skills. Mögliche Ergebnisse sind `complete`, `partial`, `missed`, `not_applicable` und `unknown`. Ohne beide benötigten Observer-Hooks oder bei abgebrochener Finalisierung bleibt die Bewertung `unknown`.

`/skill-router audit` fasst die letzten 20 Einträge zusammen, `/skill-router audit last` zeigt die letzte Empfehlung mit Ladeergebnis und `/skill-router audit N` fasst die letzten `N` Einträge zusammen. Die Historie ist profilspezifisch und begrenzt. Nur ein SHA-256-Task-Hash bleibt erhalten; Prompts, Task-Previews, Antworten, Skill-Inhalte, Tool-Ergebnisse, Fehlermeldungen, Dateien und Zugangsdaten werden nicht gespeichert.

## Einstellungen

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: model             # model | deterministic
        deep_refresh_on_start: true
        rescan_interval_seconds: 60
        max_skills_per_task: 4
        max_audit_entries: 100          # begrenzt auf 10-1000
        max_skill_chars: 20000
        analysis_batch_size: 6
        analysis_model_timeout_seconds: 25
        routing_catalog_chars: 60000
        routing_model_timeout_seconds: 20
        openviking_enabled: true
        openviking_url: http://127.0.0.1:1933
        openviking_timeout_seconds: 10
        openviking_retrieval_limit: 12
        openviking_routing_timeout_seconds: 3
        openviking_score_threshold: 0.15
        openviking_plan_uri: "viking://~/resources/hermes-skill-router/{profile}/plan.md"
```

## Sicherheit und bekannte Grenzen

- OpenViking liefert nur Retrieval-Hinweise und Skill-Namen. Die dort gespeicherte Kopie wird nicht direkt als ausführbare Anweisung eingefügt.
- Die Audit-Observer verwerfen Prompt-, Antwort-, Tool-Ergebnis- und Fehlerdaten bereits an der Compatibility-Grenze. Persistiert werden nur Identifikatoren, Task-Hashes, Skill-Namen, Rollen, Reihenfolge, Zeitpunkte, Routing-/Policy-Statuswerte und Ergebnisse.
- Bei einem Policy-Fehler wird die ungeprüfte Auswahl verworfen und ein leerer degradierter Plan geliefert; rohe Modellausgaben werden nie als Fallback injiziert.
- Entfernte Spiegel werden nur gelöscht, wenn ihr Name zuvor als Router-Eigentum im Profilzustand gespeichert wurde.
- Die HTTP-Brücke blockiert URL-Zugangsdaten, Pfade, Query-Strings, Redirects, Proxys, Metadaten-/Link-Local-Ziele und übergroße Antworten. Zugangsdaten außerhalb von Loopback erfordern HTTPS.
- Das Hilfsmodell erhält Skill-Dokumente ausdrücklich als nicht vertrauenswürdige Analysedaten.
- Hermes besitzt derzeit keine öffentliche Plugin-API, die gleichzeitig exakte Rohdateien, alle Quellen, Provenienz und eine erzwungene Cache-Aktualisierung anbietet. Alle versionsabhängigen Hermes-Imports und Pfadzugriffe liegen deshalb in `skill_router_plugin/compat/hermes.py` und werden über Feature Detection geprüft. Fehlt eine benötigte interne API oder ist sie inkompatibel, verwendet der Router ausschließlich Katalogmetadaten.
- `/skill-router status` zeigt `full` oder `degraded` sowie die Verfügbarkeit von Raw Reader, Plugin-Skill-Lookup, Lifecycle-Hook, Auxiliary Tasks und Skill-Ausführungs-Audit. Der Audit benötigt die öffentlichen Hooks `post_tool_call` und `post_llm_call`; fehlen sie, bleibt das Routing unverändert aktiv.
- Der Lifecycle-Hook meldet derzeit kein Löschen oder Deinstallieren. Die regelmäßige Katalogprüfung erkennt solche Änderungen später.
- Änderungen innerhalb einer `SKILL.md` können wegen Hermes-Cachezeiten ungefähr 30 Sekunden verzögert erscheinen.
- Ein bereits bestehender System-Prompt wird aus Cache-Gründen nicht verändert. Die dynamische Empfehlung wird trotzdem bei jedem Turn über `pre_llm_call` ergänzt.
- Hermes begrenzt `pre_llm_call` standardmäßig auf 30 Sekunden. Die Router-Timeouts bleiben darunter; bei Zeitüberschreitung läuft Hermes für diesen Turn ohne Router-Kontext weiter.
- Native Hermes-Plugins laufen als vertrauenswürdiger Python-Code im Prozess. Quellcode vor dem Aktivieren prüfen.

## Entwicklung und Prüfung

```bash
python -m pytest -q
python -m compileall -q .
hermes plugins doctor . --ci
```

## Lizenz

MIT, siehe [LICENSE](LICENSE).
