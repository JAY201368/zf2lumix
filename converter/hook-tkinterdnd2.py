"""Include the native drop extension matching this build's platform only."""
from pathlib import Path
import platform
import sys
import tkinterdnd2
import tkinter

machine = platform.machine().lower()
if sys.platform == 'darwin':
    variant = 'osx-arm64' if machine == 'arm64' else 'osx-x64'
elif sys.platform == 'win32':
    variant = 'win-arm64' if machine == 'arm64' else 'win-x64' if sys.maxsize > 2**32 else 'win-x86'
else:
    variant = 'linux-arm64' if machine in ('aarch64', 'arm64') else 'linux-x64'
base = Path(tkinterdnd2.__file__).parent / 'tkdnd'
if tkinter.TclVersion >= 9 and (base / (variant+'-tcl9')).is_dir():
    variant += '-tcl9'
source = base / variant
target = 'tkinterdnd2/tkdnd/' + variant
datas = [(str(path), target) for path in source.iterdir() if path.suffix == '.tcl']
binaries = [(str(path), target) for path in source.iterdir() if path.suffix in ('.dll', '.so', '.dylib')]
