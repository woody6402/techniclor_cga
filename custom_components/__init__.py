import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST
from .technicolor_cga import TechnicolorCGA

_LOGGER = logging.getLogger(__name__)

DOMAIN = "technicolor_cga"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Technicolor CGA from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    router = entry.data[CONF_HOST]  # Use CONF_HOST to get the router

    _LOGGER.debug(f"Setting up Technicolor CGA with router {router}")

    try:
        technicolor_cga = TechnicolorCGA(username, password, router)
        await hass.async_add_executor_job(technicolor_cga.login)
    except Exception as e:
        _LOGGER.error(f"Failed to log in to Technicolor CGA: {e}")
        return False

    hass.data[DOMAIN][entry.entry_id] = technicolor_cga
    hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, "sensor"))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

