"""Setup, entities, reauth after repeated login rejections, diagnostics."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.draytek_vigor.api import CannotConnect, InvalidAuth, VigorClient
from custom_components.draytek_vigor.const import DOMAIN, LOGIN_REJECTIONS_BEFORE_REAUTH
from custom_components.draytek_vigor.diagnostics import async_get_config_entry_diagnostics


async def test_setup_creates_entities(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("binary_sensor.draytek_vigor_dsl_sync").state == "on"
    assert hass.states.get("sensor.draytek_vigor_line_status").state == "Showtime"
    rate = hass.states.get("sensor.draytek_vigor_sync_rate_downstream")
    assert rate.attributes["unit_of_measurement"] == "Mbit/s"
    assert float(rate.state) == 113.742
    assert hass.states.get("sensor.draytek_vigor_snr_margin_downstream").state == "2.9"
    assert hass.states.get("button.draytek_vigor_reboot_modem") is not None

    # Error counters and interleave depth exist but start disabled.
    registry = er.async_get(hass)
    for entity_id in ("sensor.draytek_vigor_loss_of_signal_near_end", "sensor.draytek_vigor_interleave_depth_downstream"):
        entry = registry.async_get(entity_id)
        assert entry is not None and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_dashboard_entities(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    now = dt_util.utcnow()

    booted = dt_util.parse_datetime(hass.states.get("sensor.draytek_vigor_last_restart").state)
    assert abs((now - booted).total_seconds() - 1005454) < 5
    synced = dt_util.parse_datetime(hass.states.get("sensor.draytek_vigor_dsl_connected_since").state)
    assert abs((now - synced).total_seconds() - 1005303) < 5
    assert hass.states.get("sensor.draytek_vigor_cpu_usage").state == "3"
    assert hass.states.get("sensor.draytek_vigor_memory_usage").state == "90"
    assert hass.states.get("binary_sensor.draytek_vigor_lan1_link").state == "on"
    assert hass.states.get("binary_sensor.draytek_vigor_lan2_link").state == "off"
    assert hass.states.get("sensor.draytek_vigor_lan1_speed").state == "1g"
    assert hass.states.get("sensor.draytek_vigor_lan2_speed").state == "down"

    # async_get_device is deprecated from 2026.10 on; this lookup works on all
    # supported versions.
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert (DOMAIN, config_entry.entry_id) in device.identifiers
    assert (device.model, device.sw_version) == ("Vigor167", "5.2.9")
    assert (dr.CONNECTION_NETWORK_MAC, "00:1d:aa:00:00:01") in device.connections
    assert device.configuration_url == "https://192.168.1.2"

    # The next poll moves "now - uptime" by a few seconds; the timestamp stays.
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert dt_util.parse_datetime(hass.states.get("sensor.draytek_vigor_last_restart").state) == booted


async def test_without_dashboard(
    hass: HomeAssistant, mock_status: AsyncMock, dashboard, config_entry
) -> None:
    """Firmware without the dashboard: the line values still work."""
    dashboard["system"] = None
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.draytek_vigor_dsl_sync").state == "on"
    assert hass.states.get("sensor.draytek_vigor_last_restart") is None
    assert hass.states.get("binary_sensor.draytek_vigor_lan1_link") is None


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
    assert diag["status"]["dsl"]["status"] == "Showtime"
    assert diag["status"]["system"]["mac"] == "**REDACTED**"


async def test_reboot_failure_is_translated(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with (
        patch(
            "custom_components.draytek_vigor.api.VigorClient.async_reboot",
            new=AsyncMock(side_effect=CannotConnect("reboot not accepted (rid 2033)")),
        ),
        pytest.raises(HomeAssistantError) as err,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.draytek_vigor_reboot_modem"}, blocking=True
        )
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "reboot_failed"
    assert str(err.value) == "Reboot failed: reboot not accepted (rid 2033)"


async def _logout_after_connect(client: VigorClient, seen: list[bool]) -> None:
    # A real request suspends while connecting; HA detaches the session in the
    # meantime if nobody awaits the logout (aiohttp then fails with
    # AttributeError '_timeout_ceil_threshold' and "Unclosed connection").
    await asyncio.sleep(0)
    seen.append(client._session.closed)


async def test_unload_logs_out_before_the_session_is_detached(
    hass: HomeAssistant, mock_status: AsyncMock, config_entry
) -> None:
    config_entry.add_to_hass(hass)
    seen: list[bool] = []
    with patch.object(VigorClient, "async_logout", lambda self: _logout_after_connect(self, seen)):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
    assert seen == [False]


async def test_failed_setup_logs_out_before_the_session_is_detached(
    hass: HomeAssistant, mock_status: AsyncMock, config_entry
) -> None:
    mock_status.side_effect = CannotConnect("timeout")
    config_entry.add_to_hass(hass)

    seen: list[bool] = []
    with patch.object(VigorClient, "async_logout", lambda self: _logout_after_connect(self, seen)):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert seen == [False]


def _old_rate_entity(hass: HomeAssistant, config_entry, options: dict | None) -> str:
    """A rate sensor as an older version left it in the entity registry."""
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{config_entry.entry_id}_rate_down",
        config_entry=config_entry,
        suggested_object_id="draytek_vigor_sync_rate_downstream",
        unit_of_measurement="kbit/s",
    )
    for domain, values in (options or {}).items():
        registry.async_update_entity_options(entity.entity_id, domain, values)
    return entity.entity_id


@pytest.mark.parametrize(
    "options",
    [
        None,  # straight from 0.2.x
        {"sensor.private": {"suggested_unit_of_measurement": "kbit/s"}},  # after 0.3.0-0.3.2
    ],
)
async def test_old_rate_sensors_move_to_mbit(hass: HomeAssistant, mock_status: AsyncMock, config_entry, options) -> None:
    config_entry.add_to_hass(hass)
    entity_id = _old_rate_entity(hass, config_entry, options)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["unit_of_measurement"] == "Mbit/s"
    assert float(state.state) == 113.742

    # A second start changes nothing.
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["unit_of_measurement"] == "Mbit/s"


async def test_unit_chosen_by_the_user_stays(hass: HomeAssistant, mock_status: AsyncMock, config_entry) -> None:
    config_entry.add_to_hass(hass)
    entity_id = _old_rate_entity(
        hass,
        config_entry,
        {"sensor": {"unit_of_measurement": "kbit/s"}, "sensor.private": {"suggested_unit_of_measurement": "kbit/s"}},
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes["unit_of_measurement"] == "kbit/s"
    assert state.state == "113742"
