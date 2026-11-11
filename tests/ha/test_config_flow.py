"""Config flow: user step and reauth."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.draytek_vigor.api import CannotConnect, InvalidAuth
from custom_components.draytek_vigor.const import DOMAIN

from .conftest import HOST


async def test_user_flow_normalises_host(hass: HomeAssistant, mock_status: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": f" HTTP://{HOST}/ ", "username": "admin", "password": "secret"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Vigor {HOST}"
    assert result["data"] == {"host": HOST, "username": "admin", "password": "secret"}
    assert result["result"].unique_id == HOST


@pytest.mark.parametrize(
    ("error", "key"),
    [(InvalidAuth("rid 0001"), "invalid_auth"), (CannotConnect("timeout"), "cannot_connect"), (RuntimeError, "unknown")],
)
async def test_user_flow_errors_recover(hass: HomeAssistant, mock_status: AsyncMock, error, key) -> None:
    mock_status.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    user_input = {"host": HOST, "username": "admin", "password": "secret"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    mock_status.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "username": "admin", "password": "other"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_status.side_effect = InvalidAuth("rid 0001")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "admin", "password": "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_status.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "admin", "password": "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new"
    assert config_entry.data["host"] == HOST
