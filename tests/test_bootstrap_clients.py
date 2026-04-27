"""Unit tests for scripts/bootstrap_clients.py (no network)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_PATH = REPO_ROOT / "scripts" / "bootstrap_clients.py"


def _load():
    spec = importlib.util.spec_from_file_location("bootstrap_clients_test", BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load bootstrap_clients.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bc = _load()


class BootstrapClientsTestCase(unittest.TestCase):
    def test_ocp_url_path_stable(self) -> None:
        self.assertEqual(bc._ocp_url_path("4.20"), "ocp/stable-4.20")

    def test_ocp_url_path_dev_preview(self) -> None:
        self.assertEqual(bc._ocp_url_path("4.22.0-ec.0"), "ocp-dev-preview/4.22.0-ec.0")


if __name__ == "__main__":
    unittest.main()
