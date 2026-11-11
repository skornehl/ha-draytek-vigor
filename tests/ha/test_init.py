"""Setup, entities, reauth after repeated login rejections, diagnostics."""
from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.draytek_vigor.api import InvalidAuth
from custom_components.draytek_vigor.const import LOGIN_REJECTIONS_BEFORE_REAUTH
from custom_components.draytek_vigor.diagnostics import async_get_config_entry_diagnostics


async def test_setup_creates_entities(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("binary_sensor.draytek_vigor_dsl_sync").state == "on"
    assert hass.states.get("sensor.draytek_vigor_line_status").state == "SHOWTIME"
    rate = hass.states.get("sensor.draytek_vigor_sync_rate_downstream")
    assert rate.attributes["unit_of_measurement"] == "Mbit/s"
    assert float(rate.state) == 116.797
    assert hass.states.get("sensor.draytek_vigor_snr_margin_downstream").state == "9.3"
    assert hass.states.get("button.draytek_vigor_reboot_modem") is not None

    # Error counters and interleave depth exist but start disabled.
    registry = er.async_get(hass)
    for entity_id in ("sensor.draytek_vigor_fec_corrections_near_end", "sensor.draytek_vigor_interleave_depth_downstream"):
        entry = registry.async_get(entity_id)
        assert entry is not None and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_rejected_logins_at_startup_lead_to_reauth(
    hass: HomeAssistant, mock_status: AsyncMock, config_entry
) -> None:
    """Every setup retry builds a new coordinator; the rejections must still add up."""
    mock_status.side_effect = InvalidAuth("rid 0001")
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    for _ in range(LOGIN_REJECTIONS_BEFORE_REAUTH - 1):
        await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(config_entry.domain)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_one_rejection_does_not_ask_for_a_password(
    hass: HomeAssistant, mock_status: AsyncMock, config_entry
) -> None:
    mock_status.side_effect = InvalidAuth("too many sessions")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    mock_status.side_effect = None
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert not hass.config_entries.flow.async_progress_by_handler(config_entry.domain)


async def test_diagnostics_redact_login(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["entry"]["password"] == "**REDACTED**"
    assert diag["entry"]["username"] == "**REDACTED**"
    assert diag["status"]["status"] == "SHOWTIME"
