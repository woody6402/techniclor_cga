# Home Assistant: Technicolor CGA Gateway (Custom Component)

Dieses Projekt stellt mehrere **Sensor-Entities** für ein Technicolor CGA‑Gateway in Home Assistant bereit. Es liest u. a. System‑ und DHCP‑Informationen aus, listet verbundene Hosts auf und bietet einen **Delta‑Sensor** zur Erkennung vermisster/inaktiver Geräte. Alle Entities werden dank `device_info` unter **einem Gerät** im Geräte‑ und Integrationsregister gebündelt.

## Features

- **Systemstatus** (z. B. `CMStatus`) inkl. Durchreichen weiterer Systemattribute
- **DHCP‑Sensoren** für alle zurückgelieferten DHCP‑Schlüssel
- **Hostliste** mit Anzahl der aktuell erkannten Geräte (`hostTbl`)
- **Missing‑Devices / Delta‑Sensor**: zeigt Geräte, die verschwunden oder inaktiv sind
- **Sauberes Geräte‑Clustering** via `device_info` (Identifier = `(DOMAIN, host)`, Hersteller, Name, `configuration_url`); Modell/Firmware werden – falls verfügbar – ergänzt
- **Automatisches Polling** alle 5 Minuten

## Verzeichnisstruktur (Beispiel)

```
custom_components/technicolor_cga/
├─ __init__.py
├─ config_flow.py
├─ manifest.json
├─ const.py
├─ technicolor_cga.py
└─ sensor.py            
```

## Installation

1. Diesen Ordner nach `config/custom_components/technicolor_cga/` kopieren.
2. Home Assistant **neu starten**.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen** und den Eintrag *Technicolor CGA* auswählen.
4. Zugangsdaten eingeben:
   - **Host** (z. B. `192.168.0.1`)
   - **Username**
   - **Password**

> Die Integration verwendet **Config Entries** (UI‑basierte Einrichtung).

## Angelegte Entities

### System‑Sensor
- **Name:** `Technicolor CGA System Status`
- **State:** Wert von `CMStatus` (oder `"Unknown"`)
- **Attribute:** Alle weiteren Systemfelder (z. B. `ModelName`, `SoftwareVersion` etc.).
- **Device Info:** `model`/`sw_version` werden – sofern vorhanden – aus den Systemdaten gesetzt.

### DHCP‑Sensoren
- **Name:** `Technicolor CGA DHCP <Key>` (für jeden Schlüssel aus `dhcp()`)
- **State:** Entspr. Wert aus den DHCP‑Daten (oder `"Unknown"`).

### Host‑Sensor
- **Name:** `Technicolor CGA Host List`
- **State:** Anzahl der Einträge in `hostTbl`.
- **Attribute:** Vollständige Host‑Datenstruktur (z. B. `hostTbl`, Einträge mit `physaddress`, `ipaddress`, `hostname`, `active`).

### Delta‑/Missing‑Devices‑Sensor
- **Name:** `Technicolor CGA Missing Devices`
- **State:** Anzahl der erkannten *fehlenden* oder *inaktiven* Geräte.
- **Attribute:**
  - `missing_devices`: Liste von Dicts `{mac, last_ip, hostname, status}`
  - `known_devices`: Liste erkannter Geräte `{mac, last_ip, hostname}`
- **Hinweise:**
  - Die Liste `known_devices` wird **zur Laufzeit gelernt** (kein Persisting über Neustarts).
  - Sortierung erfolgt numerisch nach IP; ungültige IPs landen am Ende.

## Aktualisierungsintervall

Standardmäßig alle **5 Minuten** (`SCAN_INTERVAL = 300s`).

**Tipps:**
- Prüfe `Host`, `Username`, `Password` und ob das Web‑Interface erreichbar ist.
- Einige Gateways liefern leicht unterschiedliche Feldnamen (`ModelName` vs. `Model`, `SoftwareVersion` vs. `SWVersion`/`FirmwareVersion`). Der Code berücksichtigt gängige Varianten.
- Der Delta‑Sensor lernt Geräte erst, nachdem sie mindestens einmal gesehen wurden.

## Entwicklung

- Entities erben von `SensorEntity` (Basisklasse stellt `device_info` bereit).
- **Einzigartige IDs** basieren auf `config_entry_id` + Entity‑Name.
- Polling via `async_track_time_interval`.
- Die API‑Klasse `TechnicolorCGA` wird im Executor aufgerufen (`login`, `system`, `dhcp`, `aDev`).
