# Branding

> Where the integration's icon lives, why it looks the way it does, and why it is **not** Österreichische Post's logo.

## Where the asset lives

| | |
|---|---|
| Location | `custom_components/post_at/brand/` |
| Files | `icon.png` (256×256), `icon@2x.png` (512×512) |
| Generator | `scripts/generate_brand_icon.py` (needs `Pillow`) |
| Format | PNG, RGBA, transparency outside the rounded square |

Home Assistant reads brand images from that directory directly, and local
images take priority over the brands CDN. This is the mechanism introduced in
**HA 2026.3**; this integration requires 2026.9.3, so it is always available.

To regenerate after editing the script:

```bash
pip install Pillow
python scripts/generate_brand_icon.py
```

## Why the asset is in this repo and not in home-assistant/brands

[home-assistant/brands](https://github.com/home-assistant/brands) still has a
`custom_integrations/` directory, but its README now states that *"Since HA
2026.3.0, custom components can include their brand icons directly"*, making
that directory legacy for new submissions. Shipping the icon here is the
current path, and it needs no pull request against another repository.

It also satisfies the HACS `brands` check, which looks for
`<content path>/brand/icon.png` in the repository tree and only falls back to
the brands CDN when the file is absent. With the asset present the check
passes without an `ignore:` entry — which matters, because HACS default-store
submission requires the action to pass with **no** ignored checks.

## Why it is not Post's logo

**This repository is MIT-licensed. Österreichische Post's post-horn mark,
wordmark and brand yellow are not ours to relicense.** Dropping their mark into
an MIT repository would assert a licence over it that we have no standing to
grant, and this project is explicitly
[not affiliated with Österreichische Post AG](../../README.md#disclaimer).

MIT is a copyright licence. A trademark is a separate right, and permissively
licensing a *file* does not convey permission to use the *mark* it depicts. The
brands CDN sidesteps this with a notice covering its own centrally-hosted
index —

> "All product names, trademarks and registered trademarks in the images in
> this repository, are property of their respective owners. All images in this
> repository are used by the Home Assistant project for identification purposes
> only."

— and that notice does not travel with a file we vendor into our own tree under
our own licence.

So the icon is an **original work authored in this repository**, and it
deliberately avoids:

- The post-horn device, in any recognisable or stylised form.
- The **POST** wordmark and its typography.
- Post's brand yellow. The parcel uses a warm amber (`#E8A854`) chosen to sit
  several steps away from Post's saturated lemon yellow, so the icon does not
  read as a Post asset at a glance.

## What the icon actually depicts

A parcel in isometric projection, with a delivery arc sweeping over it and
terminating in a waypoint dot. The design is functional rather than
brand-derived: it describes what the integration reports — a parcel, and where
it is on its way to you — rather than who carries it.

Anyone is free to reuse it under this repository's MIT licence, which is only
true because we own it.
