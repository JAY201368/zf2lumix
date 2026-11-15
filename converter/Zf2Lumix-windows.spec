from pathlib import Path
import sys

if sys.platform != 'win32':
    raise RuntimeError('Windows packaging must run on Windows with x64 Python 3.12.')
p = Path(SPECPATH)
for required in ['encode_pana8.exe', 'vendor/exiftool.exe', 'vendor/exiftool_files']:
    if not (p / required).exists():
        raise FileNotFoundError(f'Missing {required}; run build-windows.cmd first.')
a = Analysis([str(p/'app.py')], pathex=[str(p)],
    binaries=[(str(p/'encode_pana8.exe'), '.')],
    datas=[(str(p/'assets'), 'assets'),
           (str(p/'vendor/exiftool.exe'), 'vendor'),
           (str(p/'vendor/exiftool_files'), 'vendor/exiftool_files'),
           (str(p/'licenses'), 'licenses'),
           (str(p/'使用说明.html'), '.'),
           (str(p/'THIRD_PARTY_NOTICES.md'), '.')],
    hiddenimports=[], hookspath=[str(p)], hooksconfig={}, runtime_hooks=[],
    excludes=['matplotlib','scipy','skimage','pandas','IPython','pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Zf2Lumix',
    debug=False, strip=False, upx=False, console=False,
    icon=str(p/'assets/icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Zf2Lumix')
