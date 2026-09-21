"""The manifest must stay consistent with the rest of the repository."""

import json
from pathlib import Path

from custom_components.post_at.const import DOMAIN

MANIFEST = Path("custom_components/post_at/manifest.json")


def test_manifest_domain_matches_const():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["domain"] == DOMAIN


def test_manifest_declares_config_flow_and_no_requirements():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert manifest["iot_class"] == "cloud_polling"


def test_hacs_filename_matches_domain():
    hacs = json.loads(Path("hacs.json").read_text())
    assert hacs["filename"] == f"{DOMAIN}.zip"
    assert hacs["zip_release"] is True
