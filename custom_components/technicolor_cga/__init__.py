import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST

from .const import DOMAIN
from .technicolor_cga import TechnicolorCGA

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Technicolor CGA from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    username = entry.data[CONF_USERNAME]

    # ✅ host/password aus Options (fallback auf data)
    password = entry.options.get(CONF_PASSWORD, entry.data.get(CONF_PASSWORD))
    router = entry.options.get(CONF_HOST, entry.data.get(CONF_HOST, "192.168.0.1"))

    _LOGGER.debug("Setting up Technicolor CGA with router %s", router)

    try:
        api = TechnicolorCGA(username, password, router)
        await hass.async_add_executor_job(api.login)
    except Exception as err:
        _LOGGER.error("Failed to log in to Technicolor CGA: %s", err)
        return False

    # ✅ Platz für api + später unsub (Interval-Listener)
    hass.data[DOMAIN][entry.entry_id] = {"api": api, "unsub": None}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # ✅ erst Timer abmelden (falls gesetzt)
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data and entry_data.get("unsub"):
        entry_data["unsub"]()
        entry_data["unsub"] = None

    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok

