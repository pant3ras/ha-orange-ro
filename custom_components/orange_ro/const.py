"""Constants for the Orange Romania integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "orange_ro"

# Config entry keys
CONF_COOKIE = "cookie"
CONF_AUTH_METHOD = "auth_method"
CONF_REFRESH_TOKEN = "refresh_token"

# Authentication methods
AUTH_PASSWORD = "password"
AUTH_COOKIE = "cookie"

# -- Mobile OAuth (MyOrange Android app) ----------------------------------- #
# The app authenticates against Orange's OAuth2 token endpoint with the app's
# built-in client credentials (Basic auth) and a password grant, then keeps a
# refresh token for silent renewal. No cookies, no reCAPTCHA, no 2FA — this is
# what makes the session persist indefinitely.
# Approach + client credentials adapted from HAForgeLabs/utilitati_romania (MIT).
OAUTH_BASE = "https://www.orange.ro"
ENDPOINT_TOKEN = "/accounts/token"
ENDPOINT_USER_INFO = "/accounts/v3/userInfo"
ENDPOINT_SUBSCRIBERS = "/myaccount/api/v5/subscribers"
ENDPOINT_INVOICE_INFO = "/myaccount/api/v5/invoice/{profile_id}/{msisdn}/invoiceInfo"
ENDPOINT_INVOICE_HISTORY = "/myaccount/api/v5/invoice/history"

OAUTH_CLIENT_ID = "07f501ee-3d7f-4eed-848c-658be314219c"
OAUTH_CLIENT_SECRET = "cDlicFa9aaRETjgU9tDk6azeyUaBMAheQTfS"
OAUTH_SCOPE = (
    "oauth.userinfo.extended myaccountb2c.access asyncchat.read "
    "eshopb2c.place_order eshopb2c.read_offers openid"
)
APP_USER_AGENT = "myorange_android okhttp/4.12.0"
APP_VERSION = "10.10.11"

# Rich per-line / loyalty data lives only in the older web API. We try these
# with the OAuth bearer token (best effort — they populate the extra sensors
# if the gateway accepts the mobile token, otherwise those sensors go away).
API_BASE_V4 = "https://www.orange.ro/myaccount/api"

# OAuth tokens refresh silently, so we no longer poll as a keep-alive. Cronos
# usage updates ~daily; hourly is plenty.
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

# A real-browser User-Agent for the legacy web (v4) endpoints.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Sentinel Orange uses in Cronos resources to mean "unlimited".
UNLIMITED = "-1"
