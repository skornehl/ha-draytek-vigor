"""Wire format of the DrayTek Vigor "v5" web API (Vigor 167).

Pure functions only - no Home Assistant, no aiohttp - so tests/test_protocol.py
runs without either.

The protocol was taken from SuperQ/draytek_exporter (Apache-2.0, Ben Kochie),
see NOTICE:

* POST form to /cgi-bin/webproc.cgi with pid, op and ct.
* CSRF: the modem sends a token in the response header x-csrf-token; the
  client returns the latest one as that header and as form field _token.
  Reads work without it, writes (reboot) answer rid 2033 "Login Timeout"
  otherwise (found against a Vigor 167, 2026-10-30; the exporter sends a
  random token and only reads).
* ct is JSON in base64 whose padding moved to the front: the number of "="
  becomes the first character and the trailing "=" are dropped. Responses
  use the same encoding.
* HTTP status is always 200; success is {"rid": "0000"} in the payload.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any

PATH = "/cgi-bin/webproc.cgi"
RID_OK = "0000"

CSRF_HEADER = "x-csrf-token"

EVENT_PID = "event"
LOGIN_PID = EVENT_PID
LOGIN_OP = "552"
LOGOUT_OP = "553"
REBOOT_PID = "0REBOOT"
REBOOT_READ_OP = "501"
REBOOT_OP = "555"
REBOOT_QUERY = {"param": [], "ct": [{REBOOT_PID: []}]}
# The modem answers an accepted reboot with "0006@1POP_REBOOTING".
RID_REBOOTING = "0006"
REBOOT_WITH_CURRENT = "Current Configuration"
DSL_PID = "0MONITORING_DSL_GENERAL"
DSL_OP = "501"
DSL_QUERY = {
    "param": [],
    "ct": [{"0MONITORING_DSL_GENERAL": []}, {"1MON_DSL_STREAM_TABLE": []}, {"1MON_DSL_END_TABLE": []}],
}


class ProtocolError(Exception):
    """The response could not be decoded or parsed."""


def encode(payload: dict[str, Any]) -> str:
    raw = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    stripped = raw.rstrip("=")
    return f"{len(raw) - len(stripped)}{stripped}"


def decode(body: str) -> dict[str, Any]:
    body = body.strip()
    if not body or body[0] not in "012":
        raise ProtocolError("response is not prefix-padded base64")
    try:
        raw = base64.b64decode(body[1:] + "=" * int(body[0]), validate=True)
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as err:
        raise ProtocolError(f"cannot decode response: {err}") from err
    if not isinstance(data, dict):
        raise ProtocolError("response is not a JSON object")
    return data


def login_payload(username: str, password: str) -> dict[str, Any]:
    digest = hashlib.sha512(password.encode()).hexdigest()
    return {"param": [], "ct": [{"Name": username, "Password": digest, "locales": "en"}]}


def logout_payload(username: str) -> dict[str, Any]:
    return {"param": [], "ct": [{"Username": username}]}


def is_ok(data: dict[str, Any]) -> bool:
    return str(data.get("rid")) == RID_OK


def parse_reboot_record(data: dict[str, Any]) -> dict[str, Any]:
    try:
        record = data["ct"][0][REBOOT_PID][0]
    except (KeyError, IndexError, TypeError) as err:
        raise ProtocolError("no reboot record in response") from err
    if not isinstance(record, dict) or "Name" not in record:
        raise ProtocolError("reboot record has no Name")
    return record


def reboot_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Payload the web UI sends for System Reboot.

    Reboot_With is forced to the current configuration: the same form can
    also reboot into factory defaults.
    """
    data = {**record, "Reboot_With": REBOOT_WITH_CURRENT}
    return {"param": [], "ct": [{REBOOT_PID: [{"name": record["Name"], "data": data}]}]}


def is_reboot_accepted(data: dict[str, Any]) -> bool:
    return str(data.get("rid", "")).split("@")[0] in (RID_REBOOTING, RID_OK)


@dataclass
class DslStatus:
    status: str | None = None
    mode: str | None = None
    profile: str | None = None
    annex: str | None = None
    dsl_version: str | None = None
    # (downstream, upstream); rates in kbit/s, margins/PSD in dB(m)
    stream: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    # (near end, far end); counters, seconds, dB or bool for ON/OFF
    end: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _number(value: Any) -> float | None:
    """'52044 kbps' -> 52044, '6.2 dB' -> 6.2, '12 s' -> 12, '7' -> 7, junk -> None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = float(value.split()[0])
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


_RATE_FACTOR = {"bps": 0.001, "kbps": 1, "mbps": 1000, "gbps": 1_000_000}


def _kbps(value: Any) -> float | None:
    """Rate in kbit/s: '52044 kbps' -> 52044, '116.8 Mbps' -> 116800; unknown unit -> None."""
    number = _number(value)
    if number is None or not isinstance(value, str):
        return number
    parts = value.split()
    factor = _RATE_FACTOR.get(parts[1].lower()) if len(parts) > 1 else 1
    if factor is None:
        return None
    result = number * factor
    return int(result) if float(result).is_integer() else result


def _option(value: Any) -> bool | None:
    if value == "ON":
        return True
    if value == "OFF":
        return False
    return None


def _rows(table: Any) -> list[dict[str, Any]]:
    """The dict rows of a Stream_Table/End_Table; anything else is skipped."""
    if not isinstance(table, list):
        return []
    return [row for row in table if isinstance(row, dict)]


def parse_dsl_status(data: dict[str, Any]) -> DslStatus:
    try:
        general = data["ct"][0]["0MONITORING_DSL_GENERAL"]
        setting = next(e for e in general if isinstance(e, dict) and e.get("Name") == "Setting")
    except (KeyError, IndexError, TypeError, StopIteration) as err:
        raise ProtocolError("no DSL 'Setting' block in response") from err

    status = DslStatus(
        status=setting.get("Status"),
        mode=setting.get("Mode"),
        profile=setting.get("Profile"),
        annex=setting.get("Annex"),
        dsl_version=setting.get("DSL_Version"),
        raw=setting,
    )
    for row in _rows(setting.get("Stream_Table")):
        if name := row.get("Name"):
            conv = _kbps if name.endswith("Rate") else _number
            status.stream[name] = (conv(row.get("Downstream")), conv(row.get("Upstream")))
    for row in _rows(setting.get("End_Table")):
        if name := row.get("Name"):
            near, far = row.get("Near_End"), row.get("Far_End")
            if name in ("Bitswap", "ReTx"):
                status.end[name] = (_option(near), _option(far))
            else:
                status.end[name] = (_number(near), _number(far))
    return status


# The dashboard of the web UI: system info, LAN port LEDs, CPU and memory, and
# the line uptime. In bridge mode the modem has no WAN interface, so the WAN
# pids (0WAN_IFNO, 1WAN_STATUS, ...) answer rid 2010_* and the LAN usage block
# only counts traffic to the modem itself (br0), not the bridged internet
# traffic - it is left out on purpose. Seen on a Vigor 167, firmware 5.2.9,
# 2026-11-11 (tests/fixtures/dashboard_fw5_2_9.json).
DASHBOARD_PID = "0DASHBOARD"
DASHBOARD_OP = "501"
DASHBOARD_QUERY = {"param": [], "ct": [{DASHBOARD_PID: []}]}

# LED "Action" of the port picture: 0 off, 1 green (1G, or VDSL for the DSL
# LED), 2 orange (10/100M, or ADSL). Taken from the web UI's setLedStatus().
PORT_DOWN = "down"
PORT_100M = "10_100m"
PORT_1G = "1g"
_PORT_LINK = {"0": PORT_DOWN, "1": PORT_1G, "2": PORT_100M}

_DURATION_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_DURATION = re.compile(r"(\d+)\s*([dhms])\b")


@dataclass
class SystemStatus:
    model: str | None = None
    firmware: str | None = None
    mac: str | None = None
    uptime: int | None = None  # seconds since boot
    line_uptime: int | None = None  # seconds since the last DSL sync
    cpu: float | None = None  # percent
    memory: float | None = None  # percent
    # LAN port name ("LAN1") -> PORT_DOWN, PORT_100M, PORT_1G or None (unknown LED state)
    ports: dict[str, str | None] = field(default_factory=dict)


def parse_duration(value: Any) -> int | None:
    """'11d 15h 15m  3s' -> 1005303 seconds; '--' or junk -> None."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    parts = _DURATION.findall(value.lower())
    if not parts:
        return None
    return sum(int(number) * _DURATION_UNITS[unit] for number, unit in parts)


def _block(blocks: dict[str, Any], pid: str) -> dict[str, Any]:
    """First record of a dashboard block, {} when missing or malformed."""
    rows = blocks.get(pid)
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def parse_dashboard(data: dict[str, Any]) -> SystemStatus:
    try:
        blocks = data["ct"][0]
    except (KeyError, IndexError, TypeError) as err:
        raise ProtocolError("no dashboard blocks in response") from err
    if not isinstance(blocks, dict):
        raise ProtocolError("dashboard blocks are not an object")

    nameplate = _block(blocks, "2NAMEPLATE")
    system = _block(blocks, "1SYSTEM_INFO")
    dsl = _block(blocks, "1DSL_STS_INFO_LITE")
    usage = _block(blocks, "1SYSTEM_USAGE")
    if not (nameplate or system or dsl or usage):
        raise ProtocolError("dashboard has none of the expected blocks")

    ports: dict[str, str | None] = {}
    for led in nameplate.get("LEDs") or []:
        if isinstance(led, dict) and str(led.get("Name", "")).startswith("LAN"):
            ports[led["Name"]] = _PORT_LINK.get(str(led.get("Action")))

    return SystemStatus(
        model=_text(nameplate.get("Model")),
        firmware=_text(system.get("Firmware")),
        mac=_text(system.get("LAN_MAC")),
        uptime=parse_duration(system.get("System_Uptime")),
        line_uptime=parse_duration(dsl.get("Line_Uptime")),
        cpu=_number(usage.get("CPU_Utilization")),
        memory=_number(usage.get("MEMORY_Utilization")),
        ports=ports,
    )
