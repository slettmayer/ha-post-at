"""The two GraphQL surfaces."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    mock_aiohttp_client,
)

from custom_components.post_at.api import PostAtApiClient, PostAtApiError
from custom_components.post_at.auth import PostAtAuthExpired
from custom_components.post_at.const import (
    GRAPHQL_AUTHENTICATED_URL,
    GRAPHQL_PUBLIC_URL,
)
from tests.conftest import make_mock_session

FIXTURES = Path(__file__).parent / "fixtures"
LIST_RESPONSE = json.loads((FIXTURES / "list_response.json").read_text())
DETAIL_RESPONSE = json.loads((FIXTURES / "detail_response.json").read_text())


def _auth(token="TOKEN"):
    auth = AsyncMock()
    auth.async_get_token = AsyncMock(return_value=token)
    return auth


def _client(mocker, auth=None):
    return PostAtApiClient(make_mock_session(mocker), auth or _auth())


async def test_list_shipments_returns_the_shipment_list():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_AUTHENTICATED_URL, status=200, json=LIST_RESPONSE)
        shipments = await _client(mocker).async_list_shipments()

    assert [s["sendungsnummer"] for s in shipments] == [
        "0000000000000000000001",
        "0000000000000000000002",
    ]


async def test_list_shipments_sends_a_bearer_token():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_AUTHENTICATED_URL, status=200, json=LIST_RESPONSE)
        await _client(mocker, _auth("ABC")).async_list_shipments()
        _method, _url, _data, headers = mocker.mock_calls[0]

    assert headers["authorization"] == "Bearer ABC"


async def test_list_shipments_raises_expired_on_401():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_AUTHENTICATED_URL, status=401, json={})
        with pytest.raises(PostAtAuthExpired):
            await _client(mocker).async_list_shipments()


async def test_list_shipments_raises_api_error_on_graphql_errors():
    with mock_aiohttp_client() as mocker:
        mocker.post(
            GRAPHQL_AUTHENTICATED_URL,
            status=200,
            json={"errors": [{"message": "boom"}]},
        )
        with pytest.raises(PostAtApiError, match="boom"):
            await _client(mocker).async_list_shipments()


async def test_list_shipments_raises_api_error_on_a_broken_envelope():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_AUTHENTICATED_URL, status=200, json={"data": None})
        with pytest.raises(PostAtApiError):
            await _client(mocker).async_list_shipments()


async def test_list_shipments_raises_api_error_when_the_list_is_not_a_list():
    with mock_aiohttp_client() as mocker:
        mocker.post(
            GRAPHQL_AUTHENTICATED_URL,
            status=200,
            json={"data": {"sendungen": {"sendungen": "nope"}}},
        )
        with pytest.raises(PostAtApiError):
            await _client(mocker).async_list_shipments()


async def test_list_shipments_tolerates_an_empty_account():
    with mock_aiohttp_client() as mocker:
        mocker.post(
            GRAPHQL_AUTHENTICATED_URL,
            status=200,
            json={"data": {"sendungen": {"sendungen": []}}},
        )
        assert await _client(mocker).async_list_shipments() == []


async def test_public_detail_returns_the_shipment():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_PUBLIC_URL, status=200, json=DETAIL_RESPONSE)
        detail = await _client(mocker).async_get_public_detail("0000000000000000000001")

    assert detail["sendungsEvents"][0]["trackingStateKey"] == "deliveryHandOver"


async def test_public_detail_sends_the_code_as_a_graphql_variable():
    """The public endpoint refuses inline arguments."""
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_PUBLIC_URL, status=200, json=DETAIL_RESPONSE)
        await _client(mocker).async_get_public_detail("0000000000000000000001")
        _method, _url, data, _headers = mocker.mock_calls[0]

    assert data["variables"] == {"id": "0000000000000000000001"}


async def test_public_detail_returns_none_for_an_unscanned_parcel():
    with mock_aiohttp_client() as mocker:
        mocker.post(
            GRAPHQL_PUBLIC_URL, status=200, json={"data": {"einzelsendung": None}}
        )
        assert await _client(mocker).async_get_public_detail("0000009") is None


async def test_public_detail_returns_none_when_post_rejects_the_code():
    """The code came from Post's own list, so a rejection is schema drift."""
    with mock_aiohttp_client() as mocker:
        mocker.post(
            GRAPHQL_PUBLIC_URL,
            status=400,
            json={"errors": [{"message": "invalid identity code"}]},
        )
        assert await _client(mocker).async_get_public_detail("0000009") is None


async def test_public_detail_needs_no_token():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_PUBLIC_URL, status=200, json=DETAIL_RESPONSE)
        auth = _auth()
        client = PostAtApiClient(make_mock_session(mocker), auth)
        await client.async_get_public_detail("0000000000000000000001")

    auth.async_get_token.assert_not_awaited()


async def test_public_detail_never_requests_an_address():
    with mock_aiohttp_client() as mocker:
        mocker.post(GRAPHQL_PUBLIC_URL, status=200, json=DETAIL_RESPONSE)
        await _client(mocker).async_get_public_detail("0000000000000000000001")
        _method, _url, data, _headers = mocker.mock_calls[0]

    query = data["query"].lower()
    for forbidden in ("recipientaddress", "consignee", "packageredirections"):
        assert forbidden not in query
