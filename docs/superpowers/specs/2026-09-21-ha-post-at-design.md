# ha-post-at — Design

**Date:** 2026-09-21
**Status:** Approved design, pending implementation plan
**Domain:** `post_at`

## 1. Purpose

A Home Assistant custom integration that tracks parcels addressed to a private
Österreichische Post customer account, so that parcels appear automatically
without the user entering tracking numbers.

The user logs in once with their post.at credentials. The integration then polls
the account's shipment list and exposes it to Home Assistant, so a dashboard can
show what is currently on its way.

## 2. Non-goals

- **No external collector services.** No AfterShip, 17track, Parcel, Track123.
  The integration talks to Post directly or not at all.
- **No tracking by tracking number.** That case is already served by
  [ha-oesterreichische-post](https://github.com/ha-parcel-integrations/ha-oesterreichische-post),
  which uses Post's keyless public endpoint. This integration is only about the
  account.
- **No outbound actions.** No parcel redirection, no damage reports, no
  payments — even though the API exposes them. Read-only.
- **No per-parcel entities in v1.** See §7.

## 3. Research findings

### 3.1 No official API covers this

- Post's only public developer portal is
  [Post Business Solutions](https://www.post.at/en/g/c/developer-portal),
  offering DAiTa (document processing), Dual Delivery (e-delivery) and an
  e-signature product. No tracking.
- `portal.api.post.at`, cited by search engines as the Post developer portal,
  does not resolve (NXDOMAIN).
- `developer.post.at`, `developers.post.at` and `api-portal.post.at` return HTTP
  200 but serve the ordinary marketing site via a wildcard — no portal exists
  there.
- A tracking API exists for business customers under contract, via a sales
  representative. It covers shipments the customer *sends*, not parcels
  addressed to a private account.

There is no official surface for "the parcels currently addressed to me" at any
price. The account API is the only route, and it is undocumented.

Note the asymmetry the design leans on: `graphqlPublic` is undocumented but
genuinely public, keyless, introspectable and already relied upon by a shipped
integration. `graphqlAuthenticated` is none of those things.

### 3.4 Prior art

- [ha-oesterreichische-post](https://github.com/ha-parcel-integrations/ha-oesterreichische-post)
  (MIT) — tracking-number-based, ships against `graphqlPublic`. Source of the
  `TrackingState` table in §6.
- [thekumi/postat](https://github.com/thekumi/postat) — Python, scripts the same
  B2C `SelfAsserted` journey, and reads tenant/policy from `SETTINGS.hosts`.
- [KrauseFx/post-at-cli](https://github.com/KrauseFx/post-at-cli) — TypeScript,
  independently arrives at `response_type=id_token token` + `prompt=none` +
  `response_mode=fragment` against `graphqlAuthenticated`. Persists only the
  access token and re-logs-in hourly; persisting the SSO cookie instead (§4) is
  what makes unattended operation possible.

### 3.2 The authenticated API

Discovered by analysing a HAR capture of an authenticated browser session.

- **Endpoint:** `https://api.post.at/sendungen/sv/graphqlAuthenticated`
- **Identity provider:** Azure AD B2C
  - Tenant `f098c632-5a55-45ba-9bf4-c13870157cf1` (`kiamprod.onmicrosoft.com`)
  - Policy `b2c_1a_signup_signin` (Identity Experience Framework custom policy)
  - Client `c02d3813-d4b9-40a1-9db9-09e34cb9c2e1` (MSAL.js 1.4.17)
  - API scope `https://login.post.at/sendungenapi-prod/Sendungen.All`
  - Registered redirect URI `https://www.post.at`

These identifiers are public — they appear in any browser's network tab on
post.at. They are configuration, not secrets.

### 3.3 Which OAuth grant works

Established empirically against the live tenant:

| Grant | Result |
| --- | --- |
| Authorization code + PKCE + `offline_access` | `AADB2C90085` at redemption |
| Authorization code + PKCE, no `offline_access` | `AADB2C90085` at redemption |
| Authorization code, no PKCE | `AADB2C90085` at redemption |
| Implicit `id_token token` | Works — `expires_in=3600`, Bearer accepted |
| Implicit `id_token token` + `prompt=none` | Works — renews with no credentials |

The code flow fails identically in a browser and headless, with and without
PKCE, redeemed within two seconds of issuance. The client is registered as an
implicit-only Web application, so the authorization-code grant is unavailable.

**Consequence: no refresh token is obtainable.** The durable credential is the
B2C SSO cookie `x-ms-cpim-sso:kiamprod.onmicrosoft.com_0`, which `prompt=none`
exchanges for a fresh access token.

## 4. Authentication design

`auth.py` owns a `PostAtSession`.

### 4.1 Initial login

Drives the B2C sign-in journey directly, with `rememberMe=true`:

1. `GET {b2c}/oauth2/v2.0/authorize` with `response_type=id_token token`,
   `response_mode=fragment`. Parse the injected `SETTINGS` blob for `csrf`,
   `transId` and `hosts` — tenant and policy are read from `SETTINGS.hosts`
   rather than hardcoded, so a policy rename does not break the login. The
   hardcoded values in `const.py` are only the starting point for the first
   request.
2. `POST {b2c}/SelfAsserted?tx=…&p=…` with `request_type=RESPONSE`,
   `signInName`, `password` and the `X-CSRF-TOKEN` header. A JSON `status` of
   `200` means the credentials were accepted.
3. `GET {b2c}/api/CombinedSigninAndSignup/confirmed?…&rememberMe=true` and stop
   at the redirect to `https://www.post.at`, taking the access token from the
   fragment.

The password is used for step 2 only and is never persisted.

### 4.2 Silent renewal

`async_get_token()` returns the cached access token while more than five minutes
of its hour remain. Otherwise it replays the `authorize` request with
`prompt=none`, carrying only the stored SSO cookie, and parses the new token
from the redirect fragment.

### 4.3 Expiry

When `prompt=none` returns an error instead of a token, the session is dead.
`PostAtAuthExpired` propagates and Home Assistant starts its `reauth` flow,
which asks for the password only — the email is already known.

### 4.4 What is stored

Config entry data holds the SSO cookie name and value, and the account email for
the reauth prefill. Nothing else. No password, no access token (it is memory-only
and outlives nothing).

The SSO cookie is a bearer credential for the whole post.at account and lives
unencrypted in `.storage`, like every other HA credential. It is preferable to a
stored password because it expires, can be revoked by signing out, and is not a
secret the user may have reused elsewhere. This trade-off is documented in the
README rather than hidden.

## 5. API surface

Two endpoints, deliberately split by role.

The **authenticated** endpoint is used only to discover *which* parcels are in
the account. Everything else comes from Post's **public keyless** endpoint,
`https://api.post.at/sendungen/sv/graphqlPublic`, keyed on the tracking number
alone.

This matters because the public endpoint is the stable one: it has
introspection enabled, it is what the consumer tracking page uses, and
`ha-oesterreichische-post` already ships against it. It also carries
`trackingStateKey`, `text`, `textEn` and `stateInfo`, which the authenticated
endpoint has never been observed to return. Keeping enrichment on the public
surface shrinks the fragile, undocumented, unsanctioned dependency to a single
query returning a list of numbers.

**List** (authenticated) — one call per poll:

```graphql
sendungen(postProcessingOptions: {
  elementCount: 25, sortByDate: DESCENDING, paging: RECEIVE
}) {
  totalSendungen empfangsSendungen
  sendungen {
    sendungsnummer status bezeichnung sender hasNewFlag
    tags { key }
    estimatedDelivery { startDate endDate startTime }
    sendungsEvents { timestamp reasontypecode eventcountry eventpostalcode eventPlaceName }
  }
}
```

Only `sendungsnummer` and `bezeichnung` are actually consumed from this
response; the rest is requested so a poll still degrades to something useful if
the public endpoint does not yet know a freshly created parcel.

**Detail** (public, keyless) — one call per *active* parcel. Sent in the
variable form; inline arguments are refused:

```graphql
query ShipmentPublic($id: String!) {
  einzelsendung(sendungsnummer: $id) {
    status weight deliveryType branchkey
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
```

Delivered parcels are never re-fetched. The number of detail calls is bounded by
parcels in flight, typically zero to three.

`recipientAddress`, `packageRedirections`, `paymentInformation` and
`customsInformation` are deliberately not requested.

A parcel the public endpoint returns as `null` (known to the account but not yet
scanned) keeps the label and tracking number from the list response and reports
`unknown` until Post scans it.

## 6. Status mapping

Post's `status` field maps onto the carrier-agnostic vocabulary already used by
the ha-parcel-integrations family, so existing community parcel cards work
unchanged:

```
registered | in_transit | out_for_delivery | at_pickup_point
delivered  | returning  | problem          | unknown
```

### 6.1 Map on `trackingStateKey`, not `status` or `reasontypecode`

The parcel's status is taken from the newest event's `trackingStateKey`, a
stable semantic key such as `deliveryHandOver`. Post's own app upper-snakes it
(`DELIVERY_HAND_OVER`) and resolves it against its `TrackingState` enum; this
integration applies the same transform.

The two alternatives were both rejected:

- The top-level `status` field (`AN`, `ZU`) is too coarse — it cannot express
  `out_for_delivery` or `at_pickup_point`.
- `reasontypecode` (`AO`, `AT`, `EZ`, `ON`, `SE`, `UPB`, `XA`, `ZA`, `ZPB`) is
  undocumented anywhere public, and no project that consumes it has mapped it.
  `BlvckBytes/postrack` annotates the field "meaning yet unknown". The same
  event that reports `reasontypecode: AO` reports
  `trackingStateKey: deliveryHandOver`, which is self-describing.

### 6.2 The table

Post's `TrackingState` vocabulary, as lifted from Post's own app by
[ha-oesterreichische-post](https://github.com/ha-parcel-integrations/ha-oesterreichische-post)
(MIT). Credit that project in the source comment and the README.

| `trackingStateKey` (upper-snaked) | Canonical |
| --- | --- |
| `PENDING_INFORMATION`, `PARCEL_STAMP`, `AVISO`, `ALLES_POST` | `registered` |
| `DELIVERY_HAND_OVER`, `IN_DISTRIBUTION`, `CUSTOMS_CLEARANCE`, `DELIVERY_IN_CUSTOMS` | `in_transit` |
| `IN_DELIVERY` | `out_for_delivery` |
| `NOTIFIED`, `READY_FOR_PICK_UP`, `READY_FOR_PICK_UP_STATION`, `READY_FOR_PICK_UP_POINT`, `READY_FOR_PICK_UP_BOX` | `at_pickup_point` |
| `DELIVERED`, `DELIVERY_PARKED` | `delivered` |
| `DELIVERY_IN_RETURN` | `returning` |
| `DELIVERY_DELAYED`, `DELIVERY_INTERUPTED`, `NOT_REACHABLE` | `problem` |

`DELIVERY_INTERUPTED` is Post's own misspelling and must be kept verbatim.
`UNKNOWN` is deliberately absent: it is the app's own fallback, so seeing it on
the wire means the vocabulary moved, and it should surface as an unmapped value.

Every unrecognised key maps to `unknown` and logs a one-shot warning naming it.
An unmapped key must report `unknown`, never a guess — a wrong `delivered` is
worse than an honest `unknown`.

`raw_status` carries the original `trackingStateKey`; `status_text` carries
Post's own `textEn` (for example `Item accepted`), which needs no mapping and
is the friendliest thing to put on a dashboard.

## 7. Entities and events

A single service device, "Post.at", carrying:

| Entity | State | Notes |
| --- | --- | --- |
| `sensor.post_at_parcels_in_delivery` | count of active parcels | `parcels` attribute holds the list |
| `sensor.post_at_next_delivery` | earliest expected delivery | `device_class: timestamp` |
| `sensor.post_at_last_update` | last successful poll | diagnostic |

Each entry in `parcels[]`:

```
sendungsnummer, bezeichnung, status, trackingStateKey, raw_status,
status_text, eta_start, eta_end, eta_time, eta_text, sender, weight,
dimensions, last_event { timestamp, place, state_key, text }, url
```

`trackingStateKey` is exactly what Post sent (`deliveryHandOver`);
`raw_status` is the upper-snaked spelling the table in §6 is keyed on
(`DELIVERY_HAND_OVER`). Both are published: the verbatim key is what an issue
report should quote, and it is the only actionable detail when a status comes
back `unknown`.

`status_text` is Post's own `textEn` and `eta_text` its own
`estimatedDeliveryDateText`; neither needs mapping and both read well on a
dashboard.

No address fields. `recipientAddress` is the user's own name and street on every
parcel; it adds nothing to a dashboard and would otherwise land in the recorder
database and in any diagnostics attached to a GitHub issue.

### 7.1 Why one sensor rather than per-parcel entities

Per-parcel entities exist in sibling integrations mainly to support automations.
Events serve that better: one automation covers every parcel, present and future,
with no entity to reference and nothing to update when a parcel arrives.

For dashboards the single sensor is actively better. A list attribute renders
with core Lovelace (a markdown card looping over `parcels`), whereas per-parcel
entities need the `auto-entities` HACS card to render dynamically, and any
dashboard hardcoding a parcel's `entity_id` breaks within days. The single sensor
never churns — one stable `entity_id` for years.

Per-parcel entities remain a purely additive future change requiring no
migration.

### 7.2 Events

`post_at_parcel_registered`, `post_at_parcel_status_changed`,
`post_at_parcel_delivered`, `post_at_parcel_delivery_time_changed`.

Every payload carries the full normalised parcel plus the device id. All events
are suppressed on the first refresh after startup, so a restart does not replay
history.

### 7.3 Recorder

The `parcels` attribute changes on every poll. The README documents a
`recorder: exclude:` snippet rather than silently growing the database.

## 8. Polling

A `DataUpdateCoordinator` polling every **15 minutes** while any parcel is
active, and every **60 minutes** when none is. Not user-configurable.

On HTTP 401, force one token renewal and retry once; a second failure fails the
refresh and `DataUpdateCoordinator` surfaces it.

## 9. Repository layout and tooling

Mirrors `ha-geosphere-next`:

```
custom_components/post_at/
  __init__.py  api.py  auth.py  config_flow.py  const.py
  coordinator.py  diagnostics.py  entity.py  models.py  sensor.py
  manifest.json  strings.json  icons.json  translations/
docs/superpowers/specs/
tests/
.github/workflows/   validate.yml  release.yml  dependabot-version-bump.yml
AGENTS.md  CLAUDE.md  CONTRIBUTING.md  CHANGELOG.md  README.md
hacs.json  pyproject.toml  requirements_lint.txt  requirements_test.txt  LICENSE
```

ruff targeting `py314`, line length 88, the same `select` list as
`ha-geosphere-next`. uv for dependency management. pytest with
`asyncio_mode = "auto"`. MIT licence. Target Home Assistant 2026.9.3.

## 10. Testing

Unit tests over mocked HTTP, no live calls in CI:

- the login journey, including a `SelfAsserted` rejection
- silent renewal via `prompt=none`
- the 401 → renew → retry path, and the second-failure path
- `PostAtAuthExpired` triggering the reauth flow
- status mapping, including an unmapped code producing `unknown` and warning once
- event emission, and suppression on the first refresh
- sensor state and attribute shape, and the absence of address fields

Fixtures are sanitised copies of real responses captured from a live account:
names, addresses and tracking numbers scrubbed.

## 11. Release and HACS default

Beyond a working integration, HACS default listing needs a repository
description and topics, a valid `hacs.json`, green hassfest and HACS validation,
a tagged release, and a PR to `home-assistant/brands` adding an icon and logo for
the `post_at` domain.

## 12. Open risks

- **SSO cookie lifetime is unverified.** If `rememberMe=true` still yields a
  roughly 24-hour session, the user re-authenticates daily and this design needs
  rethinking. Measuring this is the first implementation task, before any other
  code is written.
- **The login journey is HTML-shaped.** Post restyling their B2C pages breaks
  `SelfAsserted` parsing. Mitigated by a clear error message and useful
  diagnostics; not preventable.
- **The API is undocumented and unsanctioned.** Unlike the public keyless
  tracking endpoint, `graphqlAuthenticated` carries no expectation of stability.
  Post may change or gate it without notice.
- **Terms of service.** Automating access to the logged-in account area may
  conflict with Post's terms. This is a decision for the repository owner before
  publishing to HACS, not a technical question.
- **`trackingStateKey` is unverified on the authenticated endpoint.** This is
  why enrichment reads from the public endpoint instead (§5). If a parcel ever
  appears in the account that the public endpoint will not resolve, it degrades
  to `unknown` rather than failing the poll.
- **The status table is second-hand.** It was lifted from Post's app by another
  project, not observed here; only `DELIVERY_HAND_OVER` has been seen against a
  real parcel in this account. Wrong rows are possible and will surface as
  visibly wrong statuses rather than errors.

## 13. Milestone 0 — verify before building

1. Log in with `rememberMe=true`; record whether the SSO cookie is persistent and
   what expiry it carries.
2. Confirm `prompt=none` still renews after the browser session would have ended.
3. If the session proves short-lived, stop and revisit §4 before writing
   integration code.
