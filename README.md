# Österreichische Post — Account Parcel Tracker

[![Release](https://img.shields.io/github/v/release/slettmayer/ha-post-at.svg)](https://github.com/slettmayer/ha-post-at/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration that signs in to your private
[Österreichische Post](https://www.post.at) account and reports the parcels
addressed to you. Parcels appear **automatically** — there is nothing to type
in, because the integration reads the same account list the post.at website
shows you.

It talks to Post directly. No AfterShip, no 17track, no Parcel app, no
third-party collector of any kind.

> ### ⚠️ Early release
>
> This integration drives an undocumented, unsanctioned API. It works today and
> may stop working tomorrow without notice. The status vocabulary is complete
> but only two of its values have been seen against a real parcel in a real
> account — anything unmapped reports `unknown` and asks you to open an issue.

## Contents

- [Do you actually want this one?](#do-you-actually-want-this-one)
- [Security](#security)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
  - [Language](#language)
- [Entities](#entities)
- [The `parcels` attribute](#the-parcels-attribute)
- [Events](#events)
- [Dashboard](#dashboard)
- [Recorder](#recorder)
- [Parcel status reference](#parcel-status-reference)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)
- [Credits](#credits)
- [License](#license)

## Do you actually want this one?

There are two Austrian Post integrations, and they solve different problems.

| | [ha-oesterreichische-post](https://github.com/ha-parcel-integrations/ha-oesterreichische-post) | **this one** |
|---|---|---|
| Account needed | no | **yes** |
| How parcels get tracked | you enter each tracking number | discovered automatically |
| Credentials stored | none | a post.at session cookie |
| API used | Post's public keyless endpoint | account endpoint + public endpoint |

**If you do not want to hand credentials to a Home Assistant integration, use
the other one.** It is well built, it needs no account, and for a parcel whose
tracking number you already have it does the same job. This integration exists
only for the case the other one cannot serve: *"show me what is on its way to
me, without me telling you about it."*

## Security

Read this before installing.

- **Your password is used once and then discarded.** The config flow runs
  Post's Azure AD B2C sign-in journey with it and keeps only the resulting
  session cookie. The password is never written to `.storage`, never logged,
  and never sent anywhere except Post's own login endpoint.
- **The session cookie is a credential for your whole post.at account.** It
  lives unencrypted in Home Assistant's `.storage`, exactly like every other
  credential Home Assistant persists. Anyone who can read that directory can
  read your parcels.
- **It can be revoked.** Signing out of post.at everywhere invalidates it.
- **It expires.** When it does, Home Assistant raises a reauthentication
  prompt and asks for your password again. Nothing is lost.
- **Your address is never touched.** The account API returns your name and
  street on every parcel. This integration does not request those fields, and
  they never reach the state machine, the recorder or a diagnostics download.

Post offers no refresh token for this client, so a stored session cookie is
the only way to poll unattended. If that trade is not one you want to make,
use the tracking-number integration linked above instead.

## Requirements

- A private post.at account with parcels addressed to it.
- Home Assistant **2026.9.3** or newer.

## Installation

### HACS

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/slettmayer/ha-post-at` as an **Integration**.
3. Install **Österreichische Post (Account)** and restart Home Assistant.

### Manual

Copy `custom_components/post_at` into your `config/custom_components/` folder
and restart Home Assistant.

## Configuration

**Settings → Devices & Services → Add Integration → Österreichische Post
(Account)**, then enter the email and password you use on post.at.

Polling runs every 15 minutes while a parcel is moving and every 60 minutes
when nothing is. That is not configurable: a parcel feed has one sensible
cadence, and the endpoint is undocumented enough without being hammered.

### Language

Post serves **German or English** — no other language exists — and it picks by
the `Accept-Language` header, not by your account settings. It affects place
names (`Logistikzentrum Kärnten, AT` vs `Logistics centre Carinthia, AT`),
delivery estimates (`Voraussichtlich morgen` vs `Approximately tomorrow`) and
event descriptions.

The default is **German for a German Home Assistant and English for everything
else**. To change it: **Settings → Devices & Services → Österreichische Post
(Account) → Configure**. The integration reloads and re-fetches, so parcels
switch language immediately.

## Entities

| Entity | State |
|---|---|
| `sensor.osterreichische_post_parcels_in_delivery` | Number of parcels still on their way. The `parcels` attribute holds them all. |
| `sensor.osterreichische_post_next_delivery` | Earliest expected delivery across active parcels (`timestamp`). |
| `sensor.osterreichische_post_last_update` | Diagnostic: last successful poll. |

There is deliberately **no entity per parcel**. A parcel lives for a few days,
so per-parcel entities churn constantly, leave orphans in the registry, and
break any dashboard that names one. One stable sensor plus
[events](#events) covers both dashboards and automations without that cost.

## The `parcels` attribute

Every parcel still on its way, plus those delivered in the last **7 days**.
Post's account list reaches months back; publishing all of it would push the
attribute past what Home Assistant will carry (~16 KB) and rewrite the whole
blob into the recorder on every poll.

| Field | Meaning |
|---|---|
| `sendungsnummer` | Tracking number |
| `bezeichnung` | The label you gave the parcel on post.at |
| `status` | Canonical status — see [the table](#parcel-status-reference) |
| `trackingStateKey` | Post's own key, **verbatim** (`deliveryHandOver`) |
| `raw_status` | The same key upper-snaked (`DELIVERY_HAND_OVER`) |
| `status_text` | Post's own wording (`Item accepted`) — see [Language](#language) |
| `eta_start` / `eta_end` | Expected delivery window, ISO 8601 |
| `eta_time` | Expected time of day, when Post gives one |
| `eta_text` | Post's own phrasing (`Approximately tomorrow`) — see [Language](#language) |
| `sender` | Shipper name. Post leaves this `null` on most consumer parcels — do not rely on it |
| `weight` | Kilograms |
| `dimensions` | `height` / `length` / `width`, in centimetres |
| `last_event` | `timestamp`, `place`, `state_key`, `text` |
| `url` | Deep link to the parcel on post.at |

No address fields. Ever.

## Events

Automations key on these rather than on entities, so one automation covers
every parcel, present and future:

| Event | When |
|---|---|
| `post_at_parcel_registered` | A parcel appears on the account |
| `post_at_parcel_status_changed` | Canonical status changed (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `post_at_parcel_delivered` | A parcel was delivered (see below for one first seen already delivered) |
| `post_at_parcel_delivery_time_changed` | The expected delivery window moved |

Every payload is the full parcel as described above. All four are suppressed on
the first refresh after a restart, so rebooting does not replay your history.

A parcel can turn up on the account already delivered, with no transition to
observe -- on the hourly idle cadence that is the ordinary case for a single
unexpected parcel. `post_at_parcel_delivered` fires for it too, alongside
`post_at_parcel_registered`, provided it arrived within the last 24 hours.
Post also surfaces much older deliveries late, and those stay quiet.

```yaml
automation:
  - alias: "Tell me when a parcel arrives"
    triggers:
      - trigger: event
        event_type: post_at_parcel_delivered
    actions:
      - action: notify.persistent_notification
        data:
          title: "Parcel delivered"
          message: >-
            {{ trigger.event.data.bezeichnung or trigger.event.data.sendungsnummer }}
            — {{ trigger.event.data.status_text }}
```

## Dashboard

No custom cards needed — a core markdown card iterates the attribute:

```yaml
type: markdown
content: |
  {% set parcels = state_attr('sensor.osterreichische_post_parcels_in_delivery', 'parcels') %}
  {% if parcels %}
  {% for p in parcels %}
  **{{ p.bezeichnung or p.sendungsnummer }}** — {{ p.status_text or p.status }}
  {{ p.eta_text or '' }}
  {% endfor %}
  {% else %}
  No parcels on the way.
  {% endif %}
```

## Recorder

The `parcels` attribute is rewritten on every poll, so it will grow your
database for no benefit. Exclude it:

```yaml
recorder:
  exclude:
    entities:
      - sensor.osterreichische_post_parcels_in_delivery
```

The count and `next_delivery` are worth keeping if you want history; the
attribute blob is not.

## Parcel status reference

`status` is the carrier-agnostic vocabulary shared with the
[ha-parcel-integrations](https://ha-parcel-integrations.github.io/) family, so
community parcel cards work against it unchanged.

| Status | Post's `trackingStateKey` |
|---|---|
| `registered` | `pendingInformation`, `parcelStamp`, `aviso`, `allesPost` |
| `in_transit` | `deliveryHandOver`, `inDistribution`, `customsClearance`, `deliveryInCustoms` |
| `out_for_delivery` | `inDelivery` |
| `at_pickup_point` | `notified`, `readyForPickUp`, `readyForPickUpStation`, `readyForPickUpPoint`, `readyForPickUpBox` |
| `delivered` | `delivered`, `deliveryParked` (left at your agreed *Wunschplatz*) |
| `returning` | `deliveryInReturn` |
| `problem` | `deliveryDelayed`, `deliveryInterupted`, `notReachable` |
| `unknown` | anything not listed above |

A key this integration does not recognise reports `unknown` rather than a
guess — a wrong `delivered` is far more damaging than an honest `unknown`. It
logs a one-shot warning naming the key. **Please
[open an issue](https://github.com/slettmayer/ha-post-at/issues) when you see
one**, quoting the `trackingStateKey` from the log or the attribute. That is
what finishes this integration.

## Debugging

```yaml
logger:
  logs:
    custom_components.post_at: debug
```

Diagnostics can be downloaded from the integration page. They contain no
tracking numbers, no labels, no email and no session cookie — only statuses and
timings, so they are safe to attach to an issue.

## Troubleshooting

- **"Invalid email or password"** — the same credentials you use on post.at.
  If they work in a browser but not here, Post has probably changed their
  sign-in page; please open an issue.
- **Reauthentication keeps being requested** — the session cookie's lifetime is
  set by Post, not by this integration. If it expires daily rather than weekly,
  open an issue with how long it lasted.
- **A parcel shows `unknown`** — either Post has not scanned it yet, or it
  reported a state key that is not mapped. The log line tells you which.
- **A parcel is missing** — only parcels the account shows under received
  shipments are tracked. If post.at does not list it, neither will this.

## Disclaimer

**Use at your own risk.**

This integration is not affiliated with, endorsed by, or supported by
Österreichische Post AG. It is an independent project that drives
**undocumented, unsanctioned endpoints** of Post's consumer website, using your
own credentials to read your own account.

**The terms are unknown.** Österreichische Post publishes terms of use for
exactly one of its online surfaces:
[Nutzungsbedingungen ELLA](https://ella.post.at/nutzungsbedingungen), governing
their **business** portal. Those apply only to `Unternehmer*innen` — ELLA's own
FAQ states that registering it with a private post.at account is not permitted
— and they carry no clause about automated access in any case. We found nothing
governing the private account area this integration uses, or these endpoints.

So: nothing permits this and nothing forbids it. That is an absence of rules,
not permission, and it is not legal advice. If automated access to your post.at
account matters to you, satisfy yourself before installing.

Consequences you accept by using it:

- Post may change, gate or withdraw these endpoints at any time, without
  notice, and the integration will simply stop working.
- Post may take a view on automated account access that this project cannot
  anticipate, including action against the account involved.
- Your post.at session cookie is stored in Home Assistant — see
  [Security](#security).

The maintainers provide no warranty of any kind, as stated in the
[MIT licence](LICENSE).

## Credits

The icon is an **original work** authored in this repository and shipped under
its MIT licence. It is deliberately **not** Österreichische Post's post-horn
mark, wordmark or brand yellow — those are registered trademarks and are not
ours to relicense. See [docs/tech/BRANDING.md](docs/tech/BRANDING.md) for the
reasoning and `scripts/generate_brand_icon.py` for how it is produced.

The `TrackingState` vocabulary in
[`status.py`](custom_components/post_at/status.py) was lifted from Post's own
app by the MIT-licensed
[ha-oesterreichische-post](https://github.com/ha-parcel-integrations/ha-oesterreichische-post)
project, and is reproduced here with thanks. If you want tracking-number-based
tracking without an account, use that project.

## License

[MIT](LICENSE)
