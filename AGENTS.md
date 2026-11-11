# AGENTS.md

Home Assistant custom integration (HACS) for the DrayTek Vigor 167 DSL modem.

- Conventional Commits, branches `<type>/<slug>`, never push to `main`;
  always a pull request. Author `Sebastian Kornehl <sebastian@kornehl.org>`.
  No `Co-Authored-By` trailer or other AI-agent reference in commit messages;
  a PR description may name the tool, but never links a session.
  English in code and docs.
- `custom_components/draytek_vigor/protocol.py` holds encoding and parsing and
  must not import Home Assistant or aiohttp, so `tests/test_protocol.py` runs
  without them. Every parser change needs a test.
- `tests/ha/` runs the config flow, setup and coordinator inside Home
  Assistant and needs `pytest-homeassistant-custom-component` (version pinned
  in `.github/workflows/validate.yml`). The login rejection count lives in
  `hass.data`, not on the coordinator: setup retries build a new coordinator.
- DSL field names come from SuperQ/draytek_exporter (see NOTICE) and match
  real Vigor 167 responses: `tests/fixtures/dsl_status_idle_fw5.json` (no line)
  and `dsl_status_showtime_fw5.json` (VDSL2 17a, 2026-11-11). `RFEC`, `NFEC`
  and `LYSMB` are framing parameters (R, N, L), not error counters - the
  exporter reads RFEC as a counter, do not.
- `0DASHBOARD` (`tests/fixtures/dashboard_fw5_2_9.json`) gives model, firmware,
  MAC, uptime in seconds, line uptime as text, CPU/memory and the port LEDs
  (`Action` 0 off, 1 green = 1G/VDSL, 2 orange = 10/100M/ADSL, from the web
  UI's `setLedStatus`). In bridge mode the WAN pids answer `rid 2010_*`, and
  the LAN byte counters (`br0`) only count traffic to the modem itself - do
  not offer them as internet traffic. Fixtures get the MAC replaced and `td`
  zeroed.
- HTTPS works with the modem's self-signed (and expired) certificate when
  verification is off; entries without `ssl` in their data use HTTP.
- The aiohttp session needs `CookieJar(unsafe=True)`: the modem is addressed by
  IP and aiohttp drops cookies from IP hosts otherwise.
- Await the logout in `async_unload_entry` (and on a failed first refresh);
  never hand it to `entry.async_on_unload`: HA only starts that coroutine and
  detaches the session right after, so the request dies half-way.
- `strings.json`, `translations/en.json` and `translations/de.json` stay
  key-identical; `en.json` is a copy of `strings.json`.
- Writes need the CSRF token from the `x-csrf-token` response header (sent
  back as header and `_token`); a random token only works for reads. Logout
  (`event`/553) and reboot (`0REBOOT`/555, answer `0006@1POP_REBOOTING`) were
  tested on a Vigor 167 on 2026-10-30. Never let the reboot payload carry
  anything but `Reboot_With: Current Configuration` - the same form can
  reset to factory defaults.
