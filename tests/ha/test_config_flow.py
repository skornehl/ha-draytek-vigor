"""Config flow: user step and reauth."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    # HTTPS without certificate check is the default: the modem's certificate is self-signed.
    assert result["data"] == {"host": HOST, "ssl": True, "verify_ssl": False, "username": "admin", "password": "secret"}
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


async def test_reconfigure_switches_to_https(hass: HomeAssistant, mock_status: AsyncMock) -> None:
    """An entry from before 0.3.0 (plain HTTP, no SSL keys) moves to HTTPS and a new address."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=HOST, title=f"Vigor {HOST}",
        data={"host": HOST, "username": "admin", "password": "secret"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults == {"host": HOST, "ssl": False, "verify_ssl": False}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.3", "ssl": True, "verify_ssl": False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "192.168.1.3"
    assert entry.title == "Vigor 192.168.1.3"
    assert entry.data == {"host": "192.168.1.3", "ssl": True, "verify_ssl": False, "username": "admin", "password": "secret"}

    # Home Assistant 2025.6 also loads the entry on reconfigure; unload it so
    # no poll timer outlives the test.
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_reconfigure_rejects_other_entrys_host(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, unique_id="192.168.1.3", data={**config_entry.data, "host": "192.168.1.3"})
    other.add_to_hass(hass)
    result = await other.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "ssl": True, "verify_ssl": False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_client_url_follows_ssl(hass: HomeAssistant) -> None:
    from custom_components.draytek_vigor import create_client

    for ssl, scheme in ((True, "https"), (False, "http")):
        client = create_client(hass, {"host": HOST, "ssl": ssl, "username": "a", "password": "b"}, auto_cleanup=False)
        assert client._url == f"{scheme}://{HOST}/cgi-bin/webproc.cgi"
        await client.async_close()
    legacy = create_client(hass, {"host": HOST, "username": "a", "password": "b"}, auto_cleanup=False)
    assert legacy._url.startswith("http://")
    await legacy.async_close()
