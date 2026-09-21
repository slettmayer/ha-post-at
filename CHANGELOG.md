# Changelog

## 0.1.4

A review pass over the whole integration. Nothing here changes how it is set
up or what it publishes; all of it is behaviour that was wrong in a state the
happy path never reaches.

- **The 401 retry now actually renews the token.** A rejected access token was
  cached purely on the clock, so the one retry replayed the very token
  post.at had just refused and failed identically — turning a recoverable
  blip into a reauth prompt. The cached token is dropped before the retry.
- **A returning parcel is no longer frozen.** Only delivered parcels are
  final; a parcel on its way back to the sender is still being scanned, and
  caching it meant its status and last event never moved again and no further
  event ever fired for it.
- **Diagnostics no longer fail on a broken entry.** Downloading diagnostics
  for an entry that was unloaded, disabled or stuck retrying raised an error
  instead of producing a file — precisely the state an entry is in when
  diagnostics are asked for. The download now works in every state and
  reports the entry's state alongside it.
- **Events are ordered by instant, not by text.** Timestamps were compared as
  strings, so a parcel whose events carry mixed UTC offsets — a cross-border
  shipment — could pick an older event and roll its status backwards.
- **A cleared sign-in cookie is no longer accepted as a session.** Post's
  sign-in can end with a header that *deletes* the SSO cookie; that was stored
  as though it were a credential, producing a sign-in that reported success
  and then failed on the first poll. It now fails at sign-in, with a message
  that says so.
- **A parcel first seen already delivered now fires `parcel_delivered`.**
  There is no transition to observe in that case, so the arrival event never
  fired — and on the hourly idle cadence that is the ordinary case for a
  single unexpected parcel, which made the README's own "tell me when a
  parcel arrives" automation miss it. Only an arrival inside the last 24
  hours is announced; Post surfaces much older deliveries late and those stay
  quiet.
- **A delivery date with no time is read as an Austrian calendar day.** Post
  sends full timestamps today, but the sibling date-only field in the same
  payload shows a bare date is possible — and it would have been parsed
  without a timezone, which breaks the next-delivery sensor.
- Reauth no longer reloads the entry twice, which Home Assistant deprecates
  today and stops allowing in 2026.12.

## 0.1.3

- **The reply language is now selectable**, via **Configure** on the
  integration. Post localises on the `Accept-Language` header, which this
  integration never sent — so place names, delivery estimates and event
  descriptions came back German even on an English Home Assistant. Only German
  and English exist; anything else Post serves as German. The default is German
  for a German Home Assistant and English otherwise, and changing it reloads
  the entry so cached delivered parcels are re-fetched rather than left in the
  old language.
- **The disclaimer now states the terms question plainly.** The only terms of
  use Österreichische Post publishes for an online surface cover ELLA, their
  business portal, which is open to companies only and carries no clause on
  automated access; nothing was found governing the private account area this
  integration uses. Nothing permits this and nothing forbids it. The README
  says so, and says use at your own risk, instead of implying the matter was
  settled.

## 0.1.2

First release informed by real account data.

- **Delivered parcels now age out after 7 days.** The account list reaches
  months back, and publishing all of it grew the `parcels` attribute towards
  Home Assistant's ~16 KB ceiling (10 parcels measured at 6.2 KB; 25 would be
  ~15.6 KB) while rewriting the whole blob into the recorder every poll.
  Active parcels are never dropped, however old.
- Events now diff against their own history rather than the published list, so
  a parcel aging out of the attribute cannot re-fire `parcel_registered` on
  every poll.
- `weight` and `dimensions` are confirmed **kilograms and centimetres**,
  against a real 5.85 kg / 80×53×32 parcel. The "unverified" caveat is gone.
- Documented that `sender` is `null` on most consumer parcels.
- **Fixed the device's "Visit" link.** It pointed at
  `https://www.post.at/s/item-overview`, which 404s; the working URL carries a
  language segment (`/en/s/item-overview`). The per-parcel link is the
  opposite — `/s/sendungsdetails` works and `/en/...` 404s — so the two are
  deliberately inconsistent and now pinned by a test.

## 0.1.1

Fixes two bugs that made the config flow fail against the live post.at login.
Neither was reachable from the unit tests as written; both are now covered.

- **Cookies are written by hand, not by aiohttp.** aiohttp's `CookieJar`
  round-trips through `http.cookies.SimpleCookie`, which quotes values holding
  characters outside the legal token set. B2C's cookie values are full of `=`,
  `+` and `/`, and one cookie name contains a `|`. Post answered the mangled
  header with a bare `Bad Request` before ever checking the credentials. Both
  client sessions now use a `DummyCookieJar` and `auth.py` tracks cookies
  itself.
- **`SETTINGS.hosts.tenant` is a path prefix, not a tenant id.** It already
  contains the policy (`/<tenant>/B2C_1A_signup_signin`), so appending the
  policy again produced a doubled segment and a 404 on `SelfAsserted`. The
  test fixture now mirrors the real shape.

## 0.1.0

Initial release.

- Sign in to a private post.at account; parcels are discovered automatically,
  with no tracking numbers to enter
- `sensor.osterreichische_post_parcels_in_delivery` — count of parcels in
  flight, with every parcel in the `parcels` attribute
- `sensor.osterreichische_post_next_delivery` and a diagnostic
  `sensor.osterreichische_post_last_update`
- Events for registered, status changed, delivered and delivery time changed,
  all suppressed on the first refresh after a restart
- Status mapped from Post's `trackingStateKey`; the verbatim key is published
  alongside the canonical status, and anything unmapped reports `unknown`
- The account password is used once at setup and never stored
- Address fields are never requested or exposed
