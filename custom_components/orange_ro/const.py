"""Constants for the Orange Romania integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "orange_ro"

# Config entry keys
CONF_COOKIE = "cookie"
CONF_AUTH_METHOD = "auth_method"

# Authentication methods
AUTH_PASSWORD = "password"
AUTH_COOKIE = "cookie"

# Base of the My Orange JSON API (same origin the web dashboard calls).
API_BASE = "https://www.orange.ro/myaccount/api"

# How often to poll Orange. The portal data (usage, invoices) refreshes slowly
# — Cronos usage is documented as having a ~24h delay — so a long interval is
# both kind to Orange and perfectly adequate.
DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)

# A real-browser User-Agent. Orange's edge (F5 / reCAPTCHA) is friendlier to
# requests that look like the browser the cookie was minted in.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Sentinel Orange uses in Cronos resources to mean "unlimited".
UNLIMITED = "-1"
