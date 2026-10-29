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
