# Österreichische Post (Account)

> Home Assistant custom integration that signs in to a private post.at account
> and reports the parcels addressed to it. No external collector service.

> **Editing this guide:** `AGENTS.md` is the single source of truth for project
> context, read by all AI coding agents and humans. Keep it concise.

## Quick Reference

- **Build**: none — pure Python custom component distributed via HACS
- **Run**: load into Home Assistant (HACS custom repository, or copy `custom_components/post_at/`)
- **Test**: `python -m pytest tests/ -q`
- **Lint**: `ruff check . --fix && ruff format .`
- **Design**: [spec](docs/superpowers/specs/2026-09-21-ha-post-at-design.md) · [plan](docs/superpowers/plans/2026-09-21-ha-post-at.md)

## Hard rules

These are not style preferences. Breaking one is a bug.

1. **The account password is never persisted.** `config_flow.py` uses it once to
   run the B2C sign-in journey and discards it. The only durable credential is
   the B2C SSO cookie in the config entry.
2. **Address fields are never requested or exposed.** `recipientAddress` is the
   user's own name and street on every parcel. It must not reach the state
   machine, the recorder, or a diagnostics download.
3. **An unmapped tracking state reports `unknown`.** Never guess. A wrong
   `delivered` is far more damaging than an honest `unknown`.
4. **Fixtures contain no real data.** No real tracking numbers, names or
   addresses.

## Architecture

Two endpoints, split by role:

- `graphqlAuthenticated` — used **only** to discover which tracking numbers the
  account holds. Undocumented, unsanctioned, Bearer-authenticated.
- `graphqlPublic` — keyless, introspectable, used for **all** per-parcel detail.
  It is the only one known to return `trackingStateKey`.

Post's SPA client is registered implicit-only: the authorization-code grant
fails with `AADB2C90085` with and without PKCE, so **no refresh token exists**.
`auth.py` therefore persists the B2C SSO cookie and exchanges it for a one-hour
access token via `prompt=none`.

| File | Responsibility |
| --- | --- |
| `const.py` | Endpoints, B2C identifiers, intervals, `ParcelStatus`, event names, GraphQL documents |
| `status.py` | `trackingStateKey` normalisation and the `TrackingState` table |
| `auth.py` | Sign-in journey, SSO cookie, silent renewal |
| `api.py` | The two GraphQL surfaces |
| `models.py` / `parcels.py` | The `Parcel` dataclass and its normalisation |
| `coordinator.py` | Polling, dynamic interval, 401 retry, events |
| `config_flow.py` | User and reauth flows |
| `sensor.py` / `entity.py` | Three sensors on one service device |
| `diagnostics.py` | Redacted diagnostics |

`status.py`, `models.py`, `parcels.py`, `auth.py` and `api.py` stay free of
`homeassistant` imports, so the client could be extracted to PyPI later and so
they test without a running hass.

## Conventions

- Classes use the `PostAt*` prefix; private helpers are `_`-prefixed.
- Every endpoint, identifier and interval lives in `const.py` — never inline.
- One stable summary sensor, not one entity per parcel: a dashboard binds to it
  for years, whereas per-parcel entity ids churn as parcels come and go.
  Automations use the bus events instead.
- Ruff-enforced: 4 spaces, double quotes, line length 88, rule set
  `E,W,F,I,UP,B,SIM,C4,RUF`.

## Status vocabulary

Mapped on `trackingStateKey`, never on the coarse `status` field (`AN`/`ZU`,
which cannot express "out for delivery") and never on `reasontypecode` (which
no consumer has managed to map). The table in `status.py` is Post's own
`TrackingState` enum, lifted from Post's app by the MIT-licensed
[ha-oesterreichische-post](https://github.com/ha-parcel-integrations/ha-oesterreichische-post)
and reproduced with thanks.

## Structural risks

- **The sign-in journey is HTML-shaped.** Post restyling their B2C pages breaks
  `SelfAsserted` parsing. Tenant and policy are read from the page's own
  `SETTINGS.hosts` to soften this; the page structure itself cannot be defended.
- **The SSO cookie's lifetime is unverified.** If it proves short-lived, users
  re-authenticate often and `auth.py` needs rethinking.
- **`graphqlAuthenticated` is undocumented and unsanctioned.** It may change or
  be gated without notice. This is why enrichment lives on the public endpoint.
- **Weight and dimension units are assumed** (kg and cm), inherited unverified
  from the sibling integration.
- `hacs/action@main` and hassfest `@master` are floating CI refs.
