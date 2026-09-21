from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "plugin-station"
sys.path.insert(0, str(APP_ROOT))

from core import wininet_proxy  # noqa: E402


class WinInetProxyTests(unittest.TestCase):
    def test_apply_proxy_bypass_updates_connection_settings_and_broadcasts(self) -> None:
        set_option = MagicMock(return_value=True)
        library = MagicMock()
        library.InternetSetOptionW = set_option

        with patch.object(wininet_proxy.ctypes, "WinDLL", return_value=library):
            wininet_proxy.apply_proxy_bypass("taobao.com;*.taobao.com")

        self.assertEqual([call.args[1] for call in set_option.call_args_list], [75, 39, 37])

    def test_apply_proxy_bypass_raises_when_connection_update_fails(self) -> None:
        set_option = MagicMock(return_value=False)
        library = MagicMock()
        library.InternetSetOptionW = set_option

        with (
            patch.object(wininet_proxy.ctypes, "WinDLL", return_value=library),
            self.assertRaises(OSError),
        ):
            wininet_proxy.apply_proxy_bypass("taobao.com")


if __name__ == "__main__":
    unittest.main()
