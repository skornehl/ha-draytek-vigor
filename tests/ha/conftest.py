"""Fixtures for the Home Assistant tests (need pytest-homeassistant-custom-component).

tests/test_protocol.py does not use them and still runs with plain pytest.
"""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.draytek_vigor.const import DOMAIN
from custom_components.draytek_vigor.protocol import DslStatus

HOST = "192.168.1.2"
ENTRY_DATA = {"host": HOST, "username": "admin", "password": "secret"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def synced_status() -> DslStatus:
    return DslStatus(
        status="SHOWTIME",
        mode="VDSL2",
        profile="17A",
        annex="B",
        dsl_version="5.12.31.0_A_A60901",
        stream={
            "Actual Rate": (116797, 46719),
            "Attainable Rate": (131000, 50112),
            "SNR Margin": (9.3, 8),
            "Interleave Depth": (1, 1),
        },
        end={"Attenuation": (12.5, 0), "CRC": (17, 3), "RFEC": (1024, 88)},
    )


@pytest.fixture
def mock_status() -> Generator[AsyncMock]:
    """Patch the modem call used by the config flow and the coordinator."""
    with patch(
        "custom_components.draytek_vigor.api.VigorClient.async_get_dsl_status",
        new=AsyncMock(return_value=synced_status()),
    ) as mock:
        yield mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id=HOST, data=dict(ENTRY_DATA), title=f"Vigor {HOST}")
