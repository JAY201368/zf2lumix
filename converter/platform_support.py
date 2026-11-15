"""Small OS boundary shared by the GUI and conversion worker."""
import os
from pathlib import Path
import subprocess
import sys


def run_tool(command, **kwargs):
    # Windowed PyInstaller apps have no console; helpers must not flash one.
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, encoding='utf-8', errors='replace', **kwargs)


def exiftool_command(home):
    if sys.platform == 'win32':
        return [str(Path(home) / 'vendor' / 'exiftool.exe')]
    return ['/usr/bin/perl', str(Path(home) / 'vendor' / 'exiftool')]


def encoder_path(home):
    return Path(home) / ('encode_pana8.exe' if sys.platform == 'win32' else 'encode_pana8')


def open_path(path):
    path = str(Path(path).resolve())
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
