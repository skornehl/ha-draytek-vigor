# AGENTS.md

Home Assistant custom integration (HACS) for the DrayTek Vigor 167 DSL modem.

- Conventional Commits, branches `<type>/<slug>`, never push to `main`;
  always a pull request. Author `Sebastian Kornehl <sebastian@kornehl.org>`,
  `Co-Authored-By` trailer when an agent did the work. English in code and docs.
- `custom_components/draytek_vigor/protocol.py` holds encoding and parsing and
  must not import Home Assistant or aiohttp, so `tests/test_protocol.py` runs
  without them. Every parser change needs a test.
- Field names come from SuperQ/draytek_exporter (see NOTICE) and match a real
  Vigor 167 response (`tests/fixtures/dsl_status_idle_fw5.json`, no line
  plugged in). Add a captured fixture with a synced line once there is one.
- The aiohttp session needs `CookieJar(unsafe=True)`: the modem is addressed by
  IP and aiohttp drops cookies from IP hosts otherwise.
- `strings.json`, `translations/en.json` and `translations/de.json` stay
  key-identical; `en.json` is a copy of `strings.json`.
- Writes need the CSRF token from the `x-csrf-token` response header (sent
  back as header and `_token`); a random token only works for reads. Logout
  (`event`/553) and reboot (`0REBOOT`/555, answer `0006@1POP_REBOOTING`) were
  tested on a Vigor 167 on 2026-10-30. Never let the reboot payload carry
  anything but `Reboot_With: Current Configuration` - the same form can
  reset to factory defaults.
