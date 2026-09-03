# Hermes Skill Router

Ein dauerhaft aktiver, profilspezifischer Skill-Planer für [Hermes Agent](https://github.com/NousResearch/hermes-agent) mit optionaler [OpenViking](https://github.com/volcengine/OpenViking)-Indexierung und semantischer Suche.

Das Plugin erfasst die tatsächlich verfügbaren Skills jedes Hermes-Profils, liest deren `SKILL.md`, erzeugt mit einem konfigurierbaren Hermes-Hilfsmodell einen Einsatzplan, spiegelt Katalog und Plan nach OpenViking und empfiehlt vor jeder Benutzeraufgabe die passenden Skills in der richtigen Reihenfolge. Die ausgewählten Anweisungen werden weiterhin über Hermes `skill_view` geladen.

> Status: frühe Community-Version (`0.5.0`). Vor unbeaufsichtigtem Einsatz mit den eigenen Hermes- und OpenViking-Versionen testen.

## Warum Plugin und Skill kombiniert werden

Eine einzelne `SKILL.md` wird nur bei Bedarf geladen. Sie kann nicht dauerhaft aktiv bleiben, Skill-Änderungen beobachten oder vor jeder Anfrage dynamische Empfehlungen einfügen. Dieses Repository enthält deshalb:

- ein Hermes-Plugin für Lebenszyklus, Planung, Speicherung, OpenViking-Synchronisierung und Routing;
- den Skill `skill-router:skill-router` für Bedienung und Diagnose;
- kein zusätzliches dauerhaftes Model-Tool-Schema.

## Ablauf

1. Das Plugin registriert einen kurzen dauerhaften Systemhinweis, Lifecycle-Hooks, Befehle und den Hilfsmodell-Task `skill_router_planner`.
2. Die erste neue Session scannt das aktive Profil, erzeugt einen deterministischen Basisplan und stellt den Hintergrundabgleich in die Warteschlange. Eine Anreicherung der Modellmetadaten erfolgt nur im Modell-Routingmodus. `refresh` bleibt ein Diagnose-Fallback und ist kein Installationsschritt.
3. Hermes liefert den effektiven Katalog aus vertrauenswürdigen Projekt-Skills, lokalen Profil-Skills, externen Verzeichnissen und aktiven Plugin-Skills.
4. Deklarierte Befehls-, Python-Modul-, Skill-, MCP-Server- und Konfigurationsanforderungen werden beim Katalog-Refresh passiv geprüft und mit dem Plan gespeichert. Der Router führt weder Setup noch MCP-Verbindungen aus.
5. Nur neue oder geänderte Skill-Dokumente werden erneut analysiert.
6. OpenViking erhält profilspezifische Skill-Spiegel und den Plan unter `viking://~/resources/hermes-skill-router/{profil-scope}/plan.md`.
7. Wenn aktiviert, liefert OpenViking vor jeder Aufgabe semantische Treffer. Das Hermes-Hilfsmodell wählt daraus und aus dem vollständigen Plan null bis fünf existierende Skills samt Reihenfolge. Deterministisches Routing verwendet auch nach Modell-Timeouts und -Fehlern dasselbe strikte No-Skill-Gate.
8. Ein deterministisches Policy Gate prüft Katalog-Readiness, explizite Benutzerwünsche, Alternativen, deklarierte Skill-Abhängigkeiten, Rollen, Dependency-Reihenfolge und das Skill-Limit. Modellausgaben umgehen diese Schicht nicht.
9. Der finale Policy-Plan initialisiert einen turn-isolierten Execution Guard. Der Standardmodus warnt nur; optionale harte Modi verlangen über `pre_tool_call` erfolgreiche geordnete `skill_view`-Aufrufe vor Task-Tools.
10. Hermes erhält einen dynamischen `[Skill Router]`-Block und lädt die validierten Skills nativ mit `skill_view`.
11. Die öffentlichen Observer `post_tool_call` und `post_llm_call` ordnen erfolgreiche `skill_view`-Aufrufe und kompakte Guard-Ergebnisse der validierten Routing-Entscheidung zu. Der Audit selbst blockiert nichts, wiederholt nichts und verändert kein Ranking.
12. Jeder finalisierte Audit erhält eine versionierte deterministische Bewertung der technischen Routing- und Ausführungsqualität.
13. Aktuelle hochwertige Quality-Historie wird in profilspezifische Skill-/Rollen-Aggregate und konservative diagnostische Bias-Werte umgebaut. Ein separater Shadow-Vergleich wird gespeichert, während die reale Auswahl unverändert bleibt.
14. Erstellen, Installieren, Patchen, Bearbeiten, Archivieren, als veraltet Markieren und Wiederherstellen eines Skills löst einen zusammengefassten inkrementellen Refresh und nach dem 30-Sekunden-Cachefenster eine zweite Prüfung aus. Intervallbegrenzte Prüfungen beim Session-Start und vor Turns erkennen Änderungen ohne Lifecycle-Event.

Jedes Hermes-Profil besitzt einen eigenen Plan und eine begrenzte Audit-Historie in `ctx.state`; Profile beeinflussen sich nicht gegenseitig. Snapshot-, Audit-, Learning- und Setup-Inventar-Umschläge tragen einen undurchsichtigen Scope-Token des kanonischen Profilverzeichnisses. Bei Klonen oder Umbenennen kopierter State wird deshalb vor Katalognutzung und OpenViking-Abgleich verworfen, ohne den Pfad offenzulegen.

## Kompatibilität

Die Lifecycle-, Profil- und nativen MCP-Konfigurations-APIs wurden gegen Hermes-Main-Commit `a399ac2fd13da28630d3a90c255d0be458dded61` geprüft und mit `hermes plugins doctor` validiert. OpenViking `0.4.17.1` ist die geprüfte API-Version. Vor dem Aktivieren auf einer anderen Hermes-Version `hermes plugins doctor . --ci` ausführen.

## Schnellinstallation

Der bevorzugte Hermes-first-Ablauf ist eine direkte Bitte an Hermes: **„Installiere den Skill Router aus `MKI13/hermes-skill-router`.“** Hermes verwendet dafür seine normalen Terminal-, Plugin-, Approval- und After-Install-Mechanismen. Benutzer müssen keine Profilverzeichnisse kennen oder bearbeiten.

Der entsprechende Terminal-Ablauf installiert das Plugin einmal im aktiven Profil und führt anschließend den standardmäßig schreibgeschützten Setup-Plan aus:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
hermes skill-router setup
```

Der Installer zeigt `after-install.md`. Erst den erkannten Profilplan prüfen und anschließend ausdrücklich anwenden; die Installation führt niemals automatisch ein Profil-Apply aus.

Hermes installiert und aktiviert Git-Plugins physisch pro Profil. Der Router folgt diesem nativen Modell: `setup --apply` ruft den offiziellen profilbezogenen Hermes-Installer und die Config-Befehle nacheinander auf. Dadurch muss der Benutzer die Installation nicht für jedes Profil manuell wiederholen.

Dry-Run prüfen und anschließend anwenden:

```bash
hermes skill-router setup --dry-run
hermes skill-router setup --apply
hermes skill-router profiles
```

Nach Erstellen, Löschen oder Umbenennen von Profilen erkennt `hermes skill-router profiles --sync` neue und entfernte Namen. Dieser ausdrücklich angeforderte Sync ergänzt fehlendes sicheres Router-Setup über offizielle Hermes-Befehle und speichert im Inventar-State ausschließlich die erkannten Namen. Profile werden nicht gelöscht, explizite Werte nicht überschrieben, deaktivierte Installationen nicht aktiviert und Profil-States nicht zusammengeführt.

Jedes Profil behält eigene Plugin-Konfiguration, sichtbare Skills, Readiness, Audits und Learning-Daten. Schlägt ein Profil fehl, bleiben erfolgreiche Profile bestehen und werden getrennt ausgewiesen.

## Funktionsweise der Profilerkennung

Die Compatibility-Schicht fragt Hermes nach den aktuellen Profilnamen und inspiziert jedes Profil über profilbezogene Hermes-Befehle. Das Setup errät keine Verzeichnisnamen, kopiert keinen Plugin-State und vereinigt keine sichtbaren Skills mehrerer Profile. Neue, entfernte und umbenannte Profile erscheinen beim nächsten ausdrücklichen `profiles --sync`; das gespeicherte Inventar enthält nur Namen und einen undurchsichtigen Scope-Token.

## Automatische Erkennung neuer Skills

Hermes-Lifecycle-Events für erstellte, installierte, gepatchte, bearbeitete, archivierte, veraltete und wiederhergestellte Skills starten unmittelbar einen einzelnen zusammengefassten Hintergrund-Refresh sowie eine Cache-settled-Prüfung nach Hermes' Content-Cachefenster. Neue und geänderte Skills erhalten aktuelle Readiness- und Routing-Metadaten; Content-Analyse läuft nur bei veränderten Analyse-Eingaben. Erfolgreiche autoritative Scans entfernen nicht mehr sichtbare Skills. Da Hermes kein Delete-/Uninstall-Event bereitstellt und manuelle Dateiänderungen kein Event liefern müssen, dienen Session-Start und intervallbegrenzte Fingerprint-Prüfungen vor Turns als Fallback.

`/skill-router events [N]` beziehungsweise `hermes skill-router events [N]` zeigt bis zu 50 profilspezifische technische Änderungen. Gespeichert werden ausschließlich Zeitstempel, Event-Arten, Skill-Namen, Ergebnisse und Readiness – niemals Skill-Inhalte, Prompts, Konfiguration, Fehler oder Zugangsdaten. `status` zeigt nur die letzte Skill-Änderung und einen eventuell ausstehenden Refresh.

## Funktionsweise MCP-gestützter Skills

Der Router routet weiterhin ausschließlich Hermes-Skills. Ein MCP-Server bleibt eine Hermes-Tool-Capability und wird niemals direkt bewertet oder ausgewählt. Ein routbarer Skill kann die exakte MCP-Server-Identität des aktiven Profils deklarieren:

```yaml
---
name: codebase-memory
description: Inspect an indexed codebase and retrieve structural code context.
requirements:
  mcps:
    - codebase-memory
---
```

Die Identität ist der exakte Schlüssel unter `mcp_servers` in der Hermes-Konfiguration des aktiven Profils. Die Compatibility-Schicht liest nur Servernamen, den passiven Enabled-Zustand und das Vorhandensein einer erkennbaren Transportdefinition. Sie kopiert keine Umgebungsvariablen, Header, Tokens oder Zugangsdaten und startet, prüft, lädt oder verwendet keinen MCP-Server. Fehlende oder deaktivierte Server ergeben `dependency_missing`; nicht verfügbare oder strukturell unklare passive Erkennung ergibt `unknown`. Eine spätere profilbezogene MCP-Konfigurationsänderung wird beim Session-Start oder der nächsten Katalog-/Readiness-Fingerprint-Prüfung sichtbar.

**Die Installation eines MCP allein macht ihn nicht zu einem routbaren Skill.** Dafür muss ein Hermes-Skill erstellt oder installiert werden, der den MCP referenziert und Hermes nach dem Laden durch `skill_view` zur Verwendung seiner Tools anweist. Ein MCP ohne diesen Skill erzeugt keinen Router-Katalogeintrag. MCP-Anforderungen beeinflussen Readiness, nicht den semantischen Relevanzwert; zwischen Profilen wird kein MCP-Inventar geteilt.

## Sichere Standards

Das adaptive Setup ergänzt nur fehlende Werte mit deterministischem Routing, Warn-Enforcement, Shadow Learning und deaktiviertem OpenViking. Explizite Einstellungen und absichtlich deaktivierte Installationen bleiben erhalten. Ohne ausdrückliches `--apply` oder `--sync` bleibt das Setup ein Dry-Run.

## Canary-Setup

Ein begrenzter Rollout verwendet einen zur Laufzeit entdeckten Profilnamen:

```bash
hermes skill-router setup --target-profile <profil>
hermes skill-router setup --target-profile <profil> --apply
```

Aktuelle Hermes-Versionen reservieren `--profile` positionsunabhängig als globalen Selektor. Der Router-Alias benötigt deshalb `hermes --profile <aufrufendes-profil> skill-router setup --profile <zielprofil> --apply`; `--target-profile` vermeidet diese Mehrdeutigkeit.

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
/skill-router events 20
/skill-router refresh
/skill-router plan
/skill-router inspect github
/skill-router audit
/skill-router audit last
/skill-router quality
/skill-router quality last
/skill-router learning
/skill-router learning github
/skill-router learning last
/skill-router learning rebuild
/skill-router learning reset
/skill-router enforcement
/skill-router recommend Erstelle und prüfe einen GitHub Pull Request
```

Im Terminal:

```bash
hermes skill-router setup
hermes skill-router setup --apply
hermes skill-router setup --target-profile <profil> --apply
hermes skill-router profiles
hermes skill-router profiles --sync
hermes skill-router status
hermes skill-router events 20
hermes skill-router refresh --wait
hermes skill-router plan
hermes skill-router inspect github
hermes skill-router audit
hermes skill-router audit last
hermes skill-router quality
hermes skill-router quality last
hermes skill-router learning
hermes skill-router learning github
hermes skill-router learning last
hermes skill-router learning rebuild
hermes skill-router learning reset
hermes skill-router enforcement
hermes skill-router recommend Erstelle und prüfe einen GitHub Pull Request
```

## Readiness-Deklarationen

Ein Skill kann passive Anforderungen im Frontmatter seiner `SKILL.md` deklarieren:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  mcps: [codebase-memory]
  config: [GITHUB_TOKEN]
```

Die älteren Hermes-Felder `prerequisites.commands` und `prerequisites.env_vars` werden ebenfalls erkannt. Ohne Deklaration bleibt ein Skill `unknown`; er wird nicht automatisch als einsatzbereit betrachtet. Fehlende Befehle, Module, Skills oder konfigurierte und aktivierte MCP-Server ergeben `dependency_missing`. Eine nicht verfügbare passive MCP-Erkennung ergibt `unknown`. Fehlende deklarierte Konfiguration oder `setup_required: true` ergeben `setup_required`. Der Router zeigt nur Namen und Verfügbarkeit an und gibt niemals konfigurierte Werte aus, startet keine MCP-Verbindung, installiert nichts, meldet sich nirgendwo an und verändert keine Konfiguration.

`/skill-router inspect <skill-name>` zeigt die gespeicherten Prüfergebnisse. Die Readiness wird beim Katalog-Refresh statt bei jedem Turn neu berechnet.

## Deterministische Routing-Policy

`skill_router_plugin/policy.py` validiert Modell- und deterministische Auswahlen, ohne semantisch neu zu ranken. Unbekannte Modellfelder werden ignoriert, höchstens eine Primary-Rolle bleibt erhalten und bei reinen Supporting-Auswahlen wird der erste gültige Skill Primary. Automatisch ausgewählte kaputte oder deaktivierte Skills werden entfernt. `setup_required` und `dependency_missing` bleiben nur nach den dokumentierten expliziten beziehungsweise Fallback-Regeln sichtbar. Ein explizit verlangter kaputter oder deaktivierter Skill ergibt `policy=blocked` ohne ausführbare Empfehlung; Hermes selbst arbeitet normal weiter.

Deklarierte `requirements.skills` werden transitiv ergänzt und vor dem abhängigen Skill geladen, während dieser seine Primary-Rolle behält. Finale Dependency-Auswahlen tragen begrenzte Metadaten `required_by_dependency` und `required_for`, damit Quality deklarierte Kanten ohne semantische Interpretation prüfen kann. Erforderliche Dependencies verdrängen optionale Supporting-Skills am Limit. Fehlende oder unbrauchbare Dependencies blockieren den betroffenen Primary. Zyklen ergeben eine degradierte deterministische Reihenfolge mit Warnung. Deklarierte Alternativen werden nach explizitem Wunsch, Readiness und ursprünglicher Auswahlposition aufgelöst. Policy-Statuswerte sind `valid`, `adjusted`, `degraded` und `blocked`.

Deterministisches Routing verlangt für einen impliziten Primary mindestens `deterministic_min_score` (Standard `20`). Dieser Standard trennt im anonymisierten Produktionsaggregat mit 76 Skills den höchsten No-Skill-Wert (`17`) vom niedrigsten beabsichtigten Skill-Wert (`24`); das datenschutzfreundliche Aggregat liegt unter `tests/fixtures/production_score_calibration.json`. Readiness beeinflusst Reihenfolge und Policy, erzeugt aber allein keine Relevanz. Ein an Wortgrenzen erkannter expliziter Skill-Wunsch umgeht den Score-Grenzwert, bleibt jedoch Readiness und Policy unterworfen; lokal negierte oder zitierte Namen gelten nicht als explizite Wünsche. Höchstens `max_optional_supporting_skills` (Standard `1`) nicht expliziter Supporting-Skill bleibt erhalten; nötig sind eine erkennbare Mehrfachabsicht, mindestens `deterministic_supporting_min_score` (Standard `24`) und entweder eine deklarierte `works_with`-Beziehung oder zwei passende Namensbegriffe innerhalb von 12 Punkten zum Primary. Deklarierte Dependencies zählen nicht gegen dieses optionale Supporting-Limit. Ein passender `avoid_when`-Konflikt zieht 12 Punkte ab. OpenViking-Evidenz ab `0.9` genügt weiterhin für einen Primary. `/skill-router recommend <task>` zeigt bei einem No-Match den stärksten Kandidaten, dessen Relevanzwert und den erforderlichen Wert.

## Kontrollierte Skill-Ausführung

`skill_router_plugin/enforcement.py` verfolgt ausschließlich den finalen Policy-Plan des aktuellen Hermes-Turns. Der Standardmodus `warn` erlaubt jedes Tool, erfasst aber einen verfrühten Task-Tool-Aufruf. `primary` verlangt den dependency-geordneten Plan bis einschließlich Primary-Skill, während `all` alle ausführbaren finalen Auswahlen in Policy-Reihenfolge verlangt. `off` deaktiviert die Prüfung, ohne den Audit abzuschalten. Nur erfolgreiche `skill_view`-Aufrufe erfüllen den Guard; `skill_view`, `skills_list` und zusätzliche nicht verlangte Skill-Ladevorgänge bleiben erlaubt.

Die harten Modi verwenden die öffentliche `pre_tool_call`-Block-Direktive von Hermes. Aufrufe aus derselben Hermes-API-Anfrage teilen sich einen Budgetplatz, sodass parallele Tool-Aufrufe den Guard nicht umgehen. Nach dem konfigurierten Block-Limit wechselt der Turn zu `exhausted` und läuft offen weiter, sodass keine permanente Block-Schleife entsteht. Fehlende Turn- oder API-Request-Identität, nicht verfügbare Hooks und vom Plugin abgefangene Guard-Exceptions laufen ebenfalls offen weiter. Ein blockierter Policy-Plan wird nie enforced. `/skill-router enforcement` zeigt Capability, Modus, Limit und kompakten Zustand des aktuellen Turns, ohne die Konfiguration zu verändern.

## Routing-Ausführungs-Audit

Für jeden gerouteten Turn speichert der Router Task-Hash, undurchsichtige Hermes-Task-/Turn-/Session-IDs, Routing-Methode, Policy-Status, finale validierte Skill-Namen und Rollen, erfolgreiche oder fehlgeschlagene `skill_view`-Beobachtungen, Ergebnis und den Ladezustand des Primary-Skills. Zusätzlich werden Enforcement-Modus und -Status, Block-Anzahl und der Primary-Ladezustand vor dem ersten erlaubten Task-Tool gespeichert. Mögliche Ergebnisse sind `complete`, `partial`, `missed`, `not_applicable` und `unknown`. Ohne beide benötigten Observer-Hooks oder bei abgebrochener Finalisierung bleibt die Bewertung `unknown`.

`/skill-router audit` fasst die letzten 20 Einträge zusammen, `/skill-router audit last` zeigt die letzte Empfehlung mit Ladeergebnis und `/skill-router audit N` fasst die letzten `N` Einträge zusammen. Die Historie ist profilspezifisch und begrenzt. Nur ein SHA-256-Task-Hash bleibt erhalten; Prompts, Task-Previews, Antworten, Skill-Inhalte, Tool-Ergebnisse, Fehlermeldungen, Dateien und Zugangsdaten werden nicht gespeichert.

## Routing-Qualitätsbewertung

`skill_router_plugin/quality.py` ergänzt jeden finalisierten Audit um einen deterministischen Datensatz mit `quality_version: 1`, Score von 0,0 bis 1,0, Grade, Confidence, technischen Signalen und expliziten Penalties. Bewertet wird, ob der Routing-Prozess technisch sauber ablief: Policy-Status, erfolgreiche notwendige Loads, Dependency-Reihenfolge, Guard-Verhalten, Ladefehler und der Primary-Load vor Task-Tools. Nicht bewertet wird, ob die abschließende fachliche Antwort von Hermes richtig war.

Das Scoring startet bei 1,0 und zieht zentral definierte Penalties ab. Angepasste oder degradierte Policy, partielle oder verfehlte Audits, fehlende Primary-/Dependency-/Supporting-Loads, `skill_view`-Fehler, Warnungen, Blocks, Exhaustion, verspäteter Primary-Load und verletzte Dependency-Reihenfolge reduzieren den Score. Eine sicher blockierende Policy gilt als bewertbares Safety-Verhalten und nicht automatisch als Fehler. Turns mit `not_applicable`, unfertige Audits oder fehlende Observer sind nicht bewertbar und erhalten unbekannten Score, Grade und Confidence.

Grades sind `excellent` ab 0,90, `good` ab 0,75, `acceptable` ab 0,55, `poor` ab 0,30 und `failed` darunter. Confidence ist hoch, wenn finalisierte Observer-Daten, vollständige Hermes-IDs, Ladeergebnisse, Task-Tool-Zeitpunkt und Dependency-Reihenfolge vorliegen; fehlende technische Evidenz reduziert sie auf mittel oder niedrig. Modell- und deterministisches Routing verwenden dieselben Regeln. `/skill-router quality`, `/skill-router quality N` und `/skill-router quality last` zeigen aggregierte beziehungsweise letzte technische Ergebnisse. Quality bleibt passiv und verändert weder Ranking, Policy, Readiness, Enforcement, OpenViking-Scores noch Skill-Metadaten.

## Shadow Learning

`skill_router_plugin/learning.py` baut deterministisch Aggregate mit `learning_version: 1` aus dem begrenzten Profil-Audit unter `router.learning` neu auf. Nutzbar sind nur bewertbare aktuelle Quality-Datensätze, die im Modus `shadow` mit hoher oder mittlerer Confidence erfasst wurden. Hohe Confidence erhält Gewicht 1,0, mittlere 0,35; niedrige, unbekannte, inkompatible und nicht bewertbare Datensätze werden ignoriert. Eine sanfte zeitliche Gewichtung von `0.985` bevorzugt neuere begrenzte Beobachtungen, ohne ältere Evidenz zu löschen.

Evidenz wird nur dem Skill zugeordnet, den sie beschreibt: erfolgreicher oder fehlender Load, Load Error dieses Skills, rechtzeitiger Primary-Load und Reihenfolge der deklarierten Dependency-Kante. Turn-weite Quality und Completion werden nicht in einen Skill-Score kopiert. Primary-, Supporting- und Dependency-Beobachtungen bleiben getrennt. Der Shadow-Primary-Bias nutzt nur Primary-Rollen-Evidenz, verlangt mindestens `learning_min_samples` rohe Samples sowie 50 Prozent effektive gewichtete Evidenz und verwendet konservative Shrinkage um einen neutralen technischen Score. Das Ergebnis ist auf `-0.20` bis `+0.20` begrenzt.

Realer Planner und Policy erhalten exakt die bestehende unveränderte Auswahl. Der Shadow-Vergleich berücksichtigt nur Nicht-Dependency-Auswahlen derselben Readiness-Klasse wie der reale Primary; Broken, Disabled, Dependency-Missing und abweichend bereite Kandidaten können nicht hochgestuft werden. Jeder explizite Skill-Wunsch unterdrückt Shadow-Umsortierung. Im Audit bleiben nur realer Primary, Shadow-Primary, Modus und Changed-Flag. Diese Daten werden weder injiziert oder enforced noch als reale Empfehlung auditiert, an OpenViking gesendet oder als Routing-Feedback verwendet.

`/skill-router learning` liest das aktuelle Aggregat, `/skill-router learning <skill>` zeigt Rollen-Samples und technische Raten, und `/skill-router learning last` zeigt den letzten Actual-vs-Shadow-Vergleich. `learning rebuild` erzeugt den State vollständig aus erhaltener Audit-/Quality-Historie. `learning reset` löscht nur `router.learning`; Audit, Quality, Plan und OpenViking-Daten bleiben erhalten, sodass ein späterer expliziter oder Routing-ausgelöster Rebuild die abgeleiteten Aggregate wiederherstellt. `learning_mode: off` erfasst keine nutzbaren Learning-Beobachtungen und führt keine Shadow-Umsortierung aus. Einen Modus `active` gibt es nicht.

## Einstellungen

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: deterministic     # deterministic | model
        deep_refresh_on_start: true
        rescan_interval_seconds: 60
        max_skills_per_task: 4
        deterministic_min_score: 20
        deterministic_supporting_min_score: 24
        max_optional_supporting_skills: 1
        max_audit_entries: 100          # begrenzt auf 10-1000
        learning_mode: shadow           # off | shadow; kein active-Modus
        learning_min_samples: 5         # begrenzt auf 3-100 und Audit-Limit
        enforcement_mode: warn          # off | warn | primary | all
        max_enforcement_blocks_per_turn: 2  # begrenzt auf 1-5
        max_skill_chars: 20000
        analysis_batch_size: 6
        analysis_model_timeout_seconds: 25
        routing_catalog_chars: 60000
        routing_model_timeout_seconds: 20
        openviking_enabled: false
        openviking_url: http://127.0.0.1:1933
        openviking_timeout_seconds: 10
        openviking_retrieval_limit: 12
        openviking_routing_timeout_seconds: 3
        openviking_score_threshold: 0.15
        openviking_plan_uri: "viking://~/resources/hermes-skill-router/{profile}/plan.md"
```

## Fehlerdiagnose

Zuerst `/skill-router status` ausführen und anschließend `events` prüfen, wenn eine Skill-Änderung nicht sichtbar ist. `refresh --wait` bleibt der ausdrückliche Diagnose-Fallback. Der Status meldet neben den bisherigen Hermes-Capabilities auch die passive native MCP-Konfigurationserkennung als `available` oder `unavailable`.

## Sicherheit und bekannte Grenzen

- OpenViking liefert nur Retrieval-Hinweise und Skill-Namen. Die dort gespeicherte Kopie wird nicht direkt als ausführbare Anweisung eingefügt.
- Die Ausführungs-Observer verwerfen Prompt-, Antwort-, Task-Tool-Argument-, Tool-Ergebnis- und Fehlerdaten bereits an der Compatibility-Grenze. Persistiert werden nur Identifikatoren, Task-Hashes, Skill-Namen, Rollen, Reihenfolge, Zeitpunkte, Routing-/Policy-/Enforcement-Statuswerte, begrenzte Block-Zähler und Ergebnisse.
- Bei einem Policy-Fehler wird die ungeprüfte Auswahl verworfen und ein leerer degradierter Plan geliefert; rohe Modellausgaben werden nie als Fallback injiziert.
- Die Quality-Auswertung liest nur bereinigte begrenzte Audit-Metadaten und ruft kein Modell auf. Sie besitzt keinen Rückkanal zu Routing oder Ranking.
- Shadow Learning speichert nur begrenzte technische Aggregate je Skill und Rolle. Es kopiert weder Task-Hash, Prompt, Antwort, Tool-Argument/-Ergebnis, Fehlertext, Datei, Zugangsdaten noch Skill-Inhalt und kann Routing-Metadaten oder OpenViking nicht verändern.
- Entfernte Spiegel werden nur gelöscht, wenn ihr Name zuvor als Router-Eigentum im Profilzustand gespeichert wurde.
- Die HTTP-Brücke blockiert URL-Zugangsdaten, Pfade, Query-Strings, Redirects, Proxys, Metadaten-/Link-Local-Ziele und übergroße Antworten. Zugangsdaten außerhalb von Loopback erfordern HTTPS.
- Das Hilfsmodell erhält Skill-Dokumente ausdrücklich als nicht vertrauenswürdige Analysedaten.
- Hermes besitzt derzeit keine öffentliche Plugin-API, die gleichzeitig exakte Rohdateien, alle Quellen, Provenienz und eine erzwungene Cache-Aktualisierung anbietet. Alle versionsabhängigen Hermes-Imports und Pfadzugriffe liegen deshalb in `skill_router_plugin/compat/hermes.py` und werden über Feature Detection geprüft. Fehlt eine benötigte interne API oder ist sie inkompatibel, verwendet der Router ausschließlich Katalogmetadaten.
- `/skill-router status` zeigt `full` oder `degraded` sowie die Verfügbarkeit von Raw Reader, Plugin-Skill-Lookup, Lifecycle-Hook, native MCP-Konfigurationserkennung, Auxiliary Tasks, Skill-Ausführungs-Audit und Execution Guard. Der Audit benötigt die öffentlichen Hooks `post_tool_call` und `post_llm_call`. Hartes Enforcement benötigt zusätzlich `pre_tool_call`; schlägt dessen Registrierung fehl, meldet der Guard `unavailable` und läuft offen weiter, ohne Routing oder Audit zu beeinträchtigen.
- Der Lifecycle-Hook meldet derzeit kein Löschen oder Deinstallieren. Die regelmäßige Katalogprüfung erkennt solche Änderungen später.
- Änderungen innerhalb einer `SKILL.md` können wegen Hermes-Cachezeiten ungefähr 30 Sekunden verzögert erscheinen.
- Ein bereits bestehender System-Prompt wird aus Cache-Gründen nicht verändert. Die dynamische Empfehlung wird trotzdem bei jedem Turn über `pre_llm_call` ergänzt.
- Hermes begrenzt `pre_llm_call` standardmäßig auf 30 Sekunden. Die Router-Timeouts bleiben darunter; bei Zeitüberschreitung läuft Hermes für diesen Turn ohne Router-Kontext weiter.
- Native Hermes-Plugins laufen als vertrauenswürdiger Python-Code im Prozess. Quellcode vor dem Aktivieren prüfen.

## Entwicklung und Prüfung

```bash
python -m pytest -q
python scripts/benchmark-routing-quality.py
python -m compileall -q .
hermes plugins doctor . --ci
```

## Lizenz

MIT, siehe [LICENSE](LICENSE).
