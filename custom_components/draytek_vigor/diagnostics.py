"""Diagnostics: the parsed status, needed to check field names on new firmware."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import VigorConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "mac"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: VigorConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "status": async_redact_data(asdict(data), TO_REDACT) if data is not None else None,
    }
