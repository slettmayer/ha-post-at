"""The B2C sign-in journey and silent renewal."""

import json
import re

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    mock_aiohttp_client,
)

from custom_components.post_at.auth import (
    PostAtAuthError,
    PostAtAuthExpired,
    PostAtInvalidCredentials,
    PostAtSession,
    SsoCookie,
)
from custom_components.post_at.const import B2C_POLICY, B2C_TENANT
from tests.conftest import make_mock_session

# Each authorize request carries a fresh state and nonce, so these have to be
# matched by pattern rather than by exact URL.
AUTHORIZE = re.compile(r"^https://login\.post\.at/.+/oauth2/v2\.0/authorize")
SELF_ASSERTED = re.compile(r"^https://login\.post\.at/.+/SelfAsserted")
CONFIRMED = re.compile(r"^https://login\.post\.at/.+/confirmed")


def signin_page(tenant: str = B2C_TENANT, policy: str = B2C_POLICY) -> str:
    """Render a B2C sign-in page carrying the injected SETTINGS blob."""
    settings = json.dumps(
        {
            "csrf": "CSRF123",
            "transId": "StateProperties=abc",
            "hosts": {"tenant": tenant, "policy": policy},
            "api": "CombinedSigninAndSignup",
        }
    )
    return (
        "<html><head><title>Sign in</title></head><body><script>"
        f"var SETTINGS = {settings};"
        "</script></body></html>"
    )


SIGNIN_PAGE = signin_page()

TOKEN_FRAGMENT = (
    "https://www.post.at#access_token=TOKEN_A&expires_in=3600"
    "&token_type=Bearer&state=xyz"
)

SSO_HEADER = {"Set-Cookie": "x-ms-cpim-sso:t_0=COOKIEVALUE; Path=/"}
CSRF_HEADER = {"Set-Cookie": "x-ms-cpim-csrf=CSRFCOOKIE; Path=/"}


def _journey(mocker, *, signin_page=SIGNIN_PAGE, self_asserted=None):
    """Register a complete, successful sign-in journey."""
    mocker.get(AUTHORIZE, status=200, text=signin_page, headers=CSRF_HEADER)
    mocker.post(
        SELF_ASSERTED,
        status=200,
        json=self_asserted or {"status": "200"},
        headers=SSO_HEADER,
    )
    mocker.get(CONFIRMED, status=302, text="", headers={"Location": TOKEN_FRAGMENT})


async def test_login_returns_the_sso_cookie():
    with mock_aiohttp_client() as mocker:
        _journey(mocker)
        auth = PostAtSession(make_mock_session(mocker))
        cookie = await auth.async_login("u@example.invalid", "pw")

    assert isinstance(cookie, SsoCookie)
    assert cookie.name == "x-ms-cpim-sso:t_0"
    assert cookie.value == "COOKIEVALUE"


async def test_login_does_not_mistake_the_csrf_cookie_for_the_session():
    """Both cookies share the x-ms-cpim prefix; only one is the session."""
    with mock_aiohttp_client() as mocker:
        _journey(mocker)
        cookie = await PostAtSession(make_mock_session(mocker)).async_login(
            "u@example.invalid", "pw"
        )

    assert "csrf" not in cookie.name


async def test_login_rejects_bad_credentials():
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=200, text=SIGNIN_PAGE)
        mocker.post(
            SELF_ASSERTED,
            status=200,
            json={"status": "400", "message": "Invalid username or password"},
        )
        with pytest.raises(PostAtInvalidCredentials):
            await PostAtSession(make_mock_session(mocker)).async_login(
                "u@example.invalid", "wrong"
            )


async def test_login_surfaces_a_restyled_signin_page():
    """No SETTINGS blob means Post changed the page; fail loudly, not silently."""
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=200, text="<html><title>Other</title></html>")
        with pytest.raises(PostAtAuthError):
            await PostAtSession(make_mock_session(mocker)).async_login(
                "u@example.invalid", "pw"
            )


async def test_login_surfaces_a_non_json_selfasserted_reply():
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=200, text=SIGNIN_PAGE)
        mocker.post(SELF_ASSERTED, status=200, text="<html>nope</html>")
        with pytest.raises(PostAtAuthError):
            await PostAtSession(make_mock_session(mocker)).async_login(
                "u@example.invalid", "pw"
            )


async def test_login_fails_when_no_sso_cookie_is_set():
    """A journey that completes without a cookie leaves nothing to persist."""
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=200, text=SIGNIN_PAGE)
        mocker.post(SELF_ASSERTED, status=200, json={"status": "200"})
        mocker.get(CONFIRMED, status=302, text="", headers={"Location": TOKEN_FRAGMENT})
        with pytest.raises(PostAtAuthError):
            await PostAtSession(make_mock_session(mocker)).async_login(
                "u@example.invalid", "pw"
            )


async def test_login_reads_tenant_and_policy_from_the_page():
    """A policy rename must not break the login."""
    page = signin_page(policy="b2c_1a_renamed")
    with mock_aiohttp_client() as mocker:
        _journey(mocker, signin_page=page)
        await PostAtSession(make_mock_session(mocker)).async_login(
            "u@example.invalid", "pw"
        )
        posted = [str(c[1]) for c in mocker.mock_calls if c[0] == "POST"]

    assert posted and "b2c_1a_renamed" in posted[0]


async def test_login_never_puts_the_password_in_a_url():
    with mock_aiohttp_client() as mocker:
        _journey(mocker)
        await PostAtSession(make_mock_session(mocker)).async_login(
            "u@example.invalid", "hunter2"
        )
        urls = [str(call[1]) for call in mocker.mock_calls]

    assert not any("hunter2" in url for url in urls)


async def test_login_asks_for_a_persistent_session():
    with mock_aiohttp_client() as mocker:
        _journey(mocker)
        await PostAtSession(make_mock_session(mocker)).async_login(
            "u@example.invalid", "pw"
        )
        urls = [str(call[1]) for call in mocker.mock_calls]

    confirmed = [url for url in urls if "confirmed" in url]
    assert confirmed and "rememberMe=true" in confirmed[0]


async def test_get_token_renews_silently_from_the_cookie():
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=302, text="", headers={"Location": TOKEN_FRAGMENT})
        auth = PostAtSession(
            make_mock_session(mocker), SsoCookie("x-ms-cpim-sso:t_0", "V")
        )
        assert await auth.async_get_token() == "TOKEN_A"


async def test_get_token_sends_the_stored_cookie_and_prompt_none():
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=302, text="", headers={"Location": TOKEN_FRAGMENT})
        auth = PostAtSession(
            make_mock_session(mocker), SsoCookie("x-ms-cpim-sso:t_0", "V")
        )
        await auth.async_get_token()
        method, url, _data, headers = mocker.mock_calls[0]

    assert method == "GET"
    assert "prompt=none" in str(url)
    assert headers["cookie"] == "x-ms-cpim-sso:t_0=V"


async def test_get_token_is_cached_until_near_expiry():
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=302, text="", headers={"Location": TOKEN_FRAGMENT})
        auth = PostAtSession(
            make_mock_session(mocker), SsoCookie("x-ms-cpim-sso:t_0", "V")
        )
        first = await auth.async_get_token()
        second = await auth.async_get_token()

    assert first == second
    assert len(mocker.mock_calls) == 1


async def test_get_token_raises_expired_when_prompt_none_fails():
    with mock_aiohttp_client() as mocker:
        mocker.get(
            AUTHORIZE,
            status=302,
            text="",
            headers={
                "Location": "https://www.post.at#error=login_required"
                "&error_description=AADB2C90077"
            },
        )
        auth = PostAtSession(
            make_mock_session(mocker), SsoCookie("x-ms-cpim-sso:t_0", "V")
        )
        with pytest.raises(PostAtAuthExpired):
            await auth.async_get_token()


async def test_get_token_raises_expired_when_there_is_no_redirect():
    with mock_aiohttp_client() as mocker:
        mocker.get(AUTHORIZE, status=200, text="<html>sign in again</html>")
        auth = PostAtSession(
            make_mock_session(mocker), SsoCookie("x-ms-cpim-sso:t_0", "V")
        )
        with pytest.raises(PostAtAuthExpired):
            await auth.async_get_token()


async def test_get_token_recovers_a_token_from_a_body_fragment():
    """Some B2C responses answer with an auto-posting page instead of a 302."""
    with mock_aiohttp_client() as mocker:
        mocker.get(
            AUTHORIZE,
            status=200,
            text=f'<html><body><a href="{TOKEN_FRAGMENT}">go</a></body></html>',
        )
        auth = PostAtSession(
            make_mock_session(mocker), SsoCookie("x-ms-cpim-sso:t_0", "V")
        )
        assert await auth.async_get_token() == "TOKEN_A"


async def test_get_token_without_a_cookie_raises_expired():
    with mock_aiohttp_client() as mocker, pytest.raises(PostAtAuthExpired):
        await PostAtSession(make_mock_session(mocker)).async_get_token()


async def test_cookie_property_exposes_what_to_persist():
    with mock_aiohttp_client() as mocker:
        auth = PostAtSession(make_mock_session(mocker), SsoCookie("n", "v"))
        assert auth.cookie == SsoCookie("n", "v")
