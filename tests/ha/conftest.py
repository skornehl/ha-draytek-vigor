"""Fixtures for the Home Assistant tests (need pytest-homeassistant-custom-component).

tests/test_protocol.py does not use them and still runs with plain pytest.
"""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.draytek_vigor.const import DOMAIN
from custom_components.draytek_vigor.protocol import PORT_1G, PORT_DOWN, DslStatus, SystemStatus

HOST = "192.168.1.2"
ENTRY_DATA = {"host": HOST, "ssl": True, "verify_ssl": False, "username": "admin", "password": "secret"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def synced_status() -> DslStatus:
    return DslStatus(
        status="Showtime",
        mode="VDSL2",
        profile="17a",
        annex="ANNEX B",
        dsl_version="5.12.31.0_B_A60901",
        stream={
            "Actual Rate": (113742, 46719),
            "Attainable Rate": (124643, 48103),
            "SNR Margin": (2.9, 7.3),
            "Interleave Depth": (8, 1),
        },
        end={"Attenuation": (11.3, 2.1), "CRC": (175, 0), "LOS Failure": (0, 0)},
    )


def system_status() -> SystemStatus:
    return SystemStatus(
        model="Vigor167",
        firmware="5.2.9",
        mac="00:1D:AA:00:00:01",
        uptime=1005454,
        line_uptime=1005303,
        cpu=3,
        memory=90,
        ports={"LAN1": PORT_1G, "LAN2": PORT_DOWN},
    )


@pytest.fixture
def dashboard() -> dict[str, SystemStatus | None]:
    """What the coordinator's dashboard request returns; set ["system"] = None for none."""
    return {"system": system_status()}


@pytest.fixture
def mock_status(dashboard) -> Generator[AsyncMock]:
    """Patch the modem calls of the config flow (DSL only) and the coordinator (DSL + dashboard).

    One mock drives both, so side_effect = InvalidAuth hits the coordinator too.
    """
    dsl = AsyncMock(return_value=synced_status())

    async def get_status(_client) -> tuple[DslStatus, SystemStatus | None]:
        return await dsl(), dashboard["system"]

    with (
        patch("custom_components.draytek_vigor.api.VigorClient.async_get_dsl_status", new=dsl),
        patch("custom_components.draytek_vigor.api.VigorClient.async_get_status", new=get_status),
    ):
        yield dsl


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=HOST, data=dict(ENTRY_DATA), title=f"Vigor {HOST}")
