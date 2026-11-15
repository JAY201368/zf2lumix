import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_support as support


class PlatformTests(unittest.TestCase):
    def test_windows_helpers_and_utf8(self):
        with patch.object(support.sys, 'platform', 'win32'), \
             patch.object(support.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
             patch.object(support.subprocess, 'run') as run:
            self.assertEqual(support.encoder_path(Path('bundle')).name, 'encode_pana8.exe')
            self.assertEqual(support.exiftool_command(Path('bundle')), [str(Path('bundle/vendor/exiftool.exe'))])
            support.run_tool(['encoder.exe', '中文 路径'], capture_output=True, timeout=10)
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
            self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
            self.assertEqual(run.call_args.args[0][1], '中文 路径')

    def test_windows_open_uses_file_association(self):
        with patch.object(support.sys, 'platform', 'win32'), \
             patch.object(support.os, 'startfile', create=True) as start:
            support.open_path('使用说明.html')
            start.assert_called_once_with(str(Path('使用说明.html').resolve()))

    def test_macos_helpers(self):
        with patch.object(support.sys, 'platform', 'darwin'):
            self.assertEqual(support.encoder_path(Path('bundle')).name, 'encode_pana8')
            self.assertEqual(support.exiftool_command(Path('bundle'))[0], '/usr/bin/perl')


if __name__ == '__main__':
    unittest.main()
