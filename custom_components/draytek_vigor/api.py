"""Async client for the Vigor web API."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any, TypeVar

import aiohttp

from .protocol import (
    CSRF_HEADER,
    EVENT_PID,
    LOGOUT_OP,
    REBOOT_OP,
    REBOOT_PID,
    REBOOT_QUERY,
    DSL_OP,
    DSL_PID,
    DSL_QUERY,
    LOGIN_OP,
    LOGIN_PID,
    PATH,
    DslStatus,
    ProtocolError,
    decode,
    encode,
    is_ok,
    is_reboot_accepted,
    login_payload,
    logout_payload,
    parse_dsl_status,
    parse_reboot_record,
    reboot_payload,
)

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=15)
T = TypeVar("T")


class VigorError(Exception):
    """Base error."""


class CannotConnect(VigorError):
    """Router not reachable or answered garbage."""


class BadResponse(CannotConnect):
    """The answer was not prefix-padded base64 (redirect, HTML page)."""


class InvalidAuth(VigorError):
    """Login rejected."""


class VigorClient:
    """One logged-in web session.

    The session must use a cookie jar with unsafe=True: aiohttp drops cookies
    set by plain IP hosts otherwise, and the login would never stick.
    """

    def __init__(self, session: aiohttp.ClientSession, host: str, username: str, password: str) -> None:
        self._session = session
        self._url = f"http://{host}{PATH}"
        self._username = username
        self._password = password
        self._csrf = ""
        self._logged_in = False
        self._lock = asyncio.Lock()

    async def _post(self, pid: str, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        form = {"pid": pid, "op": op, "ct": encode(payload)}
        headers = {}
        if self._csrf:
            form["_token"] = headers[CSRF_HEADER] = self._csrf
        try:
            async with self._session.post(
                self._url, data=form, headers=headers, timeout=TIMEOUT, allow_redirects=False
            ) as resp:
                body = await resp.text(errors="replace")
                if token := resp.headers.get(CSRF_HEADER):
                    self._csrf = token
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect(f"{self._url}: {err}") from err
        try:
            return decode(body)
        except ProtocolError as err:
            # Expired session (redirect/login page) or "Force HTTPS" switched on.
            raise BadResponse(f"unexpected answer (HTTP {resp.status}): {err}") from err

    def _forget_session(self) -> None:
        self._csrf = ""
        self._logged_in = False
        self._session.cookie_jar.clear()

    async def async_login(self) -> None:
        self._forget_session()
        data = await self._post(LOGIN_PID, LOGIN_OP, login_payload(self._username, self._password))
        if not is_ok(data):
            # The rid does not say why (wrong password, too many sessions, lockout).
            raise InvalidAuth(f"login rejected (rid {data.get('rid')})")
        self._logged_in = True

    async def _request(self, pid: str, op: str, payload: dict[str, Any], parse: Callable[[dict[str, Any]], T]) -> T:
        """Post and parse; log in again once if the session looks dead.

        A dead session may answer with a rid other than 0000, with a redirect or
        HTML page, or with an empty ct - all of these trigger one fresh login.
        """
        async with self._lock:
            if self._logged_in:
                try:
                    data = await self._post(pid, op, payload)
                    if is_ok(data):
                        return parse(data)
                    _LOGGER.debug("%s answered rid %s, logging in again", pid, data.get("rid"))
                except (BadResponse, ProtocolError) as err:
                    _LOGGER.debug("%s failed (%s), logging in again", pid, err)
            await self.async_login()
            data = await self._post(pid, op, payload)
            if not is_ok(data):
                raise CannotConnect(f"{pid} failed after login (rid {data.get('rid')})")
            try:
                return parse(data)
            except ProtocolError as err:
                raise CannotConnect(str(err)) from err

    async def async_get_dsl_status(self) -> DslStatus:
        return await self._request(DSL_PID, DSL_OP, DSL_QUERY, parse_dsl_status)

    async def async_reboot(self) -> None:
        """Reboot the modem with its current configuration (about 70 s offline).

        DSL drops and resyncs; in bridge mode the router behind it dials in
        again on its own.
        """
        record = await self._request(REBOOT_PID, "501", REBOOT_QUERY, parse_reboot_record)
        async with self._lock:
            data = await self._post(REBOOT_PID, REBOOT_OP, reboot_payload(record))
            self._forget_session()
        if not is_reboot_accepted(data):
            raise CannotConnect(f"reboot not accepted (rid {data.get('rid')})")

    async def async_logout(self) -> None:
        """End the web session, so it does not count against the modem's limit."""
        async with self._lock:
            if not self._logged_in:
                return
            try:
                await self._post(EVENT_PID, LOGOUT_OP, logout_payload(self._username))
            except VigorError as err:
                _LOGGER.debug("Logout failed: %s", err)
            self._forget_session()

    async def async_close(self) -> None:
        await self.async_logout()
        await self._session.close()
