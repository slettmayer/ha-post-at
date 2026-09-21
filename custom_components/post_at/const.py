"""Constants for the Österreichische Post account integration."""

from __future__ import annotations

from enum import StrEnum

DOMAIN = "post_at"
MANUFACTURER = "Österreichische Post AG"
ATTRIBUTION = "Data provided by Österreichische Post AG"


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
