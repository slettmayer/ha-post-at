"""The user and reauth flows."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.post_at.auth import (
    PostAtAuthError,
    PostAtInvalidCredentials,
    SsoCookie,
)
from custom_components.post_at.const import (
    CONF_EMAIL,
    CONF_LANGUAGE,
    CONF_SSO_COOKIE_NAME,
    CONF_SSO_COOKIE_VALUE,
    DOMAIN,
    LANGUAGE_DE,
    LANGUAGE_EN,
    default_language,
)

USER_INPUT = {"email": "user@example.invalid", "password": "secret"}
COOKIE = SsoCookie("x-ms-cpim-sso:t_0", "VALUE")


def _patch_login(cookie=COOKIE, side_effect=None):
    return patch(
        "custom_components.post_at.config_flow.PostAtSession.async_login",
        AsyncMock(return_value=cookie, side_effect=side_effect),
    )


def _patch_setup():
    return patch("custom_components.post_at.async_setup_entry", return_value=True)


async def test_user_flow_shows_a_form_first(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_EMAIL: "user@example.invalid",
        CONF_SSO_COOKIE_NAME: "x-ms-cpim-sso:t_0",
        CONF_SSO_COOKIE_VALUE: "VALUE",
    }


async def test_user_flow_never_stores_the_password(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert "password" not in result["data"]
    assert "secret" not in str(result["data"])


async def test_invalid_credentials_show_an_error(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login(side_effect=PostAtInvalidCredentials("no")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_a_broken_journey_shows_cannot_connect(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login(side_effect=PostAtAuthError("page moved")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_an_unexpected_error_shows_unknown(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login(side_effect=RuntimeError("???")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["errors"] == {"base": "unknown"}


async def test_an_error_lets_the_user_try_again(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login(side_effect=PostAtInvalidCredentials("no")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    with _patch_login(), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_account_cannot_be_added_twice(hass):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        data={CONF_EMAIL: "user@example.invalid"},
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_the_account_is_matched_case_insensitively(hass):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        data={CONF_EMAIL: "user@example.invalid"},
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with _patch_login():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": "User@Example.Invalid", "password": "s"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_the_cookie(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        data={
            CONF_EMAIL: "user@example.invalid",
            CONF_SSO_COOKIE_NAME: "x-ms-cpim-sso:t_0",
            CONF_SSO_COOKIE_VALUE: "OLD",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with _patch_login(SsoCookie("x-ms-cpim-sso:t_0", "NEW")), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "secret"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_SSO_COOKIE_VALUE] == "NEW"


async def test_reauth_only_asks_for_the_password(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        data={
            CONF_EMAIL: "user@example.invalid",
            CONF_SSO_COOKIE_NAME: "x-ms-cpim-sso:t_0",
            CONF_SSO_COOKIE_VALUE: "OLD",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    assert set(result["data_schema"].schema) == {"password"}


async def test_reauth_rejects_a_wrong_password(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        data={
            CONF_EMAIL: "user@example.invalid",
            CONF_SSO_COOKIE_NAME: "x-ms-cpim-sso:t_0",
            CONF_SSO_COOKIE_VALUE: "OLD",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    with _patch_login(side_effect=PostAtInvalidCredentials("no")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_SSO_COOKIE_VALUE] == "OLD"


async def test_sign_in_uses_a_cookie_less_session(hass):
    """aiohttp's CookieJar mangles B2C's cookies; auth.py handles them itself."""
    import aiohttp

    seen = {}

    def _capture(hass_arg, **kwargs):
        seen.update(kwargs)
        return AsyncMock()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with (
        patch(
            "custom_components.post_at.config_flow.async_create_clientsession",
            side_effect=_capture,
        ),
        _patch_login(),
        _patch_setup(),
    ):
        await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert isinstance(seen.get("cookie_jar"), aiohttp.DummyCookieJar)


async def test_default_language_is_german_only_for_a_german_home_assistant():
    assert default_language("de") == LANGUAGE_DE
    assert default_language("de-AT") == LANGUAGE_DE
    assert default_language("en") == LANGUAGE_EN
    assert default_language("fr") == LANGUAGE_EN
    assert default_language(None) == LANGUAGE_EN


async def test_options_flow_offers_the_language_picker(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_EMAIL: "u@example.invalid"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_stores_the_chosen_language(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_EMAIL: "u@example.invalid"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_LANGUAGE: LANGUAGE_DE}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LANGUAGE] == LANGUAGE_DE


async def test_options_flow_defaults_to_the_home_assistant_language(hass):
    """An unconfigured entry shows the derived default, not a blank field."""
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_EMAIL: "u@example.invalid"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"]({})

    assert schema[CONF_LANGUAGE] == LANGUAGE_DE


async def test_reauth_leaves_the_reload_to_the_update_listener(hass):
    """The flow must not schedule a reload of its own.

    The entry already carries an update listener that reloads on any change.
    A reload scheduled by the flow on top of that is the duplicate Home
    Assistant deprecates today and rejects in 2026.12.0 -- and
    `async_update_reload_and_abort` schedules one whenever the entry changed,
    which a successful reauth always does, whatever
    `reload_even_if_entry_is_unchanged` is set to.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.invalid",
        data={
            CONF_EMAIL: "user@example.invalid",
            CONF_SSO_COOKIE_NAME: "x-ms-cpim-sso:t_0",
            CONF_SSO_COOKIE_VALUE: "OLD",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    with (
        _patch_login(SsoCookie("x-ms-cpim-sso:t_0", "NEW")),
        _patch_setup(),
        patch.object(hass.config_entries, "async_schedule_reload") as scheduled,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "secret"}
        )

    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_SSO_COOKIE_VALUE] == "NEW"
    assert scheduled.call_count == 0
