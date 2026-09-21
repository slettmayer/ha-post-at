"""Constants for the Österreichische Post account integration."""

from __future__ import annotations

from enum import StrEnum
from zoneinfo import ZoneInfo

from homeassistant.const import Platform

DOMAIN = "post_at"
MANUFACTURER = "Österreichische Post AG"
ATTRIBUTION = "Data provided by Österreichische Post AG"

PLATFORMS = [Platform.SENSOR]


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    Deliberately identical to the vocabulary published by the
    ha-parcel-integrations family, so community parcel cards and cross-carrier
    automations work against this integration unchanged.
    """

    REGISTERED = "registered"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    AT_PICKUP_POINT = "at_pickup_point"
    DELIVERED = "delivered"
    RETURNING = "returning"
    PROBLEM = "problem"
    UNKNOWN = "unknown"


# --- Azure AD B2C ------------------------------------------------------------
#
# Every value here is public configuration: it appears in any browser's network
# tab on post.at. None of it is a secret.
#
# Post's SPA client is registered implicit-only. The authorization-code grant
# fails with AADB2C90085 with and without PKCE, in a browser and headless, so
# no refresh token can ever be obtained -- hence the SSO cookie in auth.py.
B2C_HOST = "https://login.post.at"
B2C_TENANT = "f098c632-5a55-45ba-9bf4-c13870157cf1"
B2C_POLICY = "b2c_1a_signup_signin"
B2C_CLIENT_ID = "c02d3813-d4b9-40a1-9db9-09e34cb9c2e1"
B2C_REDIRECT_URI = "https://www.post.at"
B2C_API_SCOPE = "https://login.post.at/sendungenapi-prod/Sendungen.All"
B2C_SCOPE = f"{B2C_API_SCOPE} openid profile"

# B2C names its SSO cookie `x-ms-cpim-sso:<tenant>_<n>`; the tenant segment is
# not stable enough to hardcode, so match on the prefix.
SSO_COOKIE_PREFIX = "x-ms-cpim-sso"

# Renew a little before the hour is up, so a poll never races the expiry.
TOKEN_EXPIRY_SKEW_SECONDS = 300

CONF_EMAIL = "email"
CONF_SSO_COOKIE_NAME = "sso_cookie_name"
CONF_SSO_COOKIE_VALUE = "sso_cookie_value"


# --- Language ----------------------------------------------------------------
#
# Post localises its API on the `Accept-Language` request header, and offers
# exactly two languages. Anything that is not an `en` prefix -- `de-AT`, `fr`,
# a malformed tag, or no header at all -- is served German, so the header has
# to be sent explicitly or a fully English Home Assistant still shows
# "Logistikzentrum Kärnten, AT".
#
# Localised: estimatedDeliveryDateText, trackingState, trackingDesc,
# eventPlaceName. Not localised: `text` is always German and `textEn` always
# English, whatever the header says -- see `parcels._event_text`.
CONF_LANGUAGE = "language"
LANGUAGE_DE = "de"
LANGUAGE_EN = "en"
LANGUAGES = [LANGUAGE_DE, LANGUAGE_EN]


def default_language(hass_language: str | None) -> str:
    """Pick the default for a Home Assistant configured in ``hass_language``.

    German only for a German Home Assistant; English for everything else,
    because English is the more useful of Post's two languages to a reader who
    has chosen neither.
    """
    tag = str(hass_language or "").casefold()
    return LANGUAGE_DE if tag.startswith(LANGUAGE_DE) else LANGUAGE_EN


# --- GraphQL -----------------------------------------------------------------
#
# Two endpoints, split by role. The authenticated one is used ONLY to discover
# which tracking numbers the account holds; it is undocumented and
# unsanctioned. Everything else comes from the public keyless endpoint, which
# has introspection enabled, is what the consumer tracking page uses, and is
# the only one known to return `trackingStateKey`.
GRAPHQL_AUTHENTICATED_URL = "https://api.post.at/sendungen/sv/graphqlAuthenticated"
GRAPHQL_PUBLIC_URL = "https://api.post.at/sendungen/sv/graphqlPublic"

# Deep links into the consumer site. These two follow *opposite* conventions,
# verified against the live site -- do not "tidy" them into one shape:
#
#   /s/sendungsdetails?snr=...     200   /en/... and /de/... both 404
#   /en/s/item-overview            307   /s/... and /de/... both 404
#
# The 307 on item-overview is the language hop; it sets `postat#lang=en` and
# lands on the account's shipment list.
TRACKING_URL = "https://www.post.at/s/sendungsdetails?snr={tracking_code}"
ACCOUNT_URL = "https://www.post.at/en/s/item-overview"

LIST_ELEMENT_COUNT = 25

# Only `sendungsnummer` and `bezeichnung` are consumed; the rest is requested
# so a poll still degrades to something useful when the public endpoint does
# not yet know a freshly created parcel.
LIST_QUERY = f"""
query {{
  sendungen: sendungen(postProcessingOptions: {{
    elementCount: {LIST_ELEMENT_COUNT}, sortByDate: DESCENDING, paging: RECEIVE
  }}) {{
    totalSendungen
    empfangsSendungen
    sendungen {{
      sendungsnummer
      bezeichnung
      status
      isRecipient
    }}
  }}
}}
"""

# The public endpoint accepts only the variable form; inline arguments are
# refused. `recipientAddress` is deliberately never requested.
DETAIL_QUERY = """
query ShipmentPublic($id: String!) {
  einzelsendung(sendungsnummer: $id) {
    status weight branchkey
    estimatedDeliveryDate estimatedDeliveryDateText
    estimatedDelivery { startDate endDate startTime endTime }
    dimensions { height length width }
    shipper { name postalCode city country }
    sendungsEvents {
      trackingStateKey trackingState trackingDesc text textEn timestamp
      eventcountry eventpostalcode eventPlaceName
    }
  }
}
"""


# Post's delivery estimates are Austrian calendar days, whatever timezone Home
# Assistant runs in, so a value that arrives without a time is read in Vienna
# rather than in the user's own zone: a parcel is delivered on the Austrian
# Tuesday regardless of where the dashboard is being looked at.
POST_TIMEZONE = ZoneInfo("Europe/Vienna")

# --- Polling -----------------------------------------------------------------
#
# Short while anything is moving, long when nothing is. Not user-configurable:
# a parcel feed has one sensible cadence and an option would only invite people
# to hammer an undocumented endpoint.
ACTIVE_INTERVAL_MINUTES = 15
IDLE_INTERVAL_MINUTES = 60

# --- Events ------------------------------------------------------------------
#
# Automations key on these rather than on per-parcel entities: one automation
# then covers every parcel, present and future, with nothing to update when a
# parcel arrives.
EVENT_PARCEL_REGISTERED = "post_at_parcel_registered"
EVENT_PARCEL_STATUS_CHANGED = "post_at_parcel_status_changed"
EVENT_PARCEL_DELIVERED = "post_at_parcel_delivered"
EVENT_PARCEL_DELIVERY_TIME_CHANGED = "post_at_parcel_delivery_time_changed"

# A parcel can turn up on the account list already delivered -- on the 60
# minute idle cadence that is the ordinary case for a single surprise parcel,
# and `delivered` has to fire or "tell me when a parcel arrives" misses it.
# But Post also surfaces old deliveries late, so only a recent arrival is
# announced: nobody wants to be told about last month's parcel.
FIRST_SIGHT_DELIVERED_MAX_AGE_HOURS = 24


# How long a delivered parcel stays on the summary sensor. Post's account list
# reaches months back, and every entry is rewritten into the recorder on each
# poll -- 25 parcels is roughly 15 KB, against Home Assistant's ~16 KB
# practical ceiling for a state attribute.
DELIVERED_RETENTION_DAYS = 7
