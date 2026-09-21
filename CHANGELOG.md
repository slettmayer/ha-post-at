# Changelog

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
