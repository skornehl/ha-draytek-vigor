# DrayTek Vigor for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Release](https://img.shields.io/github/v/release/skornehl/ha-draytek-vigor?style=for-the-badge&color=6366F1)](https://github.com/skornehl/ha-draytek-vigor/releases)
[![Home Assistant 2025.6+](https://img.shields.io/badge/Home%20Assistant-2025.6%2B-18BCF2?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Checks](https://img.shields.io/github/actions/workflow/status/skornehl/ha-draytek-vigor/validate.yml?branch=main&style=for-the-badge&label=checks)](https://github.com/skornehl/ha-draytek-vigor/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/skornehl/ha-draytek-vigor?style=for-the-badge&color=9333EA)](LICENSE)

Reads the DSL line values of a **DrayTek Vigor 167** modem (firmware 5.x)
through its web API and shows them in Home Assistant. Read-only.

> **Status: 0.2.0.** Login, logout, the DSL status request and the reboot
> are tested against a Vigor 167 (DSL firmware 5.12.31.0) without a DSL line; the line values
> (rates, SNR, counters) are not yet seen with a synced line. The protocol is
> taken from [SuperQ/draytek_exporter](https://github.com/SuperQ/draytek_exporter),
> which supports the Vigor 167 with v5 firmware.

## Requirements

- Web management reachable over **HTTP** from Home Assistant. With
  *Force HTTPS* enabled the modem no longer answers on HTTP and setup fails
  with "cannot connect".
- A web user (usually `admin`).

## Installation

HACS → custom repository `https://github.com/skornehl/ha-draytek-vigor`
(category *Integration*), install, restart Home Assistant, then
*Settings → Devices & services → Add integration → DrayTek Vigor*.

## Entities

| Entity | Notes |
|---|---|
| DSL sync (binary) | on while the line status contains `SHOWTIME` |
| Line status, mode, profile, annex, DSL firmware | text |
| Sync rate / attainable rate, down and up | kbit/s |
| SNR margin down/up, attenuation near/far | dB |
| CRC, ES, SES, UAS (near/far end) | disabled by default; reset on resync |
| Reboot modem (button) | reboots with the current configuration; the modem is offline for about a minute, DSL resyncs and a router behind it dials in again |

Polled every 60 seconds. Diagnostics contain the raw status block (login
redacted) - attach them to issues about missing or wrong values.

## How it talks to the modem

`POST /cgi-bin/webproc.cgi` with `pid`, `op` and `ct`. The modem hands out a
CSRF token in the `x-csrf-token` response header; the client sends the latest
one back as that header and as `_token` (writes such as the reboot need it).
`ct` and the response are JSON in base64 whose padding count is moved to the
front (`{"a":1}` → `2eyJhIjoxfQ`). Login is `pid=event, op=552` with the
SHA-512 hex digest of the password; the session cookie is reused until a
request no longer returns `rid` `0000`, then the client logs in again. On
unload it logs out (`pid=event, op=553`). Reboot is `pid=0REBOOT`: read the
form (`op=501`), send it back with `op=555`.
