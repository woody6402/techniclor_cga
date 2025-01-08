import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST
from .const import DOMAIN
from .technicolor_cga import TechnicolorCGA
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=300)  # Ändere hier den Wert

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

    # Fetch system data and create a single sensor for it
    try:
        system_data = await hass.async_add_executor_job(technicolor_cga.system)
        sensors.append(
            TechnicolorCGASystemSensor(
                technicolor_cga,
                hass,
                config_entry.entry_id,
                "Technicolor CGA Status",
                system_data
            )
        )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch system data from Technicolor CGA: {e}")

    # Fetch DHCP data and create sensors for each item
    try:
        dhcp_data = await hass.async_add_executor_job(technicolor_cga.dhcp)
        for key in dhcp_data.keys():
            sensors.append(
                TechnicolorCGASensor(
                    technicolor_cga,
                    hass,
                    config_entry.entry_id,
                    f"Technicolor CGA DHCP {key}",
                    key
                )
            )
    except Exception as e:
        _LOGGER.error(f"Failed to fetch DHCP data from Technicolor CGA: {e}")

    async_add_entities(sensors, True)
    _LOGGER.debug("Technicolor CGA sensors added")
    
    # Rufe die async_update-Funktion im festgelegten Intervall auf
    async_track_time_interval(hass, sensor.async_update, SCAN_INTERVAL)

class TechnicolorCGASensor(SensorEntity):
    """Representation of a Technicolor CGA sensor."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name, attribute):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._attr_name = name
        self._attribute = attribute
        self._state = None
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

    async def async_update(self):
        """Fetch new state data for the sensor."""
        _LOGGER.debug(f"Updating {self._attr_name} sensor")
        try:
            dhcp_data = await self.hass.async_add_executor_job(self.technicolor_cga.dhcp)
            self._state = dhcp_data.get(self._attribute, "Unknown")
            
            _LOGGER.debug(f"{self._attr_name} sensor state updated: {self._state}")
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name} sensor: {e}")

class TechnicolorCGASystemSensor(SensorEntity):
    """Representation of the Technicolor CGA System sensor."""

    def __init__(self, technicolor_cga, hass, config_entry_id, name, system_data):
        """Initialize the sensor."""
        self.technicolor_cga = technicolor_cga
        self.hass = hass
        self._config_entry_id = config_entry_id
        self._attr_name = name
        self._system_data = system_data
        self._state = system_data.get('CMStatus', 'Unknown')
        self._attributes = {key: value for key, value in system_data.items() if key != 'CMStatus'}
        _LOGGER.debug(f"{name} System Sensor initialized")

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
        _LOGGER.debug(f"Updating {self._attr_name} system sensor")
        try:
            system_data = await self.hass.async_add_executor_job(self.technicolor_cga.system)
            self._state = system_data.get('CMStatus', 'Unknown')
            self._attributes = {key: value for key, value in system_data.items() if key != 'CMStatus'}
            _LOGGER.debug(f"{self._attr_name} system sensor state updated: {self._state}")
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name} system sensor: {e}")

