"""Distribution rules for the plugin manifests.

Claude Code reads the plugin version from the `version` field. If the
manifests have no `version` field, Claude Code uses the git commit, and each
new commit becomes an update. The manifests must not have a `version` field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> Any:
    return json.loads((REPO_ROOT / ".claude-plugin" / name).read_text(encoding="utf-8"))


def test_plugin_manifest_declares_no_static_version() -> None:
    manifest = _load("plugin.json")

    assert manifest["name"] == "langfuse-observability"
    assert "version" not in manifest


def test_marketplace_entries_declare_no_static_version() -> None:
    marketplace = _load("marketplace.json")

    entries = marketplace["plugins"]
    assert entries, "marketplace.json must list the plugin"
    for entry in entries:
        assert "version" not in entry
