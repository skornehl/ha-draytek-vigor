# DrayTek Vigor for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Release](https://img.shields.io/github/v/release/skornehl/ha-draytek-vigor?style=for-the-badge&color=6366F1)](https://github.com/skornehl/ha-draytek-vigor/releases)
[![Home Assistant 2025.6+](https://img.shields.io/badge/Home%20Assistant-2025.6%2B-18BCF2?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Checks](https://img.shields.io/github/actions/workflow/status/skornehl/ha-draytek-vigor/validate.yml?branch=main&style=for-the-badge&label=checks)](https://github.com/skornehl/ha-draytek-vigor/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/skornehl/ha-draytek-vigor?style=for-the-badge&color=9333EA)](LICENSE)

Shows a **DrayTek Vigor 167** modem (firmware 5.x) in Home Assistant: DSL
sync, sync and attainable rates, SNR margin, attenuation and the line error
counters, plus uptime, DSL connection time, LAN port links, CPU and memory,
and a button to reboot the modem. Set up in the UI with host, user and
password over HTTPS; no SNMP, no YAML, no OID lists.

> **Status: 1.0.0.** Running on Home Assistant 2026.10 with a Vigor 167
> (firmware 5.2.9, DSL firmware 5.12.31.0) on a synced VDSL2 17a line, over
> HTTPS: all entities and reloading are checked there, login, logout and the
> reboot earlier on the same modem. The DSL status and dashboard responses are
> captured in `tests/fixtures/`. The protocol follows
> [SuperQ/draytek_exporter](https://github.com/SuperQ/draytek_exporter). If a
> value stays empty on your modem, or you have another model or router mode,
> see [Contributing](#contributing).

## Why not just SNMP?

The Vigor 167 has an SNMP agent, and Home Assistant's
[SNMP integration](https://www.home-assistant.io/integrations/snmp/) can read
it. That works, but every value is a hand-written YAML sensor with an OID you
have to find yourself. This integration reads the modem's web API, the same
one its web UI uses, and turns it into a ready device.

| | This integration | Home Assistant SNMP |
|---|---|---|
| Setup | UI: host, user, password; the login is checked before saving. Address and HTTPS can be changed later | YAML, one `sensor:` block per value, plus the SNMP settings on the modem (community or v3 user) |
| Finding the values | Built in | `snmpwalk` the modem and work out which OID is which. DSL values sit in the ADSL line MIB or, on some firmware, the VDSL2 line MIB; DrayTek does not document this per model |
| Device in Home Assistant | One device with model, firmware, MAC and a link to the web UI | Loose entities, no device |
| Units | kbit/s shown as Mbit/s, dB, seconds, timestamps; device and state classes for long-term statistics | Raw numbers: SNR and attenuation in tenths of a dB, rates in bit/s, uptime in hundredths of a second; you scale them in `value_template` |
| DSL sync | Connectivity binary sensor, on in `Showtime` | Build it yourself from a status OID with a template |
| Line status, mode, profile, annex, DSL firmware | Text sensors | Only if you find the OIDs |
| Uptime | *Last restart* and *DSL connected since* as timestamps | `sysUpTime`; the DSL connection time only if the MIB has it |
| LAN ports | Link (connectivity) and speed class (down, 10/100 Mbit/s, 1 Gbit/s) per port | `ifOperStatus`, `ifSpeed` |
| CPU and memory | Percent | Only via vendor OIDs, if any |
| Error counters | CRC, ES, SES, UAS, HEC, LOS, LOF, LPR, LCD, near and far end (disabled by default) | Whatever the MIB on your firmware exposes |
| Traffic | **No** (see below) | `ifHCInOctets`, `ifHCOutOctets` |
| Control | Reboot button | None |
| Wrong password | Reauth dialog in the UI | Sensors go unavailable; a wrong community string looks like a timeout |
| Problem reports | Diagnostics download with the parsed status, login and MAC redacted | `snmpwalk` output |
| Translations | English, German | Your own names |

### Where you still need SNMP

**Traffic and throughput.** In bridge mode the modem has no WAN interface in
its web API, and the only byte counters it shows belong to its LAN bridge,
which counts traffic to the modem itself, not the internet traffic passing
through. If you want throughput from the modem, use SNMP's interface counters
next to this integration. Usually the router behind the modem is the better
source: it sees the same traffic, and its own integration reports it.

## Requirements

- Home Assistant 2025.6 or later. The integration's icon shows from 2026.3 on;
  older versions show a placeholder.
- Web management reachable from Home Assistant, over HTTPS (default) or HTTP.
  The modem's certificate is self-signed, so certificate verification is off
  by default.
- A web user (usually `admin`). The reboot button needs a user that may reboot
  the modem.

## Installation

[![Open in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=skornehl&repository=ha-draytek-vigor&category=integration)

**Home Assistant 2026.11 and later (Marketplace):** *Settings → Marketplace →
Add from link*, enter `skornehl/ha-draytek-vigor`, select *Add*, then open the
repository and select *Install*. Adding from a link needs a GitHub connection.
Once the integration is in the catalog, the Marketplace search finds it
without this step.

**Before 2026.11 (HACS):** HACS → ⋮ → *Custom repositories* →
`https://github.com/skornehl/ha-draytek-vigor` (type *Integration*), install,
restart Home Assistant.

The Marketplace opens the setup right after the install. Otherwise use
*Settings → Devices & services → Add integration → DrayTek Vigor*.

Entries set up before 0.3.0 keep using HTTP. Switch them with
*DrayTek Vigor → ⋮ → Reconfigure*; the entities and their history stay.
Rate sensors from before 0.3.0 move from kbit/s to Mbit/s with 0.3.3 (history
is converted), unless you picked a unit for them in the entity settings.

## Entities

| Entity | Notes |
|---|---|
| DSL sync (binary) | Connectivity; on while the line status is `Showtime` |
| Line status | Text as the modem reports it, e.g. `Showtime`, `Idle` |
| Mode, profile, annex, DSL firmware | Diagnostic text |
| Sync rate down/up | kbit/s, shown as Mbit/s |
| Attainable rate down/up | kbit/s, shown as Mbit/s |
| SNR margin down/up | dB |
| Attenuation near/far end | dB |
| DSL connected since | Timestamp of the last sync; empty while the line is down |
| LAN1 link, LAN2 link (binary) | Connectivity of each LAN port |
| LAN1 speed, LAN2 speed | Diagnostic: *Down*, *10/100 Mbit/s* or *1 Gbit/s*, from the port LED colour. The state behind it, for automations and the API, is `down`, `10_100m` or `1g`; the LED does not tell 10 from 100 Mbit/s |
| Last restart | Diagnostic timestamp of the modem's boot |
| CPU usage, memory usage | Diagnostic, percent |
| Interleave depth down/up | Diagnostic, disabled by default; 1 means fast path |
| CRC, ES, SES, UAS (near/far end) | CRC errors; errored, severely errored and unavailable seconds. Diagnostic, disabled by default; reset on resync |
| HEC errors, loss of signal, frame, power and cell delineation (near/far end) | Diagnostic counters, disabled by default |
| Reboot modem (button) | Reboots with the current configuration; the modem is offline for about a minute, DSL resyncs and a router behind it dials in again. Stays usable while polling fails |

Polled every 60 seconds with two requests (DSL status and dashboard). The
timestamps only change on a real reboot or resync, not on every poll. Counters
use the `total_increasing` state class, so a reset to zero does not break
long-term statistics. A firmware without the dashboard still gets all DSL
entities.

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

*DSL connected since* changing is a resync, even when it happened between two
polls.

The entity IDs here are the English ones. Home Assistant derives them from the
names in the language active at setup, so on a German installation the sync
sensor is `binary_sensor.draytek_vigor_dsl_synchronisation`; check yours under
*Settings → Devices & services → DrayTek Vigor*.

## Diagnostics

*Settings → Devices & services → DrayTek Vigor → ⋮ → Download diagnostics*
gives the parsed DSL and dashboard status with user, password and MAC
redacted. Attach it to issues about missing or wrong values.

## Not yet supported

- Traffic counters (see *Where you still need SNMP*).
- Other DrayTek models. Routers such as the Vigor 2865 use a different web UI;
  see [Contributing](#contributing).

The login sends an unsalted SHA-512 hash of the password, which an attacker on
the LAN could replay over plain HTTP; use HTTPS. SNMP v1/v2c sends its
community string in clear text.

<!-- ha-marketplace:exclude-start -->
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
unload and on shutdown it logs out (`pid=event, op=553`).

Each poll reads `pid=0MONITORING_DSL_GENERAL` and then `pid=0DASHBOARD`
(both `op=501`) on the same session; the dashboard request is best effort and
never triggers a new login. Reboot is `pid=0REBOOT`: read the form
(`op=501`), send it back with `op=555`.

<!-- ha-marketplace:exclude-end -->
## Contributing

So far this has only run on one Vigor 167 in bridge mode. Reports from other
setups help most, "it just works" included.

### Another model, firmware or router mode

Open an issue with the
[*Other model or mode* form](https://github.com/skornehl/ha-draytek-vigor/issues/new?template=other_model.yml).
It asks for:

- Model, firmware and DSL firmware. With a working setup they are on the
  device page in Home Assistant, otherwise on the modem's dashboard.
- Bridge or router mode, and the line type (for example VDSL2 17a, ADSL2+).
- What happened: the error at setup, or which entities stay empty or look
  wrong.
- The diagnostics download, if setup worked.

The diagnostics only hold what the integration already understands. For a
value it does not read yet, or a model where setup fails, the modem's raw
answers are needed:

1. Log in to the modem's web UI in a desktop browser, open the developer
   tools (F12) → *Network* and filter for `webproc.cgi`.
2. Open the page of the web UI that shows the value. Note `pid`, `op` and
   `ct` from each request's form data.
3. Copy each response body into a file and decode it; `ct` decodes the same
   way:

   ```bash
   python3 -c 'import base64, json, sys; b = sys.stdin.read().strip(); print(json.dumps(json.loads(base64.b64decode(b[1:] + "=" * int(b[0]))), indent=1))' < response.txt
   ```

4. Before posting, replace MAC addresses, serial numbers, public IP
   addresses and PPPoE user names, and set `td` to zeros.

**Never post the login request** (`pid=event`, `op=552`): it carries a hash
of your password that logs in just like the password. Leave out cookies and
the `x-csrf-token` header too; copying only response bodies and the `ct` of
other requests avoids all three.

**Router mode.** In bridge mode the WAN pages (`0WAN_IFNO`, `1WAN_STATUS`, …)
answer with an error, which is why internet traffic, the WAN IP and the PPPoE
state are missing (see *Where you still need SNMP*). In router mode they
should answer. Their responses and the dashboard from a modem in router mode
are what it takes to add them.

**Other models.** If the web UI also posts to `/cgi-bin/webproc.cgi`, the
model most likely speaks the same protocol and may only need other field
names. If no such requests show up, it has a different web API (the Vigor
2865 router, for example) and needs a client of its own. Open an issue
anyway with model and firmware, so it is visible which models people want.

<!-- ha-marketplace:exclude-start -->
### Code

Pull requests are welcome: a branch `<type>/<slug>`, Conventional Commits,
English in code and docs.

- `custom_components/draytek_vigor/protocol.py` holds the encoding and the
  parsers and imports neither Home Assistant nor aiohttp, so
  `tests/test_protocol.py` runs with plain `pytest`.
- The whole suite needs `pytest-homeassistant-custom-component` in one of
  the versions in `.github/workflows/validate.yml` (oldest supported and a
  current Home Assistant), then `pytest -q tests`.
- Every parser change needs a test with a real, redacted response in
  `tests/fixtures/` (MAC addresses replaced, `td` zeroed).
- When touching the reboot, keep `Reboot_With: Current Configuration`: the
  same form also resets the modem to factory defaults.
- [AGENTS.md](AGENTS.md) has more notes on the protocol and on Home Assistant
  pitfalls.

<!-- ha-marketplace:exclude-end -->
## Credits

The web API protocol follows
[SuperQ/draytek_exporter](https://github.com/SuperQ/draytek_exporter) by Ben
Kochie (Apache-2.0); see [NOTICE](NOTICE). No code was copied.

This integration was built with the help of
[Claude Code](https://claude.com/claude-code) by Anthropic.
