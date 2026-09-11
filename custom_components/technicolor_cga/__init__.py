import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST
from homeassistant.exceptions import ConfigEntryNotReady

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
        # The modem allows a single session and can briefly refuse a login
        # (e.g. right after a reboot, or while another session is being torn
        # down), which surfaces here as a missing 'salt'/'data' key. Treat it
        # as temporary so Home Assistant retries with backoff instead of
        # leaving the integration dead until a manual reload.
        raise ConfigEntryNotReady(
            f"Could not log in to Technicolor CGA at {router}: {err}"
        ) from err

    # ✅ Platz für api + später unsub (Interval-Listener)
    hass.data[DOMAIN][entry.entry_id] = {"api": api, "unsub": None}

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        if entry_data.get("unsub"):
            entry_data["unsub"]()
        if entry_data.get("poller"):
            await entry_data["poller"].async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # ✅ erst Timer abmelden (falls gesetzt)
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data and entry_data.get("unsub"):
        entry_data["unsub"]()
        entry_data["unsub"] = None

    if entry_data and entry_data.get("poller"):
        await entry_data["poller"].async_stop()

    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    elif entry_data and entry_data.get("start_polling"):
        entry_data["poller"].resume()
        entry_data["start_polling"]()

    return unload_ok

