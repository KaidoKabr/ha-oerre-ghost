"""Config flow for Oerre Ghost."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_APP_PORT,
    CONF_LISTEN_PORT,
    CONF_UPSTREAM_HOST,
    CONF_UPSTREAM_PORT,
    DEFAULT_APP_PORT,
    DEFAULT_LISTEN_PORT,
    DEFAULT_UPSTREAM_HOST,
    DEFAULT_UPSTREAM_PORT,
    DOMAIN,
)

PORT = vol.All(vol.Coerce(int), vol.Range(min=0, max=65535))


class OerreGhostConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Oerre Ghost", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_LISTEN_PORT, default=DEFAULT_LISTEN_PORT): PORT,
                vol.Optional(CONF_UPSTREAM_HOST, default=DEFAULT_UPSTREAM_HOST): str,
                vol.Required(CONF_UPSTREAM_PORT, default=DEFAULT_UPSTREAM_PORT): PORT,
                vol.Required(CONF_APP_PORT, default=DEFAULT_APP_PORT): PORT,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
