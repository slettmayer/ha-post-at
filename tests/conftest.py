"""Shared fixtures."""

import asyncio

import pytest

_OPEN_SESSIONS: list = []


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components/."""
    return


def make_mock_session(mocker):
    """Create a mocked aiohttp session that the test teardown will close.

    ``AiohttpClientMocker.create_session`` hands back a real ``ClientSession``,
    and Home Assistant's test plugin fails any test that leaves one open.
    """
    session = mocker.create_session(asyncio.get_running_loop())
    _OPEN_SESSIONS.append(session)
    return session


@pytest.fixture(autouse=True)
async def close_mock_sessions():
    """Close every session handed out by :func:`make_mock_session`."""
    yield
    while _OPEN_SESSIONS:
        await _OPEN_SESSIONS.pop().close()
