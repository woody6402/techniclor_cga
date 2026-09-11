import logging
from datetime import timedelta

from homeassistant.const import (
    CONF_HOST, CONF_SCAN_INTERVAL, UnitOfInformation,
)
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .polling import RouterPoller

_LOGGER = logging.getLogger(__name__)
DEFAULT_SCAN_SECONDS = 300


def _to_float(value):
    """Extract the leading number from values like '6.4 dBmV' or '38.7 dB'."""
    if value is None:
        return None
    try:
        return float(str(value).strip().split()[0])
    except (ValueError, IndexError):
        return None


def _to_int(value):
    """Parse an integer counter value, tolerating stray whitespace/units."""
    number = _to_float(value)
    return int(number) if number is not None else None


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Technicolor CGA sensors from a config entry."""

    # ✅ Host/Password aus options (fallback data)
    host = config_entry.options.get(CONF_HOST, config_entry.data.get(CONF_HOST, "192.168.0.1"))

    # ✅ ScanInterval aus options (fallback data / default)
    scan_seconds = config_entry.options.get(
        CONF_SCAN_INTERVAL,
        config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_SECONDS),
    )
    scan_interval = timedelta(seconds=int(scan_seconds))

    entry_store = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})
    technicolor = entry_store.get("api")
    

    if technicolor is None:
        _LOGGER.error("No API object found in hass.data for entry %s", config_entry.entry_id)
        return


    poller = RouterPoller(hass, technicolor)
    entry_store["poller"] = poller
    await poller.async_refresh()
    system_data = poller.data.get("system") or {}

    sensors = [
        TechnicolorCGASystemSensor(technicolor, hass, config_entry.entry_id, host, "System", system_data,
          unique_suffix="system", suggested_object_id="technicolor_system"),

        TechnicolorCGAHostSensor(technicolor, hass, config_entry.entry_id, host, "Hosts",
          unique_suffix="hosts", suggested_object_id="technicolor_hosts"),
          
        TechnicolorCGAHostDeltaSensor(technicolor, hass, config_entry.entry_id, host, "Missing/Inactive Hosts",
          unique_suffix="missing_inactive_hosts", suggested_object_id="technicolor_missing_inactive_hosts"),
    ]

    # DOCSIS RF / line-quality sensors (downstream/upstream power, SNR and
    # corrected/uncorrectable codeword counters).
    sensors.extend([
        TechnicolorCGADownstreamPowerSensor(technicolor, hass, config_entry.entry_id, host,
          "Downstream Power", unique_suffix="downstream_power",
          suggested_object_id="technicolor_downstream_power"),
        TechnicolorCGADownstreamSnrSensor(technicolor, hass, config_entry.entry_id, host,
          "Downstream SNR", unique_suffix="downstream_snr",
          suggested_object_id="technicolor_downstream_snr"),
        TechnicolorCGAUpstreamPowerSensor(technicolor, hass, config_entry.entry_id, host,
          "Upstream Power", unique_suffix="upstream_power",
          suggested_object_id="technicolor_upstream_power"),
        TechnicolorCGACorrectedsSensor(technicolor, hass, config_entry.entry_id, host,
          "Downstream Correcteds", unique_suffix="downstream_correcteds",
          suggested_object_id="technicolor_downstream_correcteds"),
        TechnicolorCGAUncorrectablesSensor(technicolor, hass, config_entry.entry_id, host,
          "Downstream Uncorrectables", unique_suffix="downstream_uncorrectables",
          suggested_object_id="technicolor_downstream_uncorrectables"),
        TechnicolorCGAChannelsSensor(technicolor, hass, config_entry.entry_id, host,
          "DOCSIS Channels", unique_suffix="docsis_channels",
          suggested_object_id="technicolor_docsis_channels"),
    ])

    # WAN / LAN interface statistics (dig_interface).
    sensors.extend([
        TechnicolorCGAWanStatusSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Status", unique_suffix="wan_status",
          suggested_object_id="technicolor_wan_status"),
        TechnicolorCGAWanCounterSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Packets Received", "PacketsReceived", unique_suffix="wan_packets_received",
          suggested_object_id="technicolor_wan_packets_received"),
        TechnicolorCGAWanCounterSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Packets Sent", "PacketsSent", unique_suffix="wan_packets_sent",
          suggested_object_id="technicolor_wan_packets_sent"),
        TechnicolorCGAWanCounterSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Bytes Received", "BytesReceived", unique_suffix="wan_bytes_received",
          suggested_object_id="technicolor_wan_bytes_received", data_size=True),
        TechnicolorCGAWanCounterSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Bytes Sent", "BytesSent", unique_suffix="wan_bytes_sent",
          suggested_object_id="technicolor_wan_bytes_sent", data_size=True),
        TechnicolorCGAWanCounterSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Errors Received", "ErrorsReceived", unique_suffix="wan_errors_received",
          suggested_object_id="technicolor_wan_errors_received", diagnostic=True),
        TechnicolorCGAWanCounterSensor(technicolor, hass, config_entry.entry_id, host,
          "WAN Errors Sent", "ErrorsSent", unique_suffix="wan_errors_sent",
          suggested_object_id="technicolor_wan_errors_sent", diagnostic=True),
        TechnicolorCGALanPortsSensor(technicolor, hass, config_entry.entry_id, host,
          "LAN Ports", unique_suffix="lan_ports",
          suggested_object_id="technicolor_lan_ports"),
    ])

    for sensor in sensors:
        sensor._poller = poller

    dhcp_keys = set()

    async def _add_dhcp_sensors():
        # Discover keys again after recovery if DHCP was unavailable at setup.
        new_sensors = []
        for key in sorted((poller.data.get("dhcp") or {}).keys()):
            if key in dhcp_keys:
                continue
            sensor = TechnicolorCGADHCPSensor(
                technicolor, hass, config_entry.entry_id, host,
                f"CGA DHCP {key}", key,
                unique_suffix=f"dhcp_{key.lower()}",
                suggested_object_id=f"technicolor_dhcp_{key.lower()}",
            )
            sensor._poller = poller
            await sensor.async_update()
            dhcp_keys.add(key)
            new_sensors.append(sensor)
        sensors.extend(new_sensors)
        return new_sensors

    await _add_dhcp_sensors()
    for sensor in sensors:
        await sensor.async_update()
    async_add_entities(sensors, update_before_add=False)

    async def _update_all(_now):
        if not await poller.async_refresh():
            return
        # Publish synchronously between awaits that do no I/O, so a new round
        # cannot replace the snapshot while it is being applied.
        existing = list(sensors)
        new_sensors = await _add_dhcp_sensors()
        for sensor in existing:
            await sensor.async_update()
            sensor.async_write_ha_state()
        if new_sensors:
            async_add_entities(new_sensors, update_before_add=False)

    def _start_polling():
        entry_store["unsub"] = async_track_time_interval(hass, _update_all, scan_interval)

    entry_store["start_polling"] = _start_polling
    _start_polling()



class TechnicolorCGABaseSensor(SensorEntity):
    """Base class for Technicolor CGA sensors with device_info."""

    def __init__(
        self,
        technicolor_cga,
        hass,
        config_entry_id,
        host,
        name,
        *,
        unique_suffix: str | None = None,
        suggested_object_id: str | None = None,
    ):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._host = host
        self._attr_has_entity_name = True
        self._attr_name = name  # z.B. "System", "Hosts", "DHCP IPAddressGW"
        if unique_suffix:
            self._attr_unique_id = f"{config_entry_id}_{unique_suffix}"
        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id
        self._state = None
        self._attributes = {}
        self._model = None
        self._sw_version = None
        self._attr_should_poll = False
        _LOGGER.debug("%s Sensor initialized (host: %s)", name, host)

        
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self._attributes

    @property
    def device_info(self):
        """Return device registry information for the Technicolor gateway.

        Keeping it simple: identifiers by (DOMAIN, host), a friendly name,
        manufacturer, and a configuration URL.
        The system sensor may enrich model and sw_version after its first fetch.
        """
        info = {
            "identifiers": {(DOMAIN, self._config_entry_id)},
            "name": "Technicolor CGA Gateway",
            "manufacturer": "Technicolor",
            "configuration_url": f"http://{self._host}/",
        }
        if self._model:
            info["model"] = self._model
        if self._sw_version:
            info["sw_version"] = self._sw_version
        return info

    async def async_update(self):
        """Apply the shared snapshot; entity updates never query the router."""
        data = self._poller.data.get(self._data_group)
        self._attr_available = False
        if data is None:
            return
        try:
            self._apply_data(data)
            self._attr_available = True
        except Exception as err:
            _LOGGER.error("Invalid data for %s: %s", self.name, err)

    def _apply_data(self, data):
        raise NotImplementedError


class TechnicolorCGASystemSensor(TechnicolorCGABaseSensor):
    """System sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, system_data, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._apply_system_data(system_data)
        

    @property
    def extra_state_attributes(self):
        # Diagnostics remain visible even when the system snapshot is absent.
        poller = getattr(self, "_poller", None)
        diagnostics = poller.diagnostics if poller is not None else {}
        return {**self._attributes, **diagnostics}

    def _apply_system_data(self, system_data: dict):
        self._state = system_data.get("CMStatus", "Unknown")
        # Pick common keys for model / firmware if available
        self._model = system_data.get("ModelName") or system_data.get("Model")
        self._sw_version = (
            system_data.get("SoftwareVersion")
            or system_data.get("SWVersion")
            or system_data.get("FirmwareVersion")
        )
        self._attributes = {k: v for k, v in system_data.items() if k != "CMStatus"}

    _data_group = 'system'

    def _apply_data(self, system_data):
        self._apply_system_data(system_data)


class TechnicolorCGADHCPSensor(TechnicolorCGABaseSensor):
    """DHCP sensor for Technicolor CGA."""


    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, attribute, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._attribute = attribute        
        self._attr_entity_category = EntityCategory.DIAGNOSTIC        

    _data_group = 'dhcp'

    def _apply_data(self, dhcp_data):
        self._state = dhcp_data.get(self._attribute, "Unknown")


class TechnicolorCGAHostSensor(TechnicolorCGABaseSensor):
    """Host sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)        

    _data_group = 'hosts'

    def _apply_data(self, host_data):
        self._state = len(host_data.get("hostTbl", []))
        self._attributes = host_data


class TechnicolorCGAHostDeltaSensor(TechnicolorCGABaseSensor):
    """Sensor to calculate missing or inactive devices and track known devices."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._missing_devices = []
        self._known_devices = {}  # dynamically learned known devices
        self._attr_entity_category = EntityCategory.DIAGNOSTIC          

    @property
    def state(self):
        """Return the state of the sensor."""
        return len(self._missing_devices)

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return {
            "missing_devices": sorted(
                self._missing_devices, key=lambda x: self._ip_sort_key(x["last_ip"])
            ),
            "known_devices": sorted(
                [
                    {"mac": mac, "last_ip": details["ip"], "hostname": details["hostname"]}
                    for mac, details in self._known_devices.items()
                ],
                key=lambda x: self._ip_sort_key(x["last_ip"]),
            ),
        }

    def _ip_sort_key(self, ip):
        """Convert an IP address into a tuple of integers for correct sorting."""
        try:
            return tuple(map(int, ip.split(".")))
        except ValueError:
            return (999, 999, 999, 999)

    _data_group = 'hosts'

    def _apply_data(self, host_data):
        current_devices = {
            host["physaddress"]: {
                "ip": host.get("ipaddress", "Unknown"),
                "hostname": host.get("hostname", "Unknown"),
                "active": host.get("active", "false"),
            }
            for host in host_data.get("hostTbl", [])
        }
        for mac, details in current_devices.items():
            self._known_devices[mac] = details
        self._missing_devices = []
        for mac, details in self._known_devices.items():
            if mac not in current_devices:
                self._missing_devices.append(
                    {
                        "mac": mac,
                        "last_ip": details["ip"],
                        "hostname": details["hostname"],
                        "status": "missing",
                    }
                )
            elif current_devices[mac]["active"] == "false":
                self._missing_devices.append(
                    {
                        "mac": mac,
                        "last_ip": current_devices[mac]["ip"],
                        "hostname": current_devices[mac]["hostname"],
                        "status": "inactive",
                    }
                )


class TechnicolorCGALevelsSensor(TechnicolorCGABaseSensor):
    """Base for sensors derived from the modem's DOCSIS levels() tables.

    ``levels()`` returns the SC-QAM downstream/upstream tables (``DSTbl`` /
    ``USTbl``), the OFDM/OFDMA tables (``exDSTbl`` / ``exUSTbl``) and the
    per-downstream-channel error counters (``ErrTbl``). All sensors consume
    the same snapshot fetched by the central poller.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    @staticmethod
    def _is_locked(row):
        return str(row.get("LockStatus", "")).strip().lower() == "locked"

    @staticmethod
    def _downstream_rows(levels):
        return (levels.get("DSTbl") or []) + (levels.get("exDSTbl") or [])

    @staticmethod
    def _upstream_rows(levels):
        return (levels.get("USTbl") or []) + (levels.get("exUSTbl") or [])

    _data_group = 'levels'

    def _apply_data(self, levels):
        self._apply_levels(levels)

    def _apply_levels(self, levels):
        raise NotImplementedError


class TechnicolorCGADownstreamPowerSensor(TechnicolorCGALevelsSensor):
    """Average downstream receive power across all locked channels (dBmV)."""

    _attr_native_unit_of_measurement = "dBmV"
    _attr_icon = "mdi:signal"

    def _apply_levels(self, levels):
        rows = self._downstream_rows(levels)
        powers = [
            value
            for row in rows
            if self._is_locked(row)
            if (value := _to_float(row.get("PowerLevel"))) is not None
        ]
        self._state = round(sum(powers) / len(powers), 1) if powers else None
        self._attributes = {
            "channel_count": len(powers),
            "min_dbmv": round(min(powers), 1) if powers else None,
            "max_dbmv": round(max(powers), 1) if powers else None,
            "channels": [
                {
                    "channel_id": r.get("ChannelID"),
                    "frequency": r.get("Frequency") or r.get("CentralFrequency"),
                    "power_dbmv": _to_float(r.get("PowerLevel")),
                    "snr_db": _to_float(r.get("SNRLevel")),
                    "type": r.get("ChannelType"),
                    "lock": r.get("LockStatus"),
                }
                for r in rows
            ],
        }


class TechnicolorCGADownstreamSnrSensor(TechnicolorCGALevelsSensor):
    """Worst-case downstream signal-to-noise ratio across channels (dB)."""

    _attr_native_unit_of_measurement = "dB"
    _attr_icon = "mdi:waveform"

    def _apply_levels(self, levels):
        rows = self._downstream_rows(levels)
        snrs = [
            value
            for row in rows
            if self._is_locked(row)
            if (value := _to_float(row.get("SNRLevel"))) is not None
        ]
        # The worst channel is the one that dictates line quality, so report min.
        self._state = round(min(snrs), 1) if snrs else None
        self._attributes = {
            "channel_count": len(snrs),
            "min_db": round(min(snrs), 1) if snrs else None,
            "max_db": round(max(snrs), 1) if snrs else None,
            "avg_db": round(sum(snrs) / len(snrs), 1) if snrs else None,
        }


class TechnicolorCGAUpstreamPowerSensor(TechnicolorCGALevelsSensor):
    """Average upstream transmit power across all locked channels (dBmV)."""

    _attr_native_unit_of_measurement = "dBmV"
    _attr_icon = "mdi:signal"

    def _apply_levels(self, levels):
        rows = self._upstream_rows(levels)
        powers = [
            value
            for row in rows
            if self._is_locked(row)
            if (value := _to_float(row.get("PowerLevel"))) is not None
        ]
        self._state = round(sum(powers) / len(powers), 1) if powers else None
        self._attributes = {
            "channel_count": len(powers),
            "min_dbmv": round(min(powers), 1) if powers else None,
            "max_dbmv": round(max(powers), 1) if powers else None,
            "channels": [
                {
                    "channel_id": r.get("ChannelID"),
                    "frequency": r.get("Frequency") or r.get("CentralFrequency"),
                    "power_dbmv": _to_float(r.get("PowerLevel")),
                    "type": r.get("ChannelType"),
                    "lock": r.get("LockStatus"),
                }
                for r in rows
            ],
        }


class TechnicolorCGACorrectedsSensor(TechnicolorCGALevelsSensor):
    """Total corrected codewords across downstream channels (ErrTbl)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:alert-circle-check-outline"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _apply_levels(self, levels):
        rows = levels.get("ErrTbl") or []
        values = [c for c in (_to_int(r.get("Correcteds")) for r in rows) if c is not None]
        self._state = sum(values) if values else None
        self._attributes = {
            "channel_count": len(rows),
            "per_channel": [_to_int(r.get("Correcteds")) for r in rows],
        }


class TechnicolorCGAUncorrectablesSensor(TechnicolorCGALevelsSensor):
    """Total uncorrectable codewords across downstream channels (ErrTbl).

    This is the key line-health metric: it should stay flat. A rising value
    means the downstream signal is degraded beyond FEC's ability to recover.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _apply_levels(self, levels):
        rows = levels.get("ErrTbl") or []
        values = [u for u in (_to_int(r.get("Uncorrectables")) for r in rows) if u is not None]
        self._state = sum(values) if values else None
        self._attributes = {
            "channel_count": len(rows),
            "per_channel": [_to_int(r.get("Uncorrectables")) for r in rows],
        }


class TechnicolorCGAChannelsSensor(TechnicolorCGALevelsSensor):
    """Number of locked DOCSIS channels; carries the raw tables as attributes."""

    _attr_icon = "mdi:television-guide"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._attr_state_class = None
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @staticmethod
    def _locked(rows):
        return sum(1 for r in rows if str(r.get("LockStatus", "")).lower() == "locked")

    def _apply_levels(self, levels):
        ds = self._downstream_rows(levels)
        us = self._upstream_rows(levels)
        self._state = self._locked(ds) + self._locked(us)
        self._attributes = {
            "downstream_locked": self._locked(ds),
            "downstream_total": len(ds),
            "upstream_locked": self._locked(us),
            "upstream_total": len(us),
            "DSTbl": levels.get("DSTbl") or [],
            "USTbl": levels.get("USTbl") or [],
            "exDSTbl": levels.get("exDSTbl") or [],
            "exUSTbl": levels.get("exUSTbl") or [],
            "ErrTbl": levels.get("ErrTbl") or [],
        }


class TechnicolorCGAInterfacesSensor(TechnicolorCGABaseSensor):
    """Base for sensors derived from the dig_interface() statistics.

    ``interfaces()`` returns per-interface counters for the WAN uplink
    (``WANStats``), the physical LAN ports (``LANEtherTable``) and the WiFi
    radios. All sensors consume the same snapshot fetched by the central
    poller.
    """

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)

    _data_group = 'interfaces'

    def _apply_data(self, data):
        self._apply_interfaces(data)

    def _apply_interfaces(self, data):
        raise NotImplementedError


class TechnicolorCGAWanStatusSensor(TechnicolorCGAInterfacesSensor):
    """WAN uplink link state (Up/Down) with link details as attributes."""

    _attr_icon = "mdi:wan"

    def _apply_interfaces(self, data):
        eth = data.get("WANEthernet") or {}
        l3 = data.get("WANL3Interface") or {}
        stats = data.get("WANStats") or {}
        self._state = eth.get("Status") or l3.get("Status") or "Unknown"
        self._attributes = {
            "l3_status": l3.get("Status"),
            "max_bitrate_mbps": _to_int(eth.get("MaxBitRate")),
            "duplex": eth.get("DuplexMode"),
            "last_change_s": _to_int(l3.get("LastChange")),
            "packets_received": _to_int(stats.get("PacketsReceived")),
            "packets_sent": _to_int(stats.get("PacketsSent")),
            "bytes_received": _to_int(stats.get("BytesReceived")),
            "bytes_sent": _to_int(stats.get("BytesSent")),
            "errors_received": _to_int(stats.get("ErrorsReceived")),
            "errors_sent": _to_int(stats.get("ErrorsSent")),
        }


class TechnicolorCGAWanCounterSensor(TechnicolorCGAInterfacesSensor):
    """A single WANStats counter (packets / bytes / errors).

    All counters are cumulative, so they use ``total_increasing``. Note that
    the byte counters are 32-bit on this firmware and clamp at 2147483647
    (2**31-1) rather than wrapping, so ``Bytes*`` becomes unreliable once the
    interface has passed ~2 GB since the last reset.
    """

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, field,
                 *, data_size=False, diagnostic=False, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._field = field
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        if data_size:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _apply_interfaces(self, data):
        stats = data.get("WANStats") or {}
        self._state = _to_int(stats.get(self._field))


class TechnicolorCGALanPortsSensor(TechnicolorCGAInterfacesSensor):
    """Number of LAN ports that are up; full per-port table as attributes."""

    _attr_icon = "mdi:ethernet"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _apply_interfaces(self, data):
        ports = data.get("LANEtherTable") or []
        self._state = sum(1 for p in ports if str(p.get("Status", "")).lower() == "up")
        self._attributes = {
            "port_count": len(ports),
            "ports": ports,
            "LANStats": data.get("LANStats") or {},
        }
