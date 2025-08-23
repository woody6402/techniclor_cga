
This project provides several **sensor entities** for a Technicolor CGA gateway in Home Assistant. It reads system and DHCP information, lists connected hosts, and offers a **delta sensor** to detect missing/inactive devices. Thanks to `device_info`, all entities are grouped under **one device** in Home Assistant's device and integrations registry.

## Features

- **System status** (e.g., `CMStatus`) including pass-through of additional system attributes
- **DHCP sensors** for all DHCP keys returned by the gateway
- **Host list** with the number of currently detected devices (`hostTbl`)
- **Missing devices / Delta sensor**: shows devices that disappeared or are inactive
- **Clean device grouping** via `device_info` (identifiers = `(DOMAIN, host)`, manufacturer, name, `configuration_url`); model/firmware are added when available
- **Automatic polling** every 5 minutes

## Directory structure (example)

```
custom_components/technicolor_cga/
├─ init.py
├─ config_flow.py
├─ manifest.json
├─ const.py
├─ technicolor_cga.py
└─ sensor.py
```

## Installation

1. Copy this folder to `config/custom_components/technicolor_cga/`.
2. **Restart** Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and pick *Technicolor CGA*.
4. Enter your credentials:
   - **Host** (e.g., `192.168.0.1`)
   - **Username**
   - **Password**

> The integration uses **Config Entries** (UI-based setup).

## Created entities

### System sensor
- **Name:** `Technicolor CGA System Status`
- **State:** value of `CMStatus` (or `"Unknown"`)
- **Attributes:** all other system fields (e.g., `ModelName`, `SoftwareVersion`, etc.).
- **Device info:** `model`/`sw_version` are set from system data when present.

### DHCP sensors
- **Name:** `Technicolor CGA DHCP <Key>` (for each key returned by `dhcp()`)
- **State:** corresponding value from DHCP data (or `"Unknown"`).

### Host sensor
- **Name:** `Technicolor CGA Host List`
- **State:** number of entries in `hostTbl`.
- **Attributes:** full host data structure (e.g., `hostTbl`, entries with `physaddress`, `ipaddress`, `hostname`, `active`).

### Delta / Missing devices sensor
- **Name:** `Technicolor CGA Missing Devices`
- **State:** number of detected *missing* or *inactive* devices.
- **Attributes:**
  - `missing_devices`: list of dicts `{mac, last_ip, hostname, status}`
  - `known_devices`: list of learned devices `{mac, last_ip, hostname}`
- **Notes:**
  - The `known_devices` list is **learned at runtime** (no persistence across restarts).
  - Sorting is numeric by IP; invalid IPs are placed at the end.

## Update interval

By default every **5 minutes** (`SCAN_INTERVAL = 300s`).

## Tips / Troubleshooting

- Verify `Host`, `Username`, `Password` and that the web interface is reachable.
- Some gateways return slightly different field names (`ModelName` vs. `Model`, `SoftwareVersion` vs. `SWVersion`/`FirmwareVersion`). The code handles common variants.
- The delta sensor only learns devices after they have been seen at least once.

## Development

- Entities inherit from `SensorEntity` (the base class provides `device_info`).
- **Unique IDs** are based on `config_entry_id` + entity name.
- Polling via `async_track_time_interval`.
- The API class `TechnicolorCGA` is called in the executor (`login`, `system`, `dhcp`, `aDev`).
