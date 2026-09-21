"""Azure AD B2C sign-in and silent token renewal for post.at.

Post's SPA client is registered implicit-only: the authorization-code grant
fails with ``AADB2C90085`` with and without PKCE, so no refresh token can be
obtained. The durable credential is therefore the B2C SSO cookie, which
``prompt=none`` exchanges for a fresh one-hour access token.

The account password is used exactly once, during :meth:`async_login`, and is
never stored anywhere.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from html import unescape
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import (
    B2C_CLIENT_ID,
    B2C_HOST,
    B2C_POLICY,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    B2C_TENANT,
    SSO_COOKIE_PREFIX,
    TOKEN_EXPIRY_SKEW_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

_SETTINGS_RE = re.compile(r"var\s+SETTINGS\s*=\s*(\{.*?\});", re.DOTALL)
_FRAGMENT_RE = re.compile(r"#(access_token=[^\"'\s]+)")


class PostAtAuthError(Exception):
    """Base class for authentication failures."""


class PostAtInvalidCredentials(PostAtAuthError):
    """The email or password was rejected by B2C."""


class PostAtAuthExpired(PostAtAuthError):
    """The stored SSO session can no longer mint tokens; reauth is required."""


@dataclass(frozen=True, slots=True)
class SsoCookie:
    """The single durable credential: B2C's SSO cookie."""

    name: str
    value: str


class PostAtSession:
    """Owns the B2C session and hands out access tokens."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        cookie: SsoCookie | None = None,
    ) -> None:
        """Store the HTTP session and, on reload, the persisted SSO cookie."""
        self._session = session
        self._cookie = cookie
        self._token: str | None = None
        self._expires_at = 0.0

    @property
    def cookie(self) -> SsoCookie | None:
        """The SSO cookie to persist in the config entry."""
        return self._cookie

    async def async_login(self, email: str, password: str) -> SsoCookie:
        """Run the sign-in journey and capture the SSO cookie.

        Raises :class:`PostAtInvalidCredentials` when B2C rejects the
        credentials, and :class:`PostAtAuthError` when the journey does not
        look the way we expect -- which is how a restyled B2C page surfaces.
        """
        found: dict[str, str] = {}
        authorize = self._authorize_url(
            prompt_none=False, tenant=B2C_TENANT, policy=B2C_POLICY
        )
        async with self._session.get(authorize) as response:
            _absorb_cookies(response, found)
            page = await response.text()
        settings = _parse_settings(page)

        # Prefer the journey the page itself names, so a policy rename does
        # not break the login; the compiled-in values are only the starting
        # point for this first request.
        base, policy = _journey_base(settings)
        csrf = settings.get("csrf")
        trans_id = settings.get("transId")
        if not csrf or not trans_id:
            raise PostAtAuthError("post.at sign-in page is missing csrf/transId")

        query = urlencode({"tx": trans_id, "p": policy})
        async with self._session.post(
            f"{base}/SelfAsserted?{query}",
            data={
                "request_type": "RESPONSE",
                "signInName": email,
                "password": password,
            },
            headers={
                "x-csrf-token": csrf,
                "x-requested-with": "XMLHttpRequest",
                "origin": B2C_HOST,
                "referer": authorize,
                "cookie": cookie_header(found),
            },
            # The Cookie header is set explicitly, and aiohttp keeps explicit
            # headers across redirects -- including origin-changing ones. This
            # response is expected to be JSON, so never follow a redirect and
            # never risk handing B2C's session cookies to another host.
            allow_redirects=False,
        ) as response:
            _absorb_cookies(response, found)
            body = await response.text()
        try:
            result = json.loads(body)
        except ValueError as err:
            raise PostAtAuthError("post.at sign-in returned a non-JSON reply") from err
        if str(result.get("status")) != "200":
            raise PostAtInvalidCredentials(str(result.get("message") or "rejected"))

        api = settings.get("api") or "CombinedSigninAndSignup"
        confirm_query = urlencode(
            {
                # Ask for a persistent session; a per-browser-session cookie
                # would strand the integration as soon as B2C expired it.
                "rememberMe": "true",
                "csrf_token": csrf,
                "tx": trans_id,
                "p": policy,
            }
        )
        async with self._session.get(
            f"{base}/api/{api}/confirmed?{confirm_query}",
            headers={"referer": authorize, "cookie": cookie_header(found)},
            allow_redirects=False,
        ) as response:
            _absorb_cookies(response, found)

        cookie = self._pick_sso_cookie(found)
        if cookie is None:
            raise PostAtAuthError("post.at sign-in produced no SSO cookie")
        self._cookie = cookie
        self._token = None
        self._expires_at = 0.0
        return cookie

    def invalidate_token(self) -> None:
        """Drop the cached access token so the next call mints a fresh one.

        The cache is purely clock-based, so a token post.at rejects early --
        revoked, or invalidated by a password change -- would otherwise be
        replayed until its nominal hour was up. The coordinator calls this
        before its one 401 retry; without it the retry is a no-op.
        """
        self._token = None
        self._expires_at = 0.0

    async def async_get_token(self) -> str:
        """Return a valid access token, renewing silently when needed."""
        if self._token and time.time() < self._expires_at:
            return self._token
        if self._cookie is None:
            raise PostAtAuthExpired("no stored post.at session")

        url = self._authorize_url(
            prompt_none=True, tenant=B2C_TENANT, policy=B2C_POLICY
        )
        async with self._session.get(
            url,
            headers={"cookie": cookie_header({self._cookie.name: self._cookie.value})},
            allow_redirects=False,
        ) as response:
            location = response.headers.get("Location", "")
            body = "" if location else await response.text()

        fragment = _fragment_from(location, body)
        if fragment is None:
            raise PostAtAuthExpired("post.at did not redirect with a token")
        params = parse_qs(fragment)
        if "error" in params:
            raise PostAtAuthExpired(
                f"post.at refused silent renewal: {params['error'][0]}"
            )
        token = params.get("access_token", [None])[0]
        if not token:
            raise PostAtAuthExpired("post.at returned no access token")

        expires_in = params.get("expires_in", ["3600"])[0]
        try:
            lifetime = int(expires_in)
        except ValueError:
            lifetime = 3600
        self._token = token
        self._expires_at = time.time() + lifetime - TOKEN_EXPIRY_SKEW_SECONDS
        return token

    def _authorize_url(self, *, prompt_none: bool, tenant: str, policy: str) -> str:
        """Build an implicit authorize request.

        ``response_type=id_token token`` with ``response_mode=fragment`` is what
        Post's own SPA uses, and the only grant this client supports.
        """
        params = {
            "client_id": B2C_CLIENT_ID,
            "redirect_uri": B2C_REDIRECT_URI,
            "scope": B2C_SCOPE,
            "response_type": "id_token token",
            "response_mode": "fragment",
            "state": secrets.token_urlsafe(8),
            "nonce": secrets.token_urlsafe(8),
        }
        if prompt_none:
            params["prompt"] = "none"
        return f"{B2C_HOST}/{tenant}/{policy}/oauth2/v2.0/authorize?{urlencode(params)}"

    def _pick_sso_cookie(self, found: dict[str, str]) -> SsoCookie | None:
        """Choose the SSO cookie out of everything the journey set.

        ``Set-Cookie`` headers are read directly rather than through the
        session's jar: the jar is shared, its contents depend on redirect
        handling, and nothing guarantees the cookie is still there by the time
        the journey ends. The jar is still consulted as a fallback.

        An empty value is skipped: a ``Set-Cookie`` that *deletes* the cookie
        carries the same name, and persisting it would produce a sign-in that
        reports success and then fails on the first poll with an opaque
        reauth loop, instead of failing here where the message is clear.
        """
        for name, value in found.items():
            if _is_sso_cookie(name) and value:
                return SsoCookie(name, value)
        for cookie in self._session.cookie_jar:
            if _is_sso_cookie(cookie.key) and cookie.value:
                return SsoCookie(cookie.key, cookie.value)
        return None


def _journey_base(settings: dict[str, Any]) -> tuple[str, str]:
    """Return the journey's URL prefix and policy name from ``SETTINGS``.

    ``hosts.tenant`` is **not** a tenant id -- it is a path prefix that already
    contains the policy, e.g. ``/f098c632-.../B2C_1A_signup_signin``. Appending
    the policy to it again yields a doubled segment and a 404, which is exactly
    how this went wrong the first time. The policy is returned separately only
    because it is also needed as the ``p`` query parameter.
    """
    hosts = settings.get("hosts") or {}
    prefix = str(hosts.get("tenant") or "").strip()
    policy = str(hosts.get("policy") or B2C_POLICY)
    if not prefix:
        return f"{B2C_HOST}/{B2C_TENANT}/{policy}", policy
    return f"{B2C_HOST}/{prefix.strip('/')}", policy


def _is_sso_cookie(name: str) -> bool:
    """Whether a cookie name is B2C's SSO cookie.

    ``x-ms-cpim-csrf`` shares the prefix and is not what we persist.
    """
    return name.startswith(SSO_COOKIE_PREFIX) and "csrf" not in name


def _absorb_cookies(response: aiohttp.ClientResponse, into: dict[str, str]) -> None:
    """Record every cookie this response and its redirect chain set.

    ``response.headers`` only carries the final hop, so ``history`` is walked
    too -- B2C sets its transaction cookies part-way through a redirect chain.
    """
    for hop in (*response.history, response):
        for raw in hop.headers.getall("Set-Cookie", []):
            jar = SimpleCookie()
            try:
                jar.load(raw)
            except CookieError:  # pragma: no cover - malformed header from Post
                _LOGGER.debug("Ignoring unparseable Set-Cookie from post.at")
                continue
            for name, morsel in jar.items():
                into[name] = morsel.value


def cookie_header(cookies: dict[str, str]) -> str:
    """Serialise cookies verbatim for a ``Cookie`` request header.

    Deliberately not left to aiohttp's ``CookieJar``. That jar round-trips
    through :class:`http.cookies.SimpleCookie`, which quotes any value holding
    characters outside the legal token set -- and B2C's values are full of
    ``=``, ``+`` and ``/``, while one cookie name even contains a ``|``. Post
    answers the resulting header with a bare ``Bad Request`` before it looks at
    the credentials at all. Writing the header by hand, exactly as the browser
    does, is the whole difference between a working login and a broken one.

    The sessions this module is handed are therefore created with a
    ``DummyCookieJar``; see ``async_create_clientsession`` in ``__init__.py``
    and ``config_flow.py``.
    """
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _parse_settings(page: str) -> dict[str, Any]:
    """Pull B2C's injected SETTINGS blob out of the sign-in page."""
    match = _SETTINGS_RE.search(page)
    if not match:
        raise PostAtAuthError("post.at sign-in page has no SETTINGS blob")
    try:
        parsed = json.loads(unescape(match.group(1)))
    except ValueError as err:
        raise PostAtAuthError("post.at SETTINGS blob is not valid JSON") from err
    if not isinstance(parsed, dict):
        raise PostAtAuthError("post.at SETTINGS blob is not an object")
    return parsed


def _fragment_from(location: str, body: str) -> str | None:
    """Return the URL fragment carrying the token, from a redirect or a body."""
    if location:
        return urlparse(location).fragment or None
    match = _FRAGMENT_RE.search(body)
    return match.group(1) if match else None
