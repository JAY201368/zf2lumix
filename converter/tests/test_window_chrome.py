"""Native title integration is opt-in for supported macOS Tk windows."""
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from window_chrome import integrated_titlebar


class ChromeFallbackTests(unittest.TestCase):
    def test_other_platforms_keep_their_window_controls(self):
        root = MagicMock()
        with patch('window_chrome.sys.platform', 'win32'):
            self.assertFalse(integrated_titlebar(root))
        root.attributes.assert_not_called()

    def test_old_tk_keeps_native_titlebar(self):
        root = MagicMock()
        root.attributes.side_effect = tk.TclError('unsupported attribute')
        with patch('window_chrome.sys.platform', 'darwin'):
            self.assertFalse(integrated_titlebar(root))
        root.attributes.assert_called_once_with('-stylemask')
