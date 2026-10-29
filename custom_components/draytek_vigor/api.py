"""Async client for the Vigor web API."""
from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

import aiohttp

from .protocol import (
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
    login_payload,
    parse_dsl_status,
)

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=15)


class VigorError(Exception):
    """Base error."""


class CannotConnect(VigorError):
    """Router not reachable or answered garbage."""


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
        self._lock = asyncio.Lock()

    async def _post(self, pid: str, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        form = {"pid": pid, "op": op, "ct": encode(payload), "_token": self._csrf}
        try:
            async with self._session.post(self._url, data=form, timeout=TIMEOUT, allow_redirects=False) as resp:
                body = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"{self._url}: {err}") from err
        try:
            return decode(body)
        except ProtocolError as err:
            # A redirect or HTML page here usually means "Force HTTPS" is on.
            raise CannotConnect(f"unexpected answer (HTTP {resp.status}): {err}") from err

    async def async_login(self) -> None:
        self._csrf = secrets.token_hex(16)
        data = await self._post(LOGIN_PID, LOGIN_OP, login_payload(self._username, self._password))
        if not is_ok(data):
            raise InvalidAuth(f"login rejected (rid {data.get('rid')})")

    async def _request(self, pid: str, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Post, logging in again when the session has expired (rid != 0000)."""
        async with self._lock:
            if self._csrf:
                data = await self._post(pid, op, payload)
                if is_ok(data):
                    return data
                _LOGGER.debug("%s answered rid %s, logging in again", pid, data.get("rid"))
            await self.async_login()
            data = await self._post(pid, op, payload)
            if not is_ok(data):
                raise CannotConnect(f"{pid} failed after login (rid {data.get('rid')})")
            return data

    async def async_get_dsl_status(self) -> DslStatus:
        data = await self._request(DSL_PID, DSL_OP, DSL_QUERY)
        try:
            return parse_dsl_status(data)
        except ProtocolError as err:
            raise CannotConnect(str(err)) from err
