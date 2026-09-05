# Hermes Skill Router

Ein dauerhaft aktiver, profilgetrennter Skill-Planer für Hermes Agent mit deterministischem Routing, optionalen lokalen Ollama-Embeddings, konservativem Folgekontext, Readiness-Prüfungen, Audit/Quality und optionaler OpenViking-Unterstützung.

> **Entwicklungsstand v0.11.0 — unveröffentlicht.** Die Änderungen dieses Branches sind noch nicht im vorgesehenen isolierten Hermes-Profil mit lokalem Modell geprüft. Eine grüne CI ist keine Produktionsfreigabe. OpenViking bleibt **standardmäßig deaktiviert**.

## Architektur

```text
User-Aufgabe
  -> Skill Router
     -> explizite/deterministische Signale
     -> optional lokale Embedding-Ähnlichkeit
     -> konservativer Session-Folgekontext
     -> Readiness + Dependency Policy
     -> kompakte Entscheidungsmetadaten
  -> Hermes skill_view
  -> ausgewählter Skill
  -> MCP / Tools dieses Skills
```

Hermes bleibt die ausführende Instanz. Der Router empfiehlt normale Hermes-Skills; er macht aus MCP-Servern keine direkt routbaren Skills. MCP-basierte Verfahren deklarieren `requirements.mcps`. Hermes lädt die ausgewählten Verfahren über `skill_view`, nicht als kopierte ausführbare Skill-Dokumente im Prompt.

Enthalten sind das native `skill-router`-Plugin, der operative Skill `skill-router:skill-router` und `skill-router:codebase-memory` für den exakten MCP-Konfigurationsschlüssel `codebase-memory` im aktiven Profil.

## Aktueller Entwicklungsumfang

Dieser Branch verbindet Rollout-Preflight, Readiness 2.0, Confidence-basierte Policy-Auswahl und Routing Decision Telemetry 2.0. Das sind Entwicklungsmeilensteine, keine Behauptung mehrerer veröffentlichter Produktionsversionen.

Readiness unterscheidet fehlende Commands, Python-Module, andere Skills, MCP-Konfigurationen und erforderliche Konfigurationsschlüssel. `inspect` gruppiert fehlende und ungeprüfte Abhängigkeiten, Setup-Anforderungen und die Router-Empfehlung. Doctor ergänzt eine begrenzte Zusammenfassung statt einer unübersichtlichen Gesamtliste.

Der Confidence-Vergleich der Policy kann einen deutlich relevanteren `unknown`-Primary beibehalten oder einen ähnlich relevanten `ready`-Kandidaten vorziehen. Explizite Benutzerwünsche und die vorhandenen Sicherheits-/Abhängigkeitsprüfungen bleiben maßgeblich. Confidence ist eine Routing-Heuristik, keine kalibrierte Wahrscheinlichkeit und kein Ausführungsnachweis.

Die Telemetrie ist jetzt über **Policy -> Runtime -> Audit** verbunden. `recommend`, `audit`, `quality` und die allgemeine `learning`-Zusammenfassung zeigen diese Beobachtungen an. Routing-Scores, Quality-Bewertung und Shadow-Learning-Gewichte werden dadurch nicht verändert.

## Voraussetzungen

- Hermes Agent mit den verwendeten nativen Plugin-Hooks: `on_session_start`, `pre_llm_call`, `pre_tool_call`, `post_tool_call`, `post_llm_call` und Lifecycle-Unterstützung, soweit verfügbar.
- Aktiviertes Hermes-`skills`-Toolset und Python 3.11 oder neuer.
- Für Hybrid/Embedding: lokaler Ollama-kompatibler `/api/embed`-Endpunkt auf numerischer Loopback-Adresse.
- Für Codebase Memory: MCP-Konfiguration im aktiven Profil mit dem exakten Schlüssel `codebase-memory`.
- OpenViking bleibt optional; für die empfohlene Konfiguration ist es nicht erforderlich.

Capabilities werden erkannt, nicht aus einer Versionsnummer abgeleitet. CI führt Repository-Tests und Plugin-Scans gegen gepinnte Hermes-Revisionen sowie einen informativen aktuellen `main`-Scan aus. Diese Scans ersetzen keinen echten Hermes-Integrationstest.

## Installation und Profilgrenzen

Eine Installation ohne Ref verwendet den Standardbranch, nicht diesen Entwicklungsbranch:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
```

Entwicklungstests benötigen einen ausdrücklich geprüften Commit und ein bereits vorhandenes isoliertes Testprofil. Zuerst dessen Konfiguration prüfen und den Router-Zustand sichern:

```bash
hermes --profile <test-profil> plugins install MKI13/hermes-skill-router --ref <gepruefter-commit-sha> --enable
hermes --profile <test-profil> skill-router setup --dry-run --target-profile <test-profil>
```

Nicht durch ein produktives Profil ersetzen. Den Setup-Plan vor einem getrennten `setup --apply` prüfen. Die Dokumentation ist keine Freigabe für Profiländerungen, Gateway-Neustarts, Merge, Release oder einen Rollout auf weitere Profile.

`profiles` dient der Übersicht; `profiles --sync` und `setup --apply` sind ausdrückliche Schreiboperationen. Setup verwendet Hermes-Profilmechanismen statt kopierter oder verlinkter Profilzustände. Neue Skills werden über Lifecycle-Ereignisse und begrenztes Rescanning erkannt; ein neuer MCP allein ist noch kein routbarer Skill.

## Konservative Konfiguration

Mit deterministischem Routing beginnen und OpenViking pausiert lassen:

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: deterministic
        enforcement_mode: warn
        learning_mode: shadow
        followup_context_enabled: true
        openviking_enabled: false
```

Nach Prüfung des lokalen Endpunkts ist semantisches Routing optional möglich:

```yaml
routing_mode: hybrid
embedding_url: http://127.0.0.1:11436
embedding_model: qwen3-embedding:0.6b
embedding_dimensions: 1024
```

Der Beispiel-Endpunkt muss zum tatsächlichen lokalen Dienst passen. Deterministisches Routing benötigt ihn nicht. Bei einem Embedding-Ausfall greift im laufenden Betrieb der deterministische Fallback; für den Hybrid-/Embedding-Preflight muss der konfigurierte Endpunkt den Health Check bestehen.

## Kommandos und Nebenwirkungen

Innerhalb von Hermes:

```text
/skill-router status
/skill-router doctor
/skill-router rollout-check
/skill-router canary
/skill-router performance
/skill-router events 20
/skill-router refresh
/skill-router plan
/skill-router inspect codebase-memory
/skill-router audit last
/skill-router quality last
/skill-router learning
/skill-router enforcement
/skill-router recommend prüfe dieses Repository und finde die Implementierung
```

Terminal-Kommandos verwenden `hermes --profile <profil> skill-router ...`; CLI-Refresh unterstützt zusätzlich `refresh --wait`.

`audit`, `quality` und die allgemeine `learning`-Zusammenfassung lesen vorhandene Beobachtungen. `recommend` zeigt eine Beispielentscheidung, ohne einen Ausführungs-Audit-Eintrag anzulegen. Kommandos mit Katalogerkennung können **Router-eigene Caches und Zustände aktualisieren**; `recommend` kann zusätzlich den abgeleiteten Shadow-Zustand neu berechnen. Doctor, Canary und Preflight sind deshalb keine Garantie für null Dateischreibvorgänge. Sie ändern keine Profilkonfiguration, installieren keine Skills/MCPs und starten keine Gateways. In Hybrid/Embedding sind begrenzte Loopback-Health-Anfragen möglich.

### Rollout-Preflight

```bash
hermes --profile <test-profil> skill-router rollout-check
hermes --profile <test-profil> skill-router doctor
hermes --profile <test-profil> skill-router canary
```

`rollout-check` liefert `READY`, `REVIEW` oder `BLOCKED`. Geprüft werden kritische Hermes-Capabilities, Katalog/Hash, Routing-/Enforcement-/Learning-Einstellungen, Folgekontext, notwendige Embedding-Health-Checks, Codebase-Memory-Konfiguration/Skill und pausiertes OpenViking.

`READY` erlaubt kontrolliertes Testen, bestätigt aber keinen echten Ausführungstest und erlaubt keine automatischen Änderungen anderer Profile. `REVIEW` verlangt eine Prüfung der Warnungen; `BLOCKED` kennzeichnet einen harten Preflight-Fehler.

### Doctor und Canary

Doctor liefert `PASS`, `WARN` oder `BLOCKED`. Die Readiness-Zusammenfassung nennt höchstens acht auffällige Skills; Details werden über `inspect` abgerufen.

```text
SKIP    OpenViking disabled by configuration
```

Der Codebase-Memory-Canary verlangt einen verfügbaren Routing-Skill und einen konfigurierten/aktivierten MCP. Fehlende MCP-Readiness führt zu WARN und übersprungenen zugehörigen Kontinuitätstests. Passive MCP-Erkennung ist kein echter RPC-, Such- oder Ende-zu-Ende-Ausführungstest.

### Performance

`performance` zeigt begrenzte Werte für `catalog_ms`, `embedding_ms`, `selection_ms`, `policy_ms` und `total_ms`, Total-p50/p95 sowie Embedding-Cache-Diagnose. Im Performance-Zustand werden keine Prompt-/Antworttexte oder Tool-Payloads gespeichert.

## Routing-Entscheidungstelemetrie

Im bestehenden profilbezogenen Audit wird optional `routing_telemetry` mit genau diesen Feldern gespeichert:

| Feld | Bedeutung |
|---|---|
| `confidence` | `high`, `medium`, `none` oder `not_assessed` |
| `original_primary` | Gegen den Katalog geprüfter Primary vor der Policy oder leer |
| `final_primary` | Tatsächlicher Primary nach der Policy oder leer |
| `fallback_applied` | Echte boolesche Angabe für automatischen Primary-Wechsel; kein expliziter Benutzer-Override |
| `fallback_reason` | Fester Code: `ready_within_margin`, `policy_replacement`, `unspecified` oder leer |

`none` bedeutet: Die Entscheidung hat keinen endgültigen Primary. `not_assessed` bedeutet: Der endgültige Kandidat wurde nicht durch die Confidence-Engine bewertet oder ein älterer Eintrag enthält keine Telemetrie. Alte Einträge erhalten keine erfundenen nachträglichen Messungen. Ein blockierter Plan kann nicht behaupten, ein zwischenzeitlicher Fallback sei ausführbar geworden.

Begründungen sind **fest zugelassene Codes, kein Freitext**. Dieser Datenpfad übernimmt keine Prompts, Konfigurationswerte, Tool-Payloads oder Modell-Erklärungen. Namen stammen aus dem aktiven Katalog und werden begrenzt sowie validiert. Fehlerhafte Werte werden normalisiert; ein Telemetriefehler darf einen sonst gültigen Routing-Plan nicht verwerfen.

`audit last`, `quality last` und `recommend` zeigen die fünf Felder. Zusammenfassungen von Audit/Quality/Learning zeigen Confidence-Zähler, automatische Wechsel und beschreibende Quality-Mittelwerte für Entscheidungen mit/ohne Fallback. Nur abgeschlossene, bewertbare Quality-Einträge fließen in diese Mittelwerte ein. Fehlende Beobachtungen werden separat gezählt. Die Historie folgt `max_audit_entries`; eine Zusammenfassung verarbeitet maximal 1.000 Einträge.

**Auch eine Route mit hoher Confidence kann beim Laden des Skills scheitern.** Confidence ist kein Ausführungserfolg. Gruppenmittelwerte beweisen nicht, dass Fallbacks die Ergebnisqualität verbessern. Die bisherige Quality-Formel und Shadow-Learning-Gewichte bleiben unverändert; aktives Lernen wird nicht eingeschaltet.

## Readiness und Policy

Skills können deklarieren:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  mcps: [codebase-memory]
  config: [GITHUB_TOKEN]
```

Status: `ready`, `unknown`, `setup_required`, `dependency_missing`, `broken`, `disabled`. Fehlende Deklarationen bedeuten nicht automatisch Einsatzbereitschaft. Readiness 2.0 ergänzt `missing_dependencies`, `unknown_dependencies`, `setup_requirements`, `readiness_summary` und Prüfzustände `available | missing | unknown`. Konfigurationsdiagnosen nennen Schlüssel, niemals deren Werte.

Die Policy prüft installierte Namen, Readiness, deklarierte Abhängigkeiten, Alternativen, Rollen, Reihenfolge und Limits. Explizite Wünsche aktivieren keine defekten/deaktivierten Skills und heben unbrauchbare Skill-Abhängigkeiten nicht auf. Setup-Warnungen berechtigen nicht zur automatischen Installation.

Enforcement-Modi: `off`, `warn`, `primary`, `all`; Standard `warn`. Learning-Modi: `off`, `shadow`; ein aktives selbstveränderndes Routing ist nicht implementiert.

## Codebase Memory und Folgekontext

Der gebündelte `codebase-memory`-Skill deklariert `requirements.mcps: [codebase-memory]`. Geeignet für Repository-Struktur, Architektur, Symbole, Implementierungssuche, Abhängigkeiten, Referenzen und Änderungsfolgen vor Codearbeit. Nicht für normale E-Mails, Übersetzungen, allgemeine Recherche, Kalender, Rechnungen oder sonstige Aufgaben ohne Codebezug.

Der Router startet, installiert oder konfiguriert Codebase Memory nicht. Jedes Profil benötigt seine eigene autorisierte MCP-Anbindung. Diese Fähigkeit ersetzt weder Hermes Memory noch setzt sie OpenViking voraus.

Kurze Folgeanfragen wie „mach weiter“, „korrigiere das“ oder „teste es“ dürfen den vorherigen Primary nur übernehmen, wenn das normale Routing keinen Skill wählt. Explizite Wünsche, Negation, `avoid_when`, defekte/deaktivierte Skills und die Policy haben weiterhin Vorrang. Themenwechsel verwerfen veralteten Workflow-Kontext.

Der begrenzte Profil-/Session-Kontext speichert ausschließlich Routing-Metadaten: gehashten Session-Key, vorherige Skill-Namen, Kategorie, Policy-Status und Zeitstempel. Keine Prompt- oder Antworttexte.

## Lokale Embedding-Sicherheit

Hybrid/Embedding akzeptiert ausschließlich numerische Loopback-HTTP-Ursprünge: keine URL-Zugangsdaten, Pfade, Queries, Fragmente, Proxies oder Redirects. Antwortgröße und Timeouts sind begrenzt; Vektoranzahl und Dimensionen müssen stimmen; Vektoren müssen endlich und ungleich null sein. Caches bleiben profilbezogen.

Embedding-Dokumente enthalten begrenzte Namen, Beschreibung, Kategorie, Tags, `use_when`, Keywords und `works_with`. `avoid_when` bleibt ein Ausschlusssignal. `EMBEDDING_DOCUMENT_VERSION = 2` bezeichnet das Cache-Format, nicht die Plugin-Version; die Formatversion fließt zusammen mit den Routing-Metadaten in die Cache-Identität ein.

## OpenViking

```yaml
openviking_enabled: false
```

Die optionale Bridge bleibt vorhanden, aber standardmäßig pausiert. `openviking_read_enabled` und `openviking_auto_write_enabled` bleiben für eine später ausdrücklich geprüfte Aktivierung getrennt verfügbar. Der Hauptschalter verhindert Router-Bridge-Lese-/Schreibzugriffe; die unabhängige Hermes-Memory-Konfiguration wird nicht verändert.

## Konfigurationsreferenz

CI gleicht diese exakten Schlüssel und Defaults mit `plugin.yaml` und der englischen README ab.

| Einstellung | Typ | Standard |
|---|---|---|
| `routing_mode` | `str` | `deterministic` |
| `deep_refresh_on_start` | `bool` | `true` |
| `rescan_interval_seconds` | `int` | `60` |
| `max_skills_per_task` | `int` | `4` |
| `deterministic_min_score` | `int` | `20` |
| `deterministic_supporting_min_score` | `int` | `24` |
| `max_optional_supporting_skills` | `int` | `2` |
| `followup_context_enabled` | `bool` | `true` |
| `followup_context_max_sessions` | `int` | `32` |
| `embedding_url` | `str` | `"http://127.0.0.1:11436"` |
| `embedding_model` | `str` | `"qwen3-embedding:0.6b"` |
| `embedding_dimensions` | `int` | `1024` |
| `embedding_timeout_seconds` | `float` | `5.0` |
| `embedding_keep_alive` | `str` | `"5m"` |
| `embedding_batch_size` | `int` | `32` |
| `embedding_ambiguity_margin` | `float` | `0.02` |
| `embedding_min_score` | `float` | `0.35` |
| `embedding_weak_signal_min_score` | `float` | `0.45` |
| `performance_history_limit` | `int` | `100` |
| `max_audit_entries` | `int` | `100` |
| `learning_mode` | `str` | `shadow` |
| `learning_min_samples` | `int` | `5` |
| `enforcement_mode` | `str` | `warn` |
| `max_enforcement_blocks_per_turn` | `int` | `2` |
| `max_skill_chars` | `int` | `20000` |
| `analysis_batch_size` | `int` | `6` |
| `analysis_model_timeout_seconds` | `int` | `25` |
| `routing_catalog_chars` | `int` | `60000` |
| `routing_model_timeout_seconds` | `int` | `20` |
| `openviking_enabled` | `bool` | `false` |
| `openviking_read_enabled` | `bool` | `true` |
| `openviking_auto_write_enabled` | `bool` | `true` |
| `openviking_url` | `str` | `""` |
| `openviking_timeout_seconds` | `int` | `10` |
| `openviking_retrieval_limit` | `int` | `12` |
| `openviking_routing_timeout_seconds` | `int` | `3` |
| `openviking_score_threshold` | `float` | `0.15` |
| `openviking_plan_uri` | `str` | `"viking://~/resources/hermes-skill-router/{profile}/plan.md"` |

Erlaubte Modi: `routing_mode` = `deterministic | hybrid | embedding | model`; `enforcement_mode` = `off | warn | primary | all`; `learning_mode` = `off | shadow`.

## Entwicklung und Validierung

```bash
python -m pytest -q
python scripts/benchmark-routing-quality.py
python scripts/check-doc-config-sync.py
python -m compileall -q .
hermes plugins doctor . --ci
```

Die Tests decken Policy/Audit-Verbindung, Produktions-Wrapper, Abschluss und erneutes Laden, Profil-/Session-Trennung, begrenzte Historie, fehlerhafte Telemetrie, Freitextausschluss bei Begründungen sowie unveränderte Quality-/Learning-Bewertung ab. Der Versionsabgleich umfasst `pyproject.toml`, `plugin.yaml`, beide gebündelten Skills, Paket-/Runtime-Version und aktuelle Dokumentationsmarker.

GitHub CI prüft Python 3.11/3.12/3.13, Benchmarks, Dokumentationsabgleich, Kompilierung, zwei gepinnte Hermes-Plugin-Scans und den aktuellen main-Scan informativ. Ein echter isolierter Profiltest mit dem vorgesehenen lokalen Modell, Codebase Memory und Embedding-Dienst bleibt eine getrennte Abnahmebedingung vor Merge oder Release.

## Lizenz

MIT. Siehe `LICENSE`.
