import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "plugin-station"))

from core.control import ControlService  # noqa: E402
from core.company_access import CompanyAccess


class DashboardProcessSnapshotTests(unittest.TestCase):
    def test_one_process_listing_serves_multiple_cards(self):
        service = object.__new__(ControlService)
        service._lock = threading.RLock()
        service.company_access = CompanyAccess()
        service.private_root = Path("private")
        service.private_errors = []
        service.plugins = {
            "first": {"id": "first", "name": "first", "executable": "First.exe", "processName": "First.exe"},
            "second": {"id": "second", "name": "second", "executable": "Second.exe", "processName": "Second.exe"},
        }
        snapshot = {"first.exe": [11], "second.exe": [22]}

        def card(plugin):
            return {"id": plugin["id"], "pids": service._plugin_pids(plugin)}

        with patch("core.control.all_process_pids", return_value=snapshot) as listing, patch.object(
            service, "_plugin_status", side_effect=card
        ), patch("core.control.process_pids", side_effect=lambda name, exe, snapshot: snapshot[name.lower()]):
            result = service.dashboard()

        listing.assert_called_once_with()
        self.assertEqual([card["pids"] for card in result["plugins"]], [[11], [22]])


if __name__ == "__main__":
    unittest.main()
