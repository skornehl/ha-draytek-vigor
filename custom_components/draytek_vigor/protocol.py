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


def parse_dsl_status(data: dict[str, Any]) -> DslStatus:
    try:
        general = data["ct"][0]["0MONITORING_DSL_GENERAL"]
        setting = next(e for e in general if e.get("Name") == "Setting")
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
    for row in setting.get("Stream_Table") or []:
        if name := row.get("Name"):
            conv = _kbps if name.endswith("Rate") else _number
            status.stream[name] = (conv(row.get("Downstream")), conv(row.get("Upstream")))
    for row in setting.get("End_Table") or []:
        if name := row.get("Name"):
            near, far = row.get("Near_End"), row.get("Far_End")
            if name in ("Bitswap", "ReTx"):
                status.end[name] = (_option(near), _option(far))
            else:
                status.end[name] = (_number(near), _number(far))
    return status
