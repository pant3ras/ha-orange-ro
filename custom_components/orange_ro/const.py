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

# The data itself refreshes slowly (Cronos usage has a ~24h delay), but the poll
# also doubles as a session KEEP-ALIVE: Orange's session has a short idle window
# and hands back rotated cookies (which the API client absorbs). Polling every
# few minutes keeps those cookies fresh so the session doesn't die between polls.
DEFAULT_SCAN_INTERVAL = timedelta(minutes=4)

# A real-browser User-Agent. Orange's edge (F5 / reCAPTCHA) is friendlier to
# requests that look like the browser the cookie was minted in.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Sentinel Orange uses in Cronos resources to mean "unlimited".
UNLIMITED = "-1"
