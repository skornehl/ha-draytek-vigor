"""Async client for the Vigor web API."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import secrets
from typing import Any, TypeVar

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
        self._lock = asyncio.Lock()

    async def _post(self, pid: str, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        form = {"pid": pid, "op": op, "ct": encode(payload), "_token": self._csrf}
        try:
            async with self._session.post(self._url, data=form, timeout=TIMEOUT, allow_redirects=False) as resp:
                body = await resp.text(errors="replace")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect(f"{self._url}: {err}") from err
        try:
            return decode(body)
        except ProtocolError as err:
            # Expired session (redirect/login page) or "Force HTTPS" switched on.
            raise BadResponse(f"unexpected answer (HTTP {resp.status}): {err}") from err

    async def async_login(self) -> None:
        self._csrf = secrets.token_hex(16)
        data = await self._post(LOGIN_PID, LOGIN_OP, login_payload(self._username, self._password))
        if not is_ok(data):
            # The rid does not say why (wrong password, too many sessions, lockout).
            raise InvalidAuth(f"login rejected (rid {data.get('rid')})")

    async def _request(self, pid: str, op: str, payload: dict[str, Any], parse: Callable[[dict[str, Any]], T]) -> T:
        """Post and parse; log in again once if the session looks dead.

        A dead session may answer with a rid other than 0000, with a redirect or
        HTML page, or with an empty ct - all of these trigger one fresh login.
        """
        async with self._lock:
            if self._csrf:
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

    async def async_close(self) -> None:
        await self._session.close()
