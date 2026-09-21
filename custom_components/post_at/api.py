"""The two GraphQL surfaces post.at exposes.

``graphqlAuthenticated`` is used only to discover *which* parcels the account
holds. Everything else comes from ``graphqlPublic``, which is keyless,
introspectable and already relied upon by a shipped integration -- and which,
unlike the authenticated endpoint, is known to return ``trackingStateKey``.

Both endpoints localise their reply on ``Accept-Language`` -- place names,
delivery-estimate prose and the human-readable state. Post serves German to
anything that is not an ``en`` prefix, including a request with no header at
all, so it is always sent explicitly.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .auth import PostAtAuthExpired, PostAtSession
from .const import (
    DETAIL_QUERY,
    GRAPHQL_AUTHENTICATED_URL,
    GRAPHQL_PUBLIC_URL,
    LIST_QUERY,
)

_LOGGER = logging.getLogger(__name__)


class PostAtApiError(Exception):
    """Raised when post.at answers with something we cannot use."""


class PostAtApiClient:
    """Reads the account's shipment list and each parcel's public detail."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: PostAtSession,
        language: str,
    ) -> None:
        """Store the HTTP session, the B2C session and the reply language."""
        self._session = session
        self._auth = auth
        self._language = language

    @property
    def language(self) -> str:
        """The language Post is asked to answer in.

        Exposed so the coordinator can normalise parcels in the same language
        it asked for, rather than deriving it a second time from the entry.
        """
        return self._language

    async def async_list_shipments(self) -> list[dict[str, Any]]:
        """Return the account's received shipments, newest first."""
        token = await self._auth.async_get_token()
        async with self._session.post(
            GRAPHQL_AUTHENTICATED_URL,
            json={"query": LIST_QUERY},
            headers={
                "authorization": f"Bearer {token}",
                "origin": "https://www.post.at",
                "accept-language": self._language,
            },
        ) as response:
            if response.status == 401:
                raise PostAtAuthExpired("post.at rejected the access token")
            status = response.status
            payload = await _read_json(response)

        data = _unwrap(payload, status)
        shipments = (data.get("sendungen") or {}).get("sendungen")
        if not isinstance(shipments, list):
            raise PostAtApiError("post.at shipment list was not a list")
        return [s for s in shipments if isinstance(s, dict)]

    async def async_get_public_detail(
        self, tracking_code: str
    ) -> dict[str, Any] | None:
        """Return one parcel's public detail, or ``None`` if not yet scanned."""
        async with self._session.post(
            GRAPHQL_PUBLIC_URL,
            json={"query": DETAIL_QUERY, "variables": {"id": tracking_code}},
            headers={"accept-language": self._language},
        ) as response:
            status = response.status
            payload = await _read_json(response)

        # A rejected code is not worth failing the whole poll for: the code
        # came from Post's own list, so a rejection means schema drift, and one
        # unreadable parcel should not blank out the others.
        if not isinstance(payload, dict) or payload.get("errors"):
            _LOGGER.debug(
                "post.at public endpoint did not resolve %s (HTTP %s)",
                tracking_code,
                status,
            )
            return None
        if status != 200:
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        shipment = data.get("einzelsendung")
        return shipment if isinstance(shipment, dict) else None


async def _read_json(response: aiohttp.ClientResponse) -> Any:
    """Parse a JSON body, tolerating post.at's occasional text/plain errors."""
    try:
        return await response.json(content_type=None)
    except ValueError as err:
        raise PostAtApiError(f"post.at returned an unparseable body ({err})") from err


def _unwrap(payload: Any, status: int) -> dict[str, Any]:
    """Validate a GraphQL envelope and return its ``data`` object."""
    if not isinstance(payload, dict):
        raise PostAtApiError("post.at returned a non-object body")
    if errors := payload.get("errors"):
        messages = "; ".join(
            str(e.get("message")) for e in errors if isinstance(e, dict)
        )
        raise PostAtApiError(f"HTTP {status}: {messages or 'GraphQL error'}")
    if status != 200:
        raise PostAtApiError(f"HTTP {status}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise PostAtApiError("post.at response carried no data object")
    return data
