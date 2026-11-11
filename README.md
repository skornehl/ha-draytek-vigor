# DrayTek Vigor for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Release](https://img.shields.io/github/v/release/skornehl/ha-draytek-vigor?style=for-the-badge&color=6366F1)](https://github.com/skornehl/ha-draytek-vigor/releases)
[![Home Assistant 2025.6+](https://img.shields.io/badge/Home%20Assistant-2025.6%2B-18BCF2?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Checks](https://img.shields.io/github/actions/workflow/status/skornehl/ha-draytek-vigor/validate.yml?branch=main&style=for-the-badge&label=checks)](https://github.com/skornehl/ha-draytek-vigor/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/skornehl/ha-draytek-vigor?style=for-the-badge&color=9333EA)](LICENSE)

Shows the DSL line of a **DrayTek Vigor 167** modem (firmware 5.x) in Home
Assistant: sync state, sync and attainable rates, SNR margin, attenuation and
the line error counters, plus a button to reboot the modem. Set up in the UI
with host, user and password; no SNMP, no YAML, no OID lists.

> **Status: 0.3.0.** Login, logout, the DSL status request and the reboot are
> tested against a Vigor 167 (DSL firmware 5.12.31.0) without a DSL line. The
> line values (rates, SNR, counters) are not yet seen with a synced line; their
> field names come from
> [SuperQ/draytek_exporter](https://github.com/SuperQ/draytek_exporter), which
> supports the Vigor 167 with v5 firmware. If a value stays empty on your line,
> please open an issue with the diagnostics attached.

## Why not just SNMP?

The Vigor 167 has an SNMP agent, and Home Assistant's
[SNMP integration](https://www.home-assistant.io/integrations/snmp/) can read
it. That works, but every value is a hand-written YAML sensor with an OID you
have to find yourself. This integration reads the same line values from the
modem's web API and turns them into a ready device.

| | This integration | Home Assistant SNMP |
|---|---|---|
| Setup | UI: host, user, password; the login is checked before saving | YAML, one `sensor:` block per value, plus the SNMP settings on the modem (community or v3 user) |
| Finding the values | Built in | `snmpwalk` the modem and work out which OID is which. DSL values sit in the ADSL line MIB or, on some firmware, the VDSL2 line MIB; DrayTek does not document this per model |
| Device in Home Assistant | One device with all entities and a link to the web UI | Loose entities, no device |
| Units | kbit/s shown as Mbit/s, dB, seconds; device and state classes for long-term statistics | Raw numbers: SNR and attenuation in tenths of a dB, rates in bit/s; you scale them in `value_template` |
| DSL sync | Connectivity binary sensor, on in `SHOWTIME` | Build it yourself from a status OID with a template |
| Line status, mode, profile, annex, DSL firmware | Text sensors | Only if you find the OIDs |
| Error counters | CRC, FEC, ES, SES, UAS, HEC, LOS, LOF, LPR, LCD, near and far end (disabled by default) | Whatever the MIB on your firmware exposes |
| Control | Reboot button | None |
| Wrong password | Reauth dialog in the UI | Sensors go unavailable; a wrong community string looks like a timeout |
| Problem reports | Diagnostics download with the raw status, login redacted | `snmpwalk` output |
| Translations | English, German | Your own names |

### Where you still need SNMP

This integration only reads the DSL status page. It does **not** have:

- **Uptime** of the modem (`sysUpTime`).
- **Traffic and throughput.** The interface counters (`ifHCInOctets`,
  `ifHCOutOctets`) are only available over SNMP. In bridge mode the router
  behind the modem sees the same traffic, so its own integration is often the
  better source.
- **Interface status** of the Ethernet port (`ifOperStatus`).

Both can run side by side: keep SNMP sensors for uptime and traffic, use this
integration for the line. Reading uptime and traffic from the web API is on the
list below.

## Requirements

- Web management reachable over **HTTP** from Home Assistant. With
  *Force HTTPS* enabled the modem no longer answers on HTTP and setup fails
  with "cannot connect".
- A web user (usually `admin`). The reboot button needs a user that may reboot
  the modem.

## Installation

HACS → ⋮ → *Custom repositories* → `https://github.com/skornehl/ha-draytek-vigor`
(type *Integration*), install, restart Home Assistant, then
*Settings → Devices & services → Add integration → DrayTek Vigor*.

## Entities

| Entity | Notes |
|---|---|
| DSL sync (binary) | Connectivity; on while the line status contains `SHOWTIME` |
| Line status | Text as the modem reports it, e.g. `SHOWTIME`, `Idle` |
| Mode, profile, annex, DSL firmware | Diagnostic text |
| Sync rate down/up | kbit/s, shown as Mbit/s |
| Attainable rate down/up | kbit/s, shown as Mbit/s |
| SNR margin down/up | dB |
| Attenuation near/far end | dB |
| Interleave depth down/up | Diagnostic, disabled by default; 1 means fast path |
| CRC, ES, SES, UAS (near/far end) | CRC errors; errored, severely errored and unavailable seconds. Diagnostic, disabled by default; reset on resync |
| FEC corrections, HEC errors, loss of signal, frame, power and cell delineation (near/far end) | Diagnostic counters, disabled by default. New in 0.3.0 |
| Reboot modem (button) | Reboots with the current configuration; the modem is offline for about a minute, DSL resyncs and a router behind it dials in again. Stays usable while polling fails |

Polled every 60 seconds. Counters use the `total_increasing` state class, so a
reset to zero does not break long-term statistics.

## Automations

The integration fires no events of its own; the sync sensor is the trigger.
Notify when the line has been down for two minutes:

```yaml
automation:
  - alias: DSL sync lost
    triggers:
      - trigger: state
        entity_id: binary_sensor.draytek_vigor_dsl_sync
        to: "off"
        for: "00:02:00"
    actions:
      - action: notify.notify
        data:
          message: "DSL lost sync: {{ states('sensor.draytek_vigor_line_status') }}"
```

## Diagnostics

*Settings → Devices & services → DrayTek Vigor → ⋮ → Download diagnostics*
gives the raw DSL status block with user and password redacted. Attach it to
issues about missing or wrong values.

## Not yet supported

- Uptime and traffic counters (see *Where you still need SNMP*). The modem's
  web UI shows both; their requests still have to be captured from a Vigor 167.
- HTTPS. The modem's login sends an unsalted SHA-512 hash of the password over
  HTTP, which an attacker on the LAN can replay. SNMP v1/v2c sends its
  community string in clear text, so neither is safe on an untrusted network.
- Changing the host after setup (remove and add the integration again).
- Other DrayTek models. Routers such as the Vigor 2865 use a different web UI.

## How it talks to the modem

`POST /cgi-bin/webproc.cgi` with `pid`, `op` and `ct`. The modem hands out a
CSRF token in the `x-csrf-token` response header; the client sends the latest
one back as that header and as `_token` (writes such as the reboot need it).
`ct` and the response are JSON in base64 whose padding count is moved to the
front (`{"a":1}` → `2eyJhIjoxfQ`). Login is `pid=event, op=552` with the
SHA-512 hex digest of the password; the session cookie is reused until a
request no longer returns `rid` `0000`, then the client logs in again. A
rejected login only asks for a new password after three rejections in a row,
since the modem answers the same way when too many sessions are open. On
unload and on shutdown it logs out (`pid=event, op=553`). Reboot is
`pid=0REBOOT`: read the form (`op=501`), send it back with `op=555`.

## Credits

The web API protocol follows
[SuperQ/draytek_exporter](https://github.com/SuperQ/draytek_exporter) by Ben
Kochie (Apache-2.0); see [NOTICE](NOTICE). No code was copied.
