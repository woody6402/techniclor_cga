import logging
from datetime import timedelta

from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.components.sensor import SensorEntity

from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
DEFAULT_SCAN_SECONDS = 300


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Technicolor CGA sensors from a config entry."""

    username = config_entry.data[CONF_USERNAME]

    # ✅ Host/Password aus options (fallback data)
    host = config_entry.options.get(CONF_HOST, config_entry.data.get(CONF_HOST, "192.168.0.1"))
    password = config_entry.options.get(CONF_PASSWORD, config_entry.data.get(CONF_PASSWORD, ""))

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


    # ✅ Initialdaten für SystemSensor (weil dein ctor system_data erwartet)
    try:
        system_data = await hass.async_add_executor_job(technicolor.system)
    except Exception as err:
        _LOGGER.warning("Initial system fetch failed, continuing: %s", err)
        system_data = {}

    sensors = [
        TechnicolorCGASystemSensor(technicolor, hass, config_entry.entry_id, host, "System", system_data,
          unique_suffix="system", suggested_object_id="technicolor_system"),

        TechnicolorCGAHostSensor(technicolor, hass, config_entry.entry_id, host, "Hosts",
          unique_suffix="hosts", suggested_object_id="technicolor_hosts"),
          
        TechnicolorCGAHostDeltaSensor(technicolor, hass, config_entry.entry_id, host, "Missing/Inactive Hosts",
          unique_suffix="missing_inactive_hosts", suggested_object_id="technicolor_missing_inactive_hosts"),
    ]

    # DHCP dynamisch (Blacklist-Ansatz)
    notwanted: set[str] = set()  # erst mal leer lassen

    try:
        dhcp_data = await hass.async_add_executor_job(technicolor.dhcp)
        for key in sorted(dhcp_data.keys()):
            if key in notwanted:
                continue

            sensors.append(
                TechnicolorCGADHCPSensor(
                    technicolor,
                    hass,
                    config_entry.entry_id,
                    host,
                    f"CGA DHCP {key}",
                    key,
                    unique_suffix=f"dhcp_{key.lower()}",
                    suggested_object_id=f"technicolor_dhcp_{key.lower()}",
                )
            )
    except Exception as err:
        _LOGGER.warning("Failed to fetch DHCP data: %s", err)


    async_add_entities(sensors, update_before_add=True)

    # ✅ EIN Update-Loop für alle Sensoren (keine doppelten Timer)
    async def _update_all(_now):
        for s in sensors:
            await s.async_update()

    # ✅ Timer starten und "unsubscribe" speichern (damit unload/reload sauber ist)
    unsub = async_track_time_interval(hass, _update_all, scan_interval)

    # Wichtig: unsub im hass.data speichern, damit __init__.py es beim unload entfernen kann    
    entry_store = hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})
    if isinstance(entry_store, dict):
        entry_store["unsub"] = unsub



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
        """Fetch new state data for the sensor."""
        raise NotImplementedError("Subclasses must implement async_update")


class TechnicolorCGASystemSensor(TechnicolorCGABaseSensor):
    """System sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, system_data, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._apply_system_data(system_data)
        

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

    async def async_update(self):
        try:
            system_data = await self.hass.async_add_executor_job(self.technicolor_cga.system)
            self._apply_system_data(system_data)
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGADHCPSensor(TechnicolorCGABaseSensor):
    """DHCP sensor for Technicolor CGA."""


    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, attribute, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._attribute = attribute        

    async def async_update(self):
        try:
            dhcp_data = await self.hass.async_add_executor_job(self.technicolor_cga.dhcp)
            self._state = dhcp_data.get(self._attribute, "Unknown")
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGAHostSensor(TechnicolorCGABaseSensor):
    """Host sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)        

    async def async_update(self):
        try:
            host_data = await self.hass.async_add_executor_job(self.technicolor_cga.aDev)
            self._state = len(host_data.get("hostTbl", []))
            self._attributes = host_data
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGAHostDeltaSensor(TechnicolorCGABaseSensor):
    """Sensor to calculate missing or inactive devices and track known devices."""

    def __init__(self, technicolor_cga, hass, config_entry_id, host, name, **kwargs):
        super().__init__(technicolor_cga, hass, config_entry_id, host, name, **kwargs)
        self._missing_devices = []
        self._known_devices = {}  # dynamically learned known devices

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

    async def async_update(self):
        """Fetch new state data for the sensor."""
        _LOGGER.debug("Updating %s sensor", self._attr_name)
        try:
            host_data = await self.hass.async_add_executor_job(self.technicolor_cga.aDev)
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
        except Exception as e:
            _LOGGER.error("Error updating %s sensor: %s", self._attr_name, e)




