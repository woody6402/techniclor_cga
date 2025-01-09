import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST
from .const import DOMAIN
from .technicolor_cga import TechnicolorCGA
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=300)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Technicolor CGA sensor from a config entry."""
    _LOGGER.debug("Setting up Technicolor CGA sensor")
    
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    host = config_entry.data[CONF_HOST]

    try:
        technicolor_cga = TechnicolorCGA(username, password, host)
        await hass.async_add_executor_job(technicolor_cga.login)
    except Exception as e:
        _LOGGER.error(f"Failed to log in to Technicolor CGA: {e}")
        return

    sensors = []

    # Add system sensor
    try:
        system_data = await hass.async_add_executor_job(technicolor_cga.system)
        sensors.append(
            TechnicolorCGASystemSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                "Technicolor CGA System Status",
                system_data
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch system data from Technicolor CGA: {e}")

    # Add DHCP sensors
    try:
        dhcp_data = await hass.async_add_executor_job(technicolor_cga.dhcp)
        for key in dhcp_data.keys():
            sensors.append(
                TechnicolorCGADHCPSensor(
                    technicolor_cga,
                    hass,
                    config_entry.entry_id,
                    f"Technicolor CGA DHCP {key}",
                    key
                )
            )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch DHCP data from Technicolor CGA: {e}")

    # Add host sensor
    try:
        sensors.append(
            TechnicolorCGAHostSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                "Technicolor CGA Host List"
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch host data from Technicolor CGA: {e}")
        
        
    # Delta-Sensor für fehlende Geräte hinzufügen
    try:
        sensors.append(
            TechnicolorCGAHostDeltaSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                "Technicolor CGA Missing Devices"
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to create Delta sensor: {e}")

    async_add_entities(sensors, True)
    _LOGGER.debug("Technicolor CGA sensors added")

    # Rufe die async_update-Funktion im festgelegten Intervall auf
    for sensor in sensors:
        async_track_time_interval(hass, sensor.async_update, SCAN_INTERVAL)    

    async_add_entities(sensors, True)
    _LOGGER.debug("Technicolor CGA sensors added")
    async_track_time_interval(hass, lambda _: [sensor.async_update() for sensor in sensors], SCAN_INTERVAL)


class TechnicolorCGABaseSensor(SensorEntity):
    """Base class for Technicolor CGA sensors."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._attr_name = name
        self._state = None
        self._attributes = {}
        _LOGGER.debug(f"{name} Sensor initialized")

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._config_entry_id}_{self._attr_name.replace(' ', '_').lower()}"

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

    async def async_update(self):
        """Fetch new state data for the sensor."""
        raise NotImplementedError("Subclasses must implement async_update")


class TechnicolorCGASystemSensor(TechnicolorCGABaseSensor):
    """System sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name, system_data):
        super().__init__(technicolor_cga, hass, config_entry_id, name)
        self._state = system_data.get('CMStatus', 'Unknown')
        self._attributes = {key: value for key, value in system_data.items() if key != 'CMStatus'}

    async def async_update(self):
        try:
            system_data = await self.hass.async_add_executor_job(self.technicolor_cga.system)
            self._state = system_data.get('CMStatus', 'Unknown')
            self._attributes = {key: value for key, value in system_data.items() if key != 'CMStatus'}
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGADHCPSensor(TechnicolorCGABaseSensor):
    """DHCP sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name, attribute):
        super().__init__(technicolor_cga, hass, config_entry_id, name)
        self._attribute = attribute

    async def async_update(self):
        try:
            dhcp_data = await self.hass.async_add_executor_job(self.technicolor_cga.dhcp)
            self._state = dhcp_data.get(self._attribute, "Unknown")
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")


class TechnicolorCGAHostSensor(TechnicolorCGABaseSensor):
    """Host sensor for Technicolor CGA."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name):
        super().__init__(technicolor_cga, hass, config_entry_id, name)

    async def async_update(self):
        try:
            host_data = await self.hass.async_add_executor_job(self.technicolor_cga.aDev)
            self._state = len(host_data.get("hostTbl", []))
            self._attributes = host_data
        except Exception as e:
            _LOGGER.error(f"Error updating {self.name}: {e}")
            
class TechnicolorCGAHostDeltaSensor(SensorEntity):
    """Sensor to calculate missing or inactive devices and track known devices."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._attr_name = name
        self._state = None
        self._missing_devices = []
        self._known_devices = {}  # Dynamisch ermittelte bekannte Geräte
        _LOGGER.debug(f"{name} Sensor initialized")

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._config_entry_id}_{self._attr_name.replace(' ', '_').lower()}"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

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
            return tuple(map(int, ip.split('.')))
        except ValueError:
            # Handle invalid IPs gracefully by placing them at the end
            return (999, 999, 999, 999)

    async def async_update(self):
        """Fetch new state data for the sensor."""
        _LOGGER.debug(f"Updating {self._attr_name} sensor")
        try:
            # Host-Tabelle abrufen
            host_data = await self.hass.async_add_executor_job(self.technicolor_cga.aDev)
            current_devices = {
                host["physaddress"]: {
                    "ip": host.get("ipaddress", "Unknown"),
                    "hostname": host.get("hostname", "Unknown"),
                    "active": host.get("active", "false"),
                }
                for host in host_data.get("hostTbl", [])
            }

            # Bekannte Geräte aktualisieren
            for mac, details in current_devices.items():
                self._known_devices[mac] = details

            # Fehlende oder inaktive Geräte ermitteln
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

            _LOGGER.debug(f"{self._attr_name} sensor state updated: {self._missing_devices}")
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name} sensor: {e}")


