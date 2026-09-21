# Changelog

## 0.1.3

- **The reply language is now selectable**, via **Configure** on the
  integration. Post localises on the `Accept-Language` header, which this
  integration never sent — so place names, delivery estimates and event
  descriptions came back German even on an English Home Assistant. Only German
  and English exist; anything else Post serves as German. The default is German
  for a German Home Assistant and English otherwise, and changing it reloads
  the entry so cached delivered parcels are re-fetched rather than left in the
  old language.
- **The disclaimer now states the terms question plainly.** Österreichische
  Post publishes no terms of use covering their website, account area or these
  endpoints — nothing permits this and nothing forbids it. The README says so,
  and says use at your own risk, instead of implying the matter was settled.

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
