# Hermes Skill Router

Ein dauerhaft aktiver, profilgetrennter Skill-Planer für Hermes Agent mit deterministischem Routing, lokalen Ollama-Embeddings, konservativem Folgekontext, passiven Readiness-Prüfungen, Audit/Quality und optionaler OpenViking-Unterstützung.

> Status: Community Release Candidate **v0.8.0**. Für den empfohlenen v0.8.0-Rollout bleibt OpenViking **standardmäßig deaktiviert**.

## Zielarchitektur

```text
User-Aufgabe
  -> Skill Router
     -> explizite/deterministische Signale
     -> optional lokale Embedding-Ähnlichkeit
     -> konservativer Session-Folgekontext
     -> Readiness + Dependency Policy
  -> Hermes skill_view
  -> ausgewählter Skill
  -> MCP / Tools dieses Skills
```

Der Router macht aus MCP-Servern niemals direkt routbare Skills. MCP-basierte Workflows werden über normale Hermes Skills mit `requirements.mcps` angebunden.

## Neu in v0.8.0

- Neuer read-only `rollout-check` mit den Entscheidungen `READY`, `REVIEW` und `BLOCKED` vor einem Profil-Rollout.
- Der Preflight prüft kritische Hermes-Capabilities, Katalog/Hash, konservative Routing-/Enforcement-/Learning-Einstellungen, lokale Embeddings wenn nötig, Codebase-Memory-MCP/Skill, Follow-up-Kontext und pausiertes OpenViking.
- Gebündelter `codebase-memory` Skill für den MCP-Identifier `codebase-memory`.
- Der Canary meldet Codebase Memory nur dann als PASS, wenn sowohl Routing-Skill als auch der aktive Profil-MCP `codebase-memory` bereit sind.
- Konservatives Follow-up-Routing für kurze Nachrichten wie „mach weiter“, „korrigiere das“, „teste es“ oder „jetzt committen“.
- Der Folgekontext speichert nur Routing-Metadaten – keine Prompts, Antworten, Tool-Payloads, Dateien oder Zugangsdaten.
- Reichere, versionierte lokale Embedding-Dokumente aus Name, Beschreibung, Kategorie, Tags, `use_when`, Keywords und `works_with`.
- `hermes skill-router doctor` / `/skill-router doctor` für sichere Gesamtdiagnose.
- `hermes skill-router performance` / `/skill-router performance` für begrenzte lokale Latenzmetriken.
- CI-Prüfung, dass `plugin.yaml`, `README.md` und `README.de.md` dieselben Konfigurationsschlüssel und Defaults dokumentieren.
- OpenViking Read/Write-Schalter bleiben erhalten; `openviking_enabled` bleibt standardmäßig `false`.

## Warum Plugin plus Skills

Ein einzelnes `SKILL.md` kann nicht dauerhaft aktiv bleiben und keine Hermes-Lifecycle-Ereignisse beobachten. Das Repository enthält deshalb das native Router-Plugin, den operativen `skill-router:skill-router` Skill und den `skill-router:codebase-memory` Skill. Hermes lädt ausgewählte Verfahren weiterhin ausschließlich über `skill_view`.

## Voraussetzungen

- Hermes Agent mit den benötigten Plugin-Hooks.
- Aktiviertes Hermes-`skills`-Toolset.
- Python 3.11 oder neuer.
- Für Hybrid-Routing: lokaler Ollama-kompatibler `/api/embed`-Endpunkt auf einer numerischen Loopback-Adresse.
- Für Codebase Memory: MCP-Server im aktiven Profil mit dem exakten Hermes-Konfigurationsschlüssel `codebase-memory`.
- OpenViking ist optional und für den empfohlenen v0.8.0-Rollout nicht erforderlich.

## Installation

Bevorzugt über Hermes:

```text
Installiere den Skill Router aus MKI13/hermes-skill-router.
```

Terminal:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
hermes skill-router setup
hermes skill-router setup --dry-run
hermes skill-router setup --apply
hermes skill-router profiles
```

Neue, entfernte oder umbenannte Profile:

```bash
hermes skill-router profiles --sync
```

Profile bleiben physisch und logisch getrennt; Router-State wird nicht zwischen Profilen kopiert.

## Empfohlene v0.8.0-Konfiguration

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: hybrid
        enforcement_mode: warn
        learning_mode: shadow
        followup_context_enabled: true
        embedding_url: http://127.0.0.1:11436
        embedding_model: qwen3-embedding:0.6b
        embedding_dimensions: 1024
        openviking_enabled: false
```

Fällt das lokale Embedding im laufenden Hybrid-Routing aus, verwendet der Router den deterministischen Fallback. Für den Rollout-Preflight muss der konfigurierte Hybrid-/Embedding-Endpunkt jedoch gesund sein.

## Rollout-Preflight

Vor der Aktivierung in einem weiteren Profil:

```bash
hermes --profile <profil> skill-router rollout-check
hermes --profile <profil> skill-router doctor
hermes --profile <profil> skill-router canary
```

`rollout-check` ist vollständig read-only und liefert:

- `READY`: konservative Rollout-Defaults und notwendige Health Checks sind erfüllt;
- `REVIEW`: kein harter Blocker, aber Einstellungen oder optionale Abhängigkeiten müssen geprüft werden;
- `BLOCKED`: eine kritische Hermes-Capability, Katalogzustand, Routing-Modus oder ein notwendiger lokaler Embedding-Check verhindert den Rollout.

Der Befehl installiert, aktiviert, startet, stoppt oder verändert keine Profile, Skills, MCPs, Gateways oder Dateien. `READY` erlaubt kontrolliertes Testen, aber niemals einen automatischen Rollout auf andere Profile.

## Lokale Embeddings

Die Sicherheitsgrenze bleibt erhalten: nur numerisches Loopback-HTTP, keine URL-Credentials/Proxies/Redirects, begrenzte Antwortgröße und Timeouts, exakte Vektordimension, endliche nicht-leere Vektoren, profilgetrennter Cache und deterministischer Fallback.

v0.8.0 verwendet `EMBEDDING_DOCUMENT_VERSION = 2`. Der Vektor-Cache berücksichtigt das Routing-Dokumentformat und relevante Skill-Metadaten, damit veraltete Vektoren nicht still wiederverwendet werden.

## Codebase Memory

Codebase Memory wird nicht als MCP direkt geroutet, sondern über den gebündelten Skill:

```yaml
requirements:
  mcps:
    - codebase-memory
```

Verwenden für Repository-Struktur, Architektur, Funktionen/Klassen/Symbole, Implementierungs-Suche, Abhängigkeiten, Referenzen und Impact-Analyse vor Codeänderungen. Nicht verwenden für normale E-Mails, Übersetzungen, Web-Recherche, Kalender, Rechnungen oder andere Aufgaben ohne Codebezug.

Der Router startet oder verändert den MCP nicht. Ist der MCP aktiv, aber kein routbarer Skill referenziert ihn, meldet `skill-router doctor` eine Warnung.

Der Canary behandelt Codebase Memory nur dann als vollständig bereit, wenn sowohl der Routing-Skill als auch der MCP im aktiven Profil bereit sind. Fehlt einer von beiden, meldet der Canary WARN und überspringt die Codebase-Memory-Follow-up-Prüfungen.

## Follow-up-Routing

Beispiel:

```text
Analysiere das Repository und finde die Implementierung.
-> PRIMARY: codebase-memory

Jetzt korrigiere es.
```

Der vorherige Primary Skill darf nur wiederverwendet werden, wenn die Nachricht kurz und referenziell ist, das normale Routing keinen Skill gewählt hat, kein anderer Skill explizit verlangt wird, der vorherige Skill weiterhin verwendbar ist, keine Negation/`avoid_when` greift und die normale Policy das Ergebnis akzeptiert.

Ein Themenwechsel wie „Schreib jetzt eine E-Mail an den Kunden“ übernimmt Codebase Memory nicht.

Gespeichert werden nur ein gehashter Session-Key, vorheriger Primary/Supporting Skill, Routing-Kategorie, Policy-Status und Zeitstempel – keine Prompt- oder Antworttexte.

## Kommandos

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

Terminal-Kommandos verwenden `hermes skill-router ...`.

### Doctor

`doctor` prüft Hermes-Capabilities, Skill-Katalog, Policy/Audit/Quality/Learning, lokale Embeddings im passenden Routing-Modus sowie Codebase-Memory-MCP und -Skill. Secrets und vollständige interne Pfade werden nicht ausgegeben.

Bei pausiertem OpenViking:

```text
SKIP    OpenViking disabled by configuration
```

Gesamtstatus: `PASS`, `WARN` oder `BLOCKED`.

### Performance

Gespeichert werden ausschließlich begrenzte numerische Werte `catalog_ms`, `embedding_ms`, `selection_ms`, `policy_ms` und `total_ms`. Die Ausgabe enthält den letzten Lauf, Total-p50/p95 und Embedding-Cache-Diagnose. Keine Prompts, Antworten, Tool-Argumente/-Ergebnisse, Dateien oder Credentials.

## Readiness

Skills können deklarieren:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  mcps: [codebase-memory]
  config: [GITHUB_TOKEN]
```

Status bleiben `ready`, `unknown`, `setup_required`, `dependency_missing`, `broken` und `disabled`.

## Policy, Enforcement, Audit, Quality, Learning

Die deterministische Policy bleibt für alle Routing-Modi autoritativ. Enforcement-Modi: `off`, `warn`, `primary`, `all`; Standard `warn`. Audit/Quality bewerten technische Routing-Ausführung, nicht die fachliche Richtigkeit der Antwort. Learning-Modi: `off`, `shadow`; v0.8.0 besitzt bewusst kein aktives selbstveränderndes Routing.

## OpenViking

OpenViking bleibt im Repository kompatibel, aber empfohlen ist:

```yaml
openviking_enabled: false
```

Für spätere Aktivierung bleiben `openviking_read_enabled` und `openviking_auto_write_enabled` getrennt verfügbar.

## Konfigurationsreferenz

CI prüft, dass diese Schlüssel und Defaults mit `plugin.yaml` und der englischen README übereinstimmen.

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

## Sicherheit und Datenschutz

- Profil-State bleibt über einen undurchsichtigen Profil-Scope getrennt.
- Session-Kontinuität verwendet einen gehashten Session-Key und nur Routing-Metadaten.
- Keine Prompts, Antworten, Tool-Payloads/-Ergebnisse, Dateien oder Credentials in Follow-up-/Performance-State.
- Codebase-Memory-MCP wird nur passiv geprüft.
- Rollout-Preflight ist read-only und kann keine Profile oder Gateways verändern.
- `skill_view` bleibt der Ausführungspfad für Skill-Prozeduren.
- Embedding-Ausfall führt im laufenden Hybrid-Routing zum deterministischen Fallback; der Rollout-Preflight blockiert Hybrid/Embedding bei einem ungesunden konfigurierten Endpunkt.
- OpenViking bleibt standardmäßig deaktiviert.

## Entwicklung und CI

```bash
python -m pytest -q
python scripts/benchmark-routing-quality.py
python scripts/check-doc-config-sync.py
python -m compileall -q .
hermes plugins doctor . --ci
```

CI prüft Python 3.11/3.12/3.13, bekannte Hermes-Revisionen und Hermes `main` zusätzlich informativ.

## Lizenz

MIT. Siehe `LICENSE`.
