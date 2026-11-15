"""Run on Windows: py -3.12 windows/build.py [--sample path.NEF]."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile
import urllib.request
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or platform.architecture()[0] != '64bit':
        raise SystemExit('Use Windows and 64-bit Python 3.12 (including Tcl/Tk).')
    os.chdir(ROOT)
    # Find the x64 native compiler without requiring a developer command prompt.
    vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        raise SystemExit('Install Visual Studio 2022 Build Tools: Desktop development with C++.')
    install = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
    vcvars = Path(install) / 'VC/Auxiliary/Build/vcvars64.bat'
    if not install or not vcvars.is_file():
        raise SystemExit('The Visual Studio x64 C++ tools and Windows SDK are required.')
    env_output = subprocess.check_output(f'call "{vcvars}" >nul && set', shell=True, text=True)
    for line in env_output.splitlines():
        key, sep, value = line.partition('=')
        if sep and key:
            os.environ[key] = value
    venv = ROOT / '.venv-windows'
    if not venv.exists():
        run(sys.executable, '-m', 'venv', venv)
    python = venv / 'Scripts/python.exe'
    run(python, '-m', 'pip', 'install', '--only-binary=:all:', '-r', 'requirements.txt')
    run(python, '-c', 'import tkinter; print("Tk", tkinter.TkVersion)')
    exif = ROOT / 'vendor/exiftool.exe'
    if not exif.is_file() or not (ROOT/'vendor/exiftool_files').is_dir():
        url = 'https://downloads.sourceforge.net/project/exiftool/exiftool-13.59_64.zip'
        print('Downloading official ExifTool 13.59 x64...', flush=True)
        with tempfile.TemporaryDirectory(prefix='zf2lumix-exiftool-') as td:
            archive = Path(td)/'exiftool.zip'
            with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as target:
                shutil.copyfileobj(response, target)
            with zipfile.ZipFile(archive) as package:
                if package.testzip() is not None:
                    raise RuntimeError('Corrupt ExifTool download')
                package.extractall(Path(td)/'expanded')
            candidates = list((Path(td)/'expanded').rglob('exiftool(-k).exe'))
            if len(candidates) != 1 or not (candidates[0].parent/'exiftool_files').is_dir():
                raise RuntimeError('Unexpected ExifTool archive layout; see WINDOWS.md')
            exif.parent.mkdir(exist_ok=True)
            shutil.copy2(candidates[0], exif)
            shutil.copytree(candidates[0].parent/'exiftool_files', exif.parent/'exiftool_files', dirs_exist_ok=True)
            (exif.parent/'windows-exiftool-origin.json').write_text(json.dumps({
                'version': '13.59', 'url': url,
                'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2), encoding='utf-8')
    run(exif, '-config', '', '-ver')
    run('cl.exe', '/nologo', '/std:c++17', '/O2', '/EHsc', '/MT',
        '/DUNICODE', '/D_UNICODE', 'encode_pana8.cpp', '/Fe:encode_pana8.exe')
    run(python, '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    run(python, '-m', 'PyInstaller', '--clean', '--noconfirm', 'Zf2Lumix-windows.spec')
    # Test the packaged runtime, helpers, Tk startup and conversion after relocation.
    run(python, 'windows/verify.py', '--app', 'dist/Zf2Lumix/Zf2Lumix.exe',
        *(['--sample', args.sample.resolve()] if args.sample else []))
    app = ROOT / 'dist/Zf2Lumix'
    shutil.copy2(ROOT/'WINDOWS.md', app/'WINDOWS.md')
    manifest = {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(app.rglob('*')) if p.is_file()}
    (app/'SHA256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    shutil.make_archive(str(ROOT/'dist/Zf2Lumix-Windows-x64'), 'zip', ROOT/'dist', 'Zf2Lumix')
    print('Built: dist/Zf2Lumix-Windows-x64.zip')
    if not args.sample:
        print('No NEF supplied: Windows full conversion remains unverified. Rebuild with --sample path.NEF.')


if __name__ == '__main__':
    main()
