"""Validate Claude Code marketplace and plugin manifests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class MarketplaceJsonTests(unittest.TestCase):
    def test_marketplace_json(self) -> None:
        path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "midu16-prega")
        self.assertIn("owner", data)
        self.assertIn("plugins", data)
        self.assertTrue(any(p.get("name") == "prega-release-notes" for p in data["plugins"]))

    def test_plugin_json(self) -> None:
        path = REPO_ROOT / "plugins" / "prega-release-notes" / ".claude-plugin" / "plugin.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "prega-release-notes")
        self.assertIn("commands", data)
        self.assertIn("skills", data)


if __name__ == "__main__":
    unittest.main()
