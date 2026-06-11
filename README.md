<p align="center">
  <img src="logo.svg" alt="Orange" width="96" height="96">
</p>

# Orange Romania for Home Assistant

A custom integration that pulls account data from **My Orange** (`orange.ro/myaccount`)
into Home Assistant: mobile usage, invoices/balance, Thank You points, subscription
and contract details — for every line on your account.

> Unofficial. Not affiliated with or endorsed by Orange. It uses the same private
> JSON API that the My Orange web dashboard calls, authenticated with your own
> browser session cookie.

## What you get

**Per account profile** (one device):
- Thank You points + point value
- Balance due, last bill amount, last/next/due bill dates
- Installments count
- Invoices (count + recent transaction history as attributes)

**Per phone line** (one device each):
- Subscription name, monthly fee, line status
- Phone-upgrade-eligible date, activation date, phone credit
- Resources valid-until date (with the full resource list as attributes)
- One sensor per metered resource (data GB / international minutes / SMS remaining);
  unlimited resources are listed as attributes on *Resources valid until*

## Authentication

When you add the integration you choose one of two methods:

### 1. Username & password (convenient, best-effort)
Enter your My Orange credentials. The integration reproduces Orange's client-side
credential encryption (RSA-OAEP-256 over an AES-128-CBC + HMAC payload) and walks the
OAuth2 login flow. If it works, **the session is refreshed automatically** when it
expires — no manual steps ever again.

> ⚠️ Orange's login is also guarded by **reCAPTCHA Enterprise**, which a non-browser
> client cannot satisfy. If Orange hard-enforces it, this method is rejected and you'll
> see an *invalid auth* error — in that case use the cookie method below. (Credentials
> are stored in Home Assistant's config entry, same as any other integration password.)

### 2. Session cookie (most reliable)
1. In a desktop browser, log in at <https://www.orange.ro/myaccount/reshape/>.
2. Open **DevTools** (F12) → **Network** tab.
3. Reload the page. Click any request whose URL contains `myaccount/api/` (e.g. `userData`).
4. In **Headers → Request Headers**, find **`Cookie`** and copy its *entire* value.
5. Paste it into the integration's cookie field.

The cookie **expires periodically** (hours to a couple of weeks). When it does, the
entities go unavailable and Home Assistant prompts you to paste a fresh one (re-auth).

## Installation

### Via HACS (custom repository)
1. HACS → ⋮ → **Custom repositories**.
2. Add this repo URL, category **Integration**.
3. Install **Orange Romania**, then restart Home Assistant.

### Manual
Copy `custom_components/orange_ro/` into your HA `config/custom_components/` folder and
restart Home Assistant.

Then: **Settings → Devices & Services → Add Integration → Orange Romania** and pick a
method above.

## Notes & limitations
- Polls every 30 minutes. Orange's usage (Cronos) data is itself delayed ~24h, so
  more frequent polling gains nothing.
- Money: subscription fee and Thank You value are in EUR; invoice/balance figures
  are in RON (as Orange returns them).
- Read-only. The integration never performs account actions, payments, or changes.

## Credits
Brought to you by **PanTeraS**.

If you find this useful, you can [buy me a coffee ☕](https://www.buymeacoffee.com/panteras).