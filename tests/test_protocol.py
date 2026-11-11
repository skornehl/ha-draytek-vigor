"""Tests for custom_components/draytek_vigor/protocol.py.

Loaded by file path so the tests need no Home Assistant installation (the
package __init__ imports homeassistant). The sample response is built from the
field names in SuperQ/draytek_exporter, not captured from a real device.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

_PATH = Path(__file__).parents[1] / "custom_components" / "draytek_vigor" / "protocol.py"
_spec = importlib.util.spec_from_file_location("vigor_protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules["vigor_protocol"] = protocol
_spec.loader.exec_module(protocol)

SAMPLE = {
    "rid": "0000",
    "ct": [
        {
            "0MONITORING_DSL_GENERAL": [
                {
                    "Name": "Setting",
                    "Status": "SHOWTIME",
                    "Mode": "VDSL2",
                    "Profile": "17A",
                    "Annex": "B",
                    "DSL_Version": "08-0C-03-04-00-07",
                    "Stream_Table": [
                        {"Name": "Actual Rate", "Downstream": "116797 kbps", "Upstream": "46719 kbps"},
                        {"Name": "Attainable Rate", "Downstream": "131000 kbps", "Upstream": "50112 kbps"},
                        {"Name": "Interleave Depth", "Downstream": "1", "Upstream": "1"},
                        {"Name": "Actual PSD", "Downstream": "-61.4 dB", "Upstream": "-58.0 dB"},
                        {"Name": "SNR Margin", "Downstream": "9.3 dB", "Upstream": "8 dB"},
                    ],
                    "End_Table": [
                        {"Name": "Bitswap", "Near_End": "ON", "Far_End": "OFF"},
                        {"Name": "Attenuation", "Near_End": "12.5 dB", "Far_End": "0 dB"},
                        {"Name": "CRC", "Near_End": "17", "Far_End": "3"},
                        {"Name": "ES", "Near_End": "4 s", "Far_End": "1 s"},
                        {"Name": "UAS", "Near_End": "", "Far_End": "n/a"},
                        {"Name": "HEC Errors", "Near_End": "0", "Far_End": "0"},
                        {"Name": "LOS Failure", "Near_End": "2", "Far_End": "0"},
                    ],
                }
            ]
        }
    ],
}


@pytest.mark.parametrize("payload", [{}, {"a": 1}, {"ab": "c"}, protocol.DSL_QUERY, SAMPLE])
def test_roundtrip(payload):
    encoded = protocol.encode(payload)
    assert "=" not in encoded
    assert protocol.decode(encoded) == payload


def test_padding_moves_to_front():
    raw = base64.b64encode(b'{"a":1}').decode()  # eyJhIjoxfQ==
    assert raw.endswith("==")
    assert protocol.encode({"a": 1}) == "2" + raw.rstrip("=")


def test_decode_rejects_garbage():
    for body in ("", "<html>", "9abc", "1!!!!"):
        with pytest.raises(protocol.ProtocolError):
            protocol.decode(body)


def test_login_hashes_password():
    payload = protocol.login_payload("admin", "geheim")
    entry = payload["ct"][0]
    assert entry["Name"] == "admin"
    assert entry["Password"] == hashlib.sha512(b"geheim").hexdigest()
    assert "geheim" not in json.dumps(payload)


def test_is_ok():
    assert protocol.is_ok({"rid": "0000"})
    assert not protocol.is_ok({"rid": "0001"})
    assert not protocol.is_ok({})


def test_parse_status():
    s = protocol.parse_dsl_status(SAMPLE)
    assert (s.status, s.mode, s.profile, s.annex) == ("SHOWTIME", "VDSL2", "17A", "B")
    assert s.stream["Actual Rate"] == (116797, 46719)
    assert s.stream["SNR Margin"] == (9.3, 8)
    assert s.stream["Actual PSD"] == (-61.4, -58)
    assert s.end["Bitswap"] == (True, False)
    assert s.end["CRC"] == (17, 3)
    assert s.end["ES"] == (4, 1)
    assert s.end["UAS"] == (None, None)
    assert s.stream["Interleave Depth"] == (1, 1)
    assert s.end["HEC Errors"] == (0, 0)
    assert s.end["LOS Failure"] == (2, 0)


def test_parse_skips_malformed_rows():
    data = json.loads(json.dumps(SAMPLE))
    setting = data["ct"][0]["0MONITORING_DSL_GENERAL"][0]
    setting["Stream_Table"].insert(0, "garbage")
    setting["End_Table"] = "not a table"
    data["ct"][0]["0MONITORING_DSL_GENERAL"].insert(0, None)
    s = protocol.parse_dsl_status(data)
    assert s.stream["Actual Rate"] == (116797, 46719)
    assert s.end == {}


def test_parse_missing_setting():
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_dsl_status({"rid": "0000", "ct": [{"0MONITORING_DSL_GENERAL": []}]})
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_dsl_status({"rid": "0000"})


def test_rates_are_normalised_to_kbps():
    data = json.loads(json.dumps(SAMPLE))
    rows = data["ct"][0]["0MONITORING_DSL_GENERAL"][0]["Stream_Table"]
    rows[0].update(Downstream="116.8 Mbps", Upstream="46719000 bps")
    rows[1].update(Downstream="131000", Upstream="50 furlongs")
    s = protocol.parse_dsl_status(data)
    assert s.stream["Actual Rate"] == (116800, 46719)
    assert s.stream["Attainable Rate"] == (131000, None)
    assert s.stream["SNR Margin"] == (9.3, 8)


def test_real_idle_response():
    """Captured from a Vigor 167 (DSL firmware 5.12.31.0) with no DSL line plugged in."""
    data = json.loads((Path(__file__).parent / "fixtures" / "dsl_status_idle_fw5.json").read_text())
    assert protocol.is_ok(data)
    s = protocol.parse_dsl_status(data)
    assert (s.status, s.mode, s.profile) == ("Idle", "DSL", "--")
    assert s.dsl_version == "5.12.31.0_A_A60901"
    assert s.stream == {} and s.end == {}
    assert protocol.decode(protocol.encode(data)) == data


def test_reboot_payload_forces_current_configuration():
    record = protocol.parse_reboot_record(
        {"rid": "0000", "ct": [{"0REBOOT": [{"Name": "Setting", "Reboot_With": "Factory Default Configuration", "Reboot_Button": ""}]}]}
    )
    payload = protocol.reboot_payload(record)
    entry = payload["ct"][0]["0REBOOT"][0]
    assert entry["name"] == "Setting"
    assert entry["data"]["Reboot_With"] == "Current Configuration"
    assert record["Reboot_With"] == "Factory Default Configuration"  # input untouched


def test_reboot_record_missing():
    for data in ({"rid": "0000", "ct": [{"0REBOOT": []}]}, {"rid": "0000"}, {"ct": [{"0REBOOT": ["x"]}]}):
        with pytest.raises(protocol.ProtocolError):
            protocol.parse_reboot_record(data)


def test_reboot_accepted():
    # Answers seen on a Vigor 167, 2026-10-30.
    assert protocol.is_reboot_accepted({"rid": "0006@1POP_REBOOTING"})
    assert not protocol.is_reboot_accepted({"rid": "2033_out_op(555)_tm(1)_stm(1)_2_ip(x)"})
    assert not protocol.is_reboot_accepted({})


def test_logout_payload():
    assert protocol.logout_payload("admin") == {"param": [], "ct": [{"Username": "admin"}]}


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def test_real_showtime_response():
    """Captured from a Vigor 167 on a synced VDSL2 17a line, 2026-11-11."""
    s = protocol.parse_dsl_status(_fixture("dsl_status_showtime_fw5.json"))
    assert (s.status, s.mode, s.profile, s.annex) == ("Showtime", "VDSL2", "17a", "ANNEX B")
    assert s.stream["Actual Rate"] == (113742, 46719)
    assert s.stream["Attainable Rate"] == (124643, 48103)  # unit written "Kbps" here
    assert s.stream["Interleave Depth"] == (8, 1)
    assert s.stream["SNR Margin"] == (2.9, 7.3)
    assert s.stream["Path Mode"] == (None, None)  # "Interleaved"/"Fast" is text
    assert s.end["Attenuation"] == (11.3, 2.1)
    assert s.end["CRC"] == (175, 0)
    assert s.end["ES"] == (20, 0)
    assert s.end["UAS"] == (127, 127)
    assert s.end["LOS Failure"] == (0, 0)
    assert s.end["ReTx"] == (True, True)
    assert s.end["FECS"] == (None, None)  # "-": not reported on this firmware


def test_real_dashboard_response():
    """Captured from a Vigor 167, firmware 5.2.9, MAC replaced."""
    data = _fixture("dashboard_fw5_2_9.json")
    assert protocol.is_ok(data)
    s = protocol.parse_dashboard(data)
    assert (s.model, s.firmware, s.mac) == ("Vigor167", "5.2.9", "00:1D:AA:00:00:01")
    assert s.uptime == 1005454
    assert s.line_uptime == 11 * 86400 + 15 * 3600 + 15 * 60 + 3
    assert (s.cpu, s.memory) == (0, 90)
    assert s.ports == {"LAN1": protocol.PORT_1G, "LAN2": protocol.PORT_1G}


def test_dashboard_port_leds():
    data = _fixture("dashboard_fw5_2_9.json")
    data["ct"][0]["2NAMEPLATE"][0]["LEDs"] = [
        {"Name": "DSL", "Action": "2"},
        {"Name": "LAN1", "Action": "0"},
        {"Name": "LAN2", "Action": "2"},
        {"Name": "LAN3", "Action": "9"},
        "garbage",
    ]
    s = protocol.parse_dashboard(data)
    assert s.ports == {"LAN1": protocol.PORT_DOWN, "LAN2": protocol.PORT_100M, "LAN3": None}


def test_dashboard_missing_blocks():
    s = protocol.parse_dashboard({"rid": "0000", "ct": [{"1SYSTEM_INFO": [{"Firmware": "5.2.9"}]}]})
    assert s.firmware == "5.2.9"
    assert s.uptime is None and s.line_uptime is None and s.ports == {}
    for data in ({"rid": "0000"}, {"rid": "0000", "ct": [{}]}, {"rid": "0000", "ct": ["x"]}):
        with pytest.raises(protocol.ProtocolError):
            protocol.parse_dashboard(data)


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("11d 15h 15m  3s", 1005303), ("0d 0h 1m 5s", 65), ("42s", 42), (1005454, 1005454), ("--", None), ("", None), (None, None)],
)
def test_parse_duration(value, seconds):
    assert protocol.parse_duration(value) == seconds
