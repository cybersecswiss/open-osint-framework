# Was hier liegt — und was bewusst nicht mehr

`n8n/entrypoint.sh` importiert **jede** Datei aus diesem Verzeichnis bei
jedem Start und aktiviert einen Teil davon. Was hier liegt, läuft also.
Deshalb gehört hierher nur, was n8n auch wirklich machen soll.

| Datei | Aktiv | Wofür |
|---|---|---|
| `ai-link.json` | ✅ | KI-Verknüpfung über Gemini. Der Prompt ist **absichtlich** hier und nicht im Code: der Betreiber soll ihn ohne Rebuild ändern können. |
| `ai-link-local.json` | — | Dasselbe gegen ein lokales Modell. Inaktiv, bis eines steht. |
| `ai-news.json` | ✅ | Lagebild-Analyse. Gleiche Begründung wie `ai-link`. |

## Drei frühere Workflows wurden entfernt

Alle drei macht das Backend selbst, und ein importierter Workflow, der
dasselbe noch einmal tut, ist keine Redundanz — er ist eine Doppelung, die
zuschlägt, sobald jemand ihn aktiviert.

| Entfernt | Ersetzt durch | Warum |
|---|---|---|
| `scheduled-rescan.json` | `services/scheduler.py` → `monitoring_rescan_loop` | Konnte **nie** funktionieren: der zweite Aufruf `POST /search` akzeptiert den internen Schlüssel nicht (403). Der erste, `GET /monitoring/pending-scans`, gelang und schob den Zeitplan weiter — der Workflow verbrauchte also den Termin jeder fälligen Überwachung und suchte nichts, während die Oberfläche „zuletzt vor N Minuten geprüft" meldete. |
| `change-detection-alert.json` | `services/alerting.py` + `services/notify.py` | Rief `GET /entities/{id}/diff` auf, das es nicht gab (404), und niemand rief seinen Webhook. |
| `license-expiry.json` | `services/operator_notify.py` → `license_expiry_loop` | Brauchte eine SMTP-Anmeldung in n8n und den internen Schlüssel; auf einer Frischinstallation wurde es gar nicht erst aktiviert, und **nichts sagte das**. Eine Lizenz, die unbemerkt abläuft, nimmt einen Kunden vom Netz. |

Die drei Gründe sind jedes Mal dieselben, und sie sind die Faustregel für
alles Weitere:

1. **Es muss ohne Workflow-Import funktionieren.** Eine Frischinstallation
   importiert diese Dateien zwar, aber ein Kundenserver hat kein n8n — und
   selbst hier ist „der Workflow war nicht aktiviert" ein stiller Ausfall.
2. **Kein zweiter Authentifizierungspfad.** Jeder Workflow, der Backend
   oder Lizenzserver aufruft, braucht dafür einen Schlüssel an einer
   Stelle, an der er nicht sein müsste.
3. **Der Audit-Eintrag braucht einen ehrlichen Urheber.** Aus dem Backend
   heraus steht dort `scheduler`; aus n8n heraus steht dort niemand.

**Ein neuer Workflow gehört also nur hierher, wenn ein Mensch ihn bearbeiten
können soll** — so wie die KI-Prompts. Alles andere gehört in den Scheduler.
