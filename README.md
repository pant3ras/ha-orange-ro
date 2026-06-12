![Orange Romania](https://raw.githubusercontent.com/pant3ras/ha-orange-ro/main/icon.png)

# Orange Romania for Home Assistant

A custom integration that pulls account data from **My Orange** into Home Assistant:
invoices/balance, Thank You points, subscription and contract details, and mobile
usage — for every line on your account.

> Unofficial. Not affiliated with or endorsed by Orange. It signs in the same way the
> **MyOrange mobile app** does and reads your own account data.

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

## Authentication — stays signed in

Add the integration and enter your **My Orange e-mail (or phone number) and password** —
that's it. The integration authenticates exactly like the MyOrange Android app: an
OAuth2 login that returns a **refresh token**, which it then uses to renew access
**silently, indefinitely**.

- **No cookies, no reCAPTCHA, no 2-step codes.**
- Survives restarts (the refresh token is stored in the config entry).
- You'll only ever be asked to sign in again if you change your password.

Your password is stored in Home Assistant's config entry (like any integration
credential) and is used to obtain the token.

> **How the data is sourced.** Billing (invoices, balance, due dates, subscription,
> line status) comes from Orange's mobile API and is always available. The richer
> extras (Thank You points, resources/usage, monthly fee, upgrade-eligible date,
> phone credit) come from Orange's older web API, fetched best-effort with the same
> login. If Orange's gateway declines those for the mobile token, only those extra
> sensors go unavailable — billing keeps working.

## Installation

### Via HACS (custom repository)
1. HACS → ⋮ → **Custom repositories**.
2. Add this repo URL, category **Integration**.
3. Install **Orange Romania**, then restart Home Assistant.

### Manual
Copy `custom_components/orange_ro/` into your HA `config/custom_components/` folder and
restart Home Assistant.

Then: **Settings → Devices & Services → Add Integration → Orange Romania**.

> Upgrading from an older cookie-based version? After the update, Home Assistant will
> ask you to sign in once with your e-mail and password — your existing sensors and
> history are kept.

## Notes & limitations
- Polls hourly. Orange's usage (Cronos) data is itself delayed ~24h, so more frequent
  polling gains nothing.
- Money: subscription fee and Thank You value are in EUR; invoice/balance figures are
  in RON (as Orange returns them).
- Read-only. The integration never performs account actions, payments, or changes.

## Credits

Brought to you by **PanTeraS**.

The mobile OAuth login flow is adapted from
[HAForgeLabs/utilitati_romania](https://github.com/HAForgeLabs/utilitati_romania)
(MIT) — see [`NOTICE`](NOTICE).

If you find this useful, you can [buy me a coffee ☕](https://www.buymeacoffee.com/panteras).
