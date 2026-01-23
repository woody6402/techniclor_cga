import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_HOST, CONF_SCAN_INTERVAL
from .const import DOMAIN

DEFAULT_SCAN_SECONDS = 300


class TechnicolorCGAConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Technicolor CGA."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_USERNAME): str,
                        vol.Required(CONF_PASSWORD): str,
                        vol.Required(CONF_HOST, default="192.168.0.1"): str,
                        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_SECONDS): vol.All(
                            vol.Coerce(int), vol.Range(min=10, max=86400)
                        ),
                    }
                ),
            )

        # Verbindung in data, ScanInterval in options speichern
        data = {
            CONF_USERNAME: user_input[CONF_USERNAME],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
            CONF_HOST: user_input[CONF_HOST],
        }
        options = {
            CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
        }

        # In aktuellen HA-Versionen ist "options=" bei async_create_entry verfügbar.
        return self.async_create_entry(title="Technicolor CGA", data=data, options=options)

    @staticmethod
    def async_get_options_flow(config_entry):
        return TechnicolorCGAOptionsFlow(config_entry)


class TechnicolorCGAOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Technicolor CGA."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # NICHT self.config_entry setzen (read-only property) -> eigener Name
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is None:
            current_host = self._config_entry.options.get(
                CONF_HOST, self._config_entry.data.get(CONF_HOST, "192.168.0.1")
            )
            current_password = self._config_entry.options.get(
                CONF_PASSWORD, self._config_entry.data.get(CONF_PASSWORD, "")
            )
            current_scan = self._config_entry.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_SECONDS
            )

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST, default=current_host): str,
                        vol.Required(CONF_PASSWORD, default=current_password): str,
                        vol.Required(
                            CONF_SCAN_INTERVAL, default=current_scan
                        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=86400)),
                    }
                ),
            )

        # data updaten (optional, aber ok)
        new_data = dict(self._config_entry.data)
        new_data[CONF_HOST] = user_input[CONF_HOST]
        new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]

        # options updaten (Scan + Host + Password)
        new_options = dict(self._config_entry.options)
        new_options[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
        new_options[CONF_HOST] = user_input[CONF_HOST]
        new_options[CONF_PASSWORD] = user_input[CONF_PASSWORD]

        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data=new_data,
            options=new_options,
        )

        # sorgt dafür, dass neue Werte (inkl. ScanInterval) greifen
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)

        # OptionsFlow speichert "data" als options
        return self.async_create_entry(title="", data=new_options)



