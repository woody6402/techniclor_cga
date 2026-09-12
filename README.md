# Technicolor CGA for Home Assistant

Custom integration for Technicolor CGA cable gateways. System, network, DOCSIS
and Wi-Fi sensors are grouped under one device. Configuration is available in
the Home Assistant UI; no YAML is required.

**0.9.6b1 is a prerelease candidate.** The new combined polling and session
handling still needs extended testing on real routers. Firmware-specific API
behavior can differ between models and providers.

## Features

| Area | Sensors and behavior |
|---|---|
| System | Router `CMStatus` (for example `OPERATIONAL`), hardware/firmware attributes and polling diagnostics |
| DOCSIS | Downstream/upstream power, minimum downstream SNR, locked channel count, corrected/uncorrectable codewords |
| WAN | Link status and received/sent packet, byte and error counters |
| LAN | Number of active Ethernet ports, with port details and LAN statistics |
| Wi-Fi | Separate 2.4 GHz and 5 GHz radio states with channel, bandwidth, SSID and security settings |
| DHCP | A sensor for each returned DHCP field |
| Hosts | Current host count and a list of missing/inactive previously observed devices |
| Polling | Shared serial fetches, HTTP timeouts, failure diagnostics and recovery |
| Sessions | Optional takeover of an occupied router session; disabled by default |
| Branding | Bundled modem icon and logo; local branding requires HA 2026.3 or later |

## Installation and upgrade

The HACS metadata declares Home Assistant **2025.10.0** as the minimum version.
The full combined prerelease has not been validated against every supported HA
version. Local brand images are a separate HA 2026.3+ capability.

### HACS

Add `https://github.com/woody6402/techniclor_cga` as a custom repository of type
**Integration**, then download Technicolor CGA. To test this prerelease, select
`0.9.6b1` once it has been published and prerelease versions are visible in HACS.

### Manual

1. Back up the existing integration folder before upgrading.
2. Copy the **entire** `custom_components/technicolor_cga/` directory into
   `/config/custom_components/technicolor_cga/`. In particular, the central
   poller needs the new `polling.py`; avoid mixing files from different versions.
3. Restart **Home Assistant Core** to load changed Python code.
4. For a new installation, open **Settings → Devices & services → Add integration**
   and select **Technicolor CGA**. Existing configuration entries can be retained.

The integration folder includes the API, sensor and polling modules, configuration
flow, manifest, translations, and `brand/icon.png` / `brand/logo.png`.
No additional release attachment is needed for a standard HACS installation.

## Configuration and browser sessions

Enter the router host/IP, username and password. The polling interval defaults
to **300 seconds**, with a configurable range of 10–86400 seconds. Options allow
changing the host, password, interval and session policy. Saving options reloads
the integration; changing Python files requires a Core restart.

**Take over an existing router session** (`force_logout`):

- **Off (default, including existing installations):** HA does not force another
  session out. If login cannot proceed, HA waits and retries later.
- **On:** an explicit `MSG_LOGIN_150` response permits one extra salt request with
  `logout=true`. This can log out a browser. Other errors do not trigger takeover.

Initial login failures are retried by Home Assistant via `ConfigEntryNotReady`.
After setup, failures are retried on the next polling round. A browser tab being
closed does not necessarily release its session; logout or session expiry may
be required. The integration does not automatically log out after each round or
when unloaded. This option does not guarantee simultaneous browser/HA access or
resolve every firmware web-server problem.

## How polling works

```text
System → DHCP → Hosts → DOCSIS → WAN/LAN → Wi-Fi → update sensors
```

Each round fetches each group once, serially, including the initial setup round.
All consumers share those results: for example, the two host sensors use one
host response. Authentication can add HTTP requests. There is no time-based
API cache; individual entity updates only reapply the shared snapshot.

- Data is published at the end of the round. Startup waits for those fetches.
- A failed or empty/invalid group response ends the round. That group and all
  groups not yet fetched become unavailable; successfully fetched groups remain
  usable. The next timer round tries again.
- If one Wi-Fi radio returns an invalid envelope, the other radio may remain
  available; diagnostics report the partial failure.
- Overlapping rounds are skipped. Unload stops the timer and waits for the
  current group call, including any login retry, without starting further groups.
- HTTP requests use **5-second connect / 15-second read inactivity timeouts**.
  These are not a total deadline for a group call or an entire polling round.
  An already running HTTP request cannot be forcibly cancelled by the poller.
- Missing individual fields inside otherwise valid responses are not all
  validated separately. Some fields may show `Unknown` or no numeric value.

### Polling diagnostics

The existing **System** sensor exposes these attributes even when unavailable:

| Attribute | Meaning |
|---|---|
| `poll_status` | `not_started`, `updating`, `ok`, `waiting_for_session`, `login_failed`, `timeout`, `connection_error`, `invalid_response` or `error` |
| `last_attempt` | Start of the latest round, in UTC |
| `last_success` | Completion of the last fully successful fetch round, in UTC |
| `failed_group` | Group that failed, or no value after a successful round |
| `poll_error` | Sanitized description without credentials or raw response bodies |

`waiting_for_session` requires an explicit `MSG_LOGIN_150` response. A missing
challenge alone is reported as `login_failed`. Before initial login succeeds,
entities are not yet created: consult the integration setup status and logs.
Diagnostics and learned host history are kept in memory, not persisted.

## Sensor details and limitations

### DOCSIS

Downstream Power and Upstream Power show the average of parseable power values
from **locked** channels (dBmV). Downstream SNR shows the **minimum** SNR among
locked channels (dB). SC-QAM and OFDM/OFDMA tables are included where provided.
Power attributes include minimum, maximum and per-channel details; raw channel
rows remain visible even if excluded from aggregation. With no eligible values,
there is no numeric measurement.

DOCSIS Channels counts locked downstream **plus** upstream channels and exposes
`DSTbl`, `USTbl`, `exDSTbl`, `exUSTbl` and `ErrTbl`. Correcteds and Uncorrectables
sum the returned `ErrTbl` counters and use `total_increasing` for HA statistics.
Router resets or channel changes can change counter totals; the returned tables
determine which channels are included.

### WAN and LAN

WAN Status prefers `WANEthernet.Status`, falling back to `WANL3Interface.Status`.
It reports a link state, **not an Internet connectivity test**. Attributes include
L3 status, bitrate, duplex and counters. LAN Ports counts `Up` entries in
`LANEtherTable`, with the table and `LANStats` exposed as attributes.

WAN counters are cumulative and use `total_increasing`; byte counters use bytes
and the data-size device class. Some firmware has been reported to clamp byte
counters at **2,147,483,647** instead of wrapping. If a counter plateaus there,
it cannot be used for reliable long-term traffic totals. Verify behavior on your
own firmware; packet/error counters are separate values.

### Wi-Fi

The endpoint `/api/v1/wifi/1,2/RadioEnable,...,RegulatoryDomain` returns separate
radio envelopes. Radio 1 maps to **WiFi 2.4 GHz**, radio 2 to **WiFi 5 GHz**, based
on the supplied CGA4233EU response. `Enabled` / `Disabled` reflects `RadioEnable`,
not reachability. Attributes preserve the reported channel, bandwidth, standards,
auto-channel setting, SSID/BSSID, SSID enable/visibility, security mode, encryption
and regulatory domain. This endpoint provides no client or traffic counters, and
no Wi-Fi passwords are requested.

### DHCP and hosts

DHCP sensors are discovered from returned keys, including keys first seen after
recovery from an initial failure. Hosts counts `hostTbl` entries; its attributes
contain the returned host data. Missing/Inactive Hosts learns devices in memory
and reports those absent or marked inactive, with `missing_devices` and
`known_devices` attributes. History resets when the integration is reloaded.
An inactive entry is not by itself proof of a device or network fault.

Entity unique IDs use the configuration entry ID and stable sensor suffixes.
Device grouping uses the integration domain and configuration entry ID.

## Testing and troubleshooting

PR #3's author reported live DOCSIS/WAN/LAN checks on a **CGA437**. The maintainer
observed all 14 PR sensors on **CGA4233EU**, firmware
**CGA4233EU-19.1.B39-022-E20-RMQS**, and supplied its Wi-Fi API response. These
observations do not constitute a complete long-term validation of this prerelease.

Local regression tests use simulated router responses and a minimal HA stand-in:

```sh
python3 -B -m unittest discover -s tests -v
```

They cover polling counts, overlap prevention, shutdown/cancellation, recovery,
late DHCP discovery, Wi-Fi envelopes, session policy and diagnostic attributes.
They do not replace a real HAOS test of setup/options, reload, session expiry and
browser access. Router response fixtures are synthetic and contain no real credentials.

When diagnosing a failure, check System polling attributes and the HA logs.
If the browser is also affected, disable the integration and verify router HTTP
access separately; a successful ping does not prove the web server is responding.
Please report model, firmware, polling interval, session option and sanitized errors.

Feature-branch history and review bases are documented in [FEATURE_BRANCHES.md](FEATURE_BRANCHES.md).
