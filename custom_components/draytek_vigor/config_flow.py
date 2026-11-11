"""Config flow: host, HTTPS and web login; reauth and reconfigure."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SSL, CONF_USERNAME, CONF_VERIFY_SSL

from . import create_client, normalize_host
from .api import CannotConnect, InvalidAuth
from .const import DEFAULT_HOST, DEFAULT_SSL, DEFAULT_USERNAME, DEFAULT_VERIFY_SSL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _connection_schema(defaults: Mapping[str, Any]) -> dict[vol.Marker, Any]:
    return {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
        vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, DEFAULT_SSL)): bool,
        vol.Required(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
    }


class VigorConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, data: dict[str, Any]) -> dict[str, str]:
        client = create_client(self.hass, data, auto_cleanup=False)
        try:
            await client.async_get_dsl_status()
        except InvalidAuth:
            return {"base": "invalid_auth"}
        except CannotConnect as err:
            _LOGGER.debug("Cannot connect: %s", err)
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while validating the modem")
            return {"base": "unknown"}
        finally:
            await client.async_close()
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_HOST: normalize_host(user_input[CONF_HOST])}
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            if not (errors := await self._validate(user_input)):
                return self.async_create_entry(title=f"Vigor {user_input[CONF_HOST]}", data=user_input)

        defaults = user_input or {CONF_USERNAME: DEFAULT_USERNAME}
        schema = vol.Schema(
            {
                **_connection_schema(defaults),
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME)): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            if not (errors := await self._validate(data)):
                return self.async_update_reload_and_abort(entry, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change host or HTTPS without losing the entities; the login stays."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            if host != entry.unique_id:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
            data = {**entry.data, **user_input, CONF_HOST: host}
            if not (errors := await self._validate(data)):
                return self.async_update_reload_and_abort(
                    entry, unique_id=host, title=f"Vigor {host}", data=data
                )
        # Entries from before 0.3.0 have no SSL keys: they use plain HTTP.
        current = {CONF_SSL: False, CONF_VERIFY_SSL: False, **entry.data}
        schema = vol.Schema(_connection_schema(user_input or current))
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
