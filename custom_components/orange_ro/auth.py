"""Username/password login for My Orange (best-effort).

This replicates the browser's client-side credential encryption and walks the
OAuth2 authorization-code flow to obtain an authenticated session, then returns
the resulting ``Cookie`` header for the API client to reuse.

IMPORTANT: the login form also submits a reCAPTCHA Enterprise v3 token that is
generated in a real browser and validated server-side. A headless client cannot
mint a valid token, so if Orange *hard-enforces* the score this login will fail
with ``OrangeRecaptchaError`` and the user must fall back to cookie auth. We send
an empty token and let the server decide.

Encryption scheme (from accounts/Scripts/utils/cryptoUtils.js):
  * fetch JWKS, pick the RSA key whose ``kid`` matches the login page's
    ``data-expected-kid`` (alg RSA-OAEP-256, use "enc")
  * keyMaterial = 48 random bytes; aesKey = bytes[0:16], hmacKey = bytes[16:48]
  * iv = 16 random bytes
  * ciphertext = AES-128-CBC(PKCS7) over JSON {username,password,nonce,ts,origin}
  * mac = HMAC-SHA256(hmacKey, iv || ciphertext)
  * encPayload = base64url(iv || ciphertext || mac)
  * encKey     = base64url(RSA-OAEP-256(pub, keyMaterial))
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone

from aiohttp import ClientError, ClientSession
from cryptography.hazmat.primitives import hashes, hmac, padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .api import OrangeAuthError, OrangeError
from .const import USER_AGENT

_LOGGER = logging.getLogger(__name__)

ORIGIN = "https://www.orange.ro"
ENTRY_URL = f"{ORIGIN}/myaccount/reshape/"
JWKS_URL = f"{ORIGIN}/accounts/.well-known/v3/jwks"

_KID_RE = re.compile(r'data-expected-kid="([^"]+)"')
_TOKEN_RE = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"'
)
_LOGIN_ACTION_RE = re.compile(r"/accounts/login-user\?[^\"'\s]+")


class OrangeRecaptchaError(OrangeAuthError):
    """Login was rejected in a way consistent with reCAPTCHA enforcement."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_to_int(value: str) -> int:
    padded = value + "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def _select_jwk(jwks: dict, expected_kid: str | None) -> dict:
    keys = [
        k
        for k in (jwks.get("keys") or [])
        if (k.get("kty") or "").upper() == "RSA"
        and (not k.get("use") or k.get("use") == "enc")
        and (not k.get("alg") or k.get("alg") == "RSA-OAEP-256")
        and k.get("n")
        and k.get("e")
        and k.get("kid")
    ]
    if not keys:
        raise OrangeError("No suitable RSA encryption key in JWKS")
    if expected_kid:
        for k in keys:
            if k["kid"] == expected_kid:
                return k
        raise OrangeError("Pinned encryption key (kid) not found in JWKS")
    if len(keys) == 1:
        return keys[0]
    raise OrangeError("Multiple JWKS keys but no pinned kid to choose")


def _encrypt_credentials(jwk: dict, username: str, password: str) -> dict[str, str]:
    """Return {encPayload, encKey, encKid} for the login form."""
    public_key = RSAPublicNumbers(
        e=_b64url_to_int(jwk["e"]), n=_b64url_to_int(jwk["n"])
    ).public_key()

    payload = json.dumps(
        {
            "username": username,
            "password": password,
            "nonce": _b64url(os.urandom(16)),
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "origin": ORIGIN,
        },
        separators=(",", ":"),
    ).encode("utf-8")

    key_material = os.urandom(48)
    aes_key, hmac_key = key_material[:16], key_material[16:]
    iv = os.urandom(16)

    padder = sym_padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(payload) + padder.finalize()
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    mac = hmac.HMAC(hmac_key, hashes.SHA256())
    mac.update(iv + ciphertext)
    tag = mac.finalize()

    enc_key = public_key.encrypt(
        key_material,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    return {
        "encPayload": _b64url(iv + ciphertext + tag),
        "encKey": _b64url(enc_key),
        "encKid": jwk["kid"],
    }


class OrangeLoginClient:
    """Performs the full browser-equivalent login and yields a Cookie header."""

    def __init__(self, session: ClientSession) -> None:
        # The session MUST own an isolated cookie jar (use
        # homeassistant.helpers.aiohttp_client.async_create_clientsession).
        self._session = session

    def _headers(self, referer: str | None = None) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT}
        if referer:
            headers["Referer"] = referer
        return headers

    async def async_login(self, username: str, password: str) -> str:
        try:
            return await self._login(username, password)
        except ClientError as err:
            raise OrangeError(f"Network error during login: {err}") from err

    async def _login(self, username: str, password: str) -> str:
        # Start from a clean jar so a previous (expired) attempt can't bleed
        # stale cookies into this one.
        self._session.cookie_jar.clear()

        # 1) Walk the OAuth redirects to the rendered login page.
        async with self._session.get(
            ENTRY_URL, headers=self._headers(), allow_redirects=True
        ) as resp:
            login_url = str(resp.url)
            html = await resp.text()

        token_match = _TOKEN_RE.search(html)
        if not token_match:
            raise OrangeError("Could not find anti-forgery token on login page")
        verification_token = token_match.group(1)

        kid_match = _KID_RE.search(html)
        expected_kid = kid_match.group(1) if kid_match else None

        action_match = _LOGIN_ACTION_RE.search(html)
        post_url = (
            f"{ORIGIN}{action_match.group(0)}" if action_match else login_url
        )

        # 2) Fetch the public key and encrypt the credentials.
        async with self._session.get(
            JWKS_URL, headers=self._headers(login_url)
        ) as resp:
            if resp.status != 200:
                raise OrangeError(f"JWKS endpoint returned HTTP {resp.status}")
            jwks = await resp.json(content_type=None)

        enc = _encrypt_credentials(_select_jwk(jwks, expected_kid), username, password)

        # 3) Submit the login. We cannot produce a valid reCAPTCHA token, so it
        #    is sent empty; the server may accept (advisory score) or reject.
        form = {
            "__RequestVerificationToken": verification_token,
            "UserDirectory": "1",
            "encPayload": enc["encPayload"],
            "encKey": enc["encKey"],
            "encKid": enc["encKid"],
            "recaptchaToken": "",
            "recaptchaAction": "login",
        }
        async with self._session.post(
            post_url,
            data=form,
            headers=self._headers(login_url),
            allow_redirects=True,
        ) as resp:
            final_url = str(resp.url)
            body = await resp.text()

        # 4) Success lands back inside /myaccount; a bounce back to the login
        #    page means rejection (bad creds or, most likely, reCAPTCHA).
        if "login-user" in final_url or "/accounts/" in final_url:
            if "recaptcha" in body.lower() or "captcha" in body.lower():
                raise OrangeRecaptchaError(
                    "Login rejected — reCAPTCHA could not be satisfied headlessly. "
                    "Use the cookie method instead."
                )
            raise OrangeAuthError(
                "Login rejected. Check the username/password, or use the cookie "
                "method (the reCAPTCHA gate may be blocking automated login)."
            )

        # 5) Build the Cookie header from the jar for the API client to replay.
        cookie = self._cookie_header()
        if not cookie:
            raise OrangeAuthError("Login produced no session cookies")
        return cookie

    def _cookie_header(self) -> str:
        pairs = []
        for cookie in self._session.cookie_jar:
            pairs.append(f"{cookie.key}={cookie.value}")
        return "; ".join(pairs)
