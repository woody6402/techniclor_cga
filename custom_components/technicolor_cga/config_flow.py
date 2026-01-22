import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST
from .const import DOMAIN

class TechnicolorCGAConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Technicolor CGA."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_HOST, default="192.168.0.1"): str,
            }))

        return self.async_create_entry(title="Technicolor CGA", data=user_input)

