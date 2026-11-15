"""Public NEF-to-RW2 desktop bundle, built entirely from release inputs."""
from pathlib import Path

project = Path(SPECPATH)
analysis = Analysis(
    [str(project / 'app.py')],
    pathex=[str(project)],
    binaries=[(str(project / 'encode_pana8'), '.')],
    datas=[
        (str(project.parent / 'LICENSE'), '.'),
        (str(project / 'assets'), 'assets'),
        (str(project / 'vendor'), 'vendor'),
        (str(project / 'licenses'), 'licenses'),
        (str(project / '使用说明.html'), '.'),
        (str(project / 'THIRD_PARTY_NOTICES.md'), '.'),
    ],
    hiddenimports=[],
    hookspath=[str(project)],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'skimage', 'pandas', 'IPython', 'pytest'],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [],
    exclude_binaries=True,
    name='Zf2Lumix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas,
    strip=False, upx=False, name='Zf2Lumix',
)
application = BUNDLE(
    collection,
    name='Zf2Lumix.app',
    icon=str(project / 'assets/icon.icns'),
    bundle_identifier='local.jay.zf2lumix',
    info_plist={
        'CFBundleShortVersionString': '1.0.1',
        'CFBundleVersion': '3',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '13.0',
        'ATSApplicationFontsPath': 'assets/fonts',
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Nikon NEF',
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
            'CFBundleTypeExtensions': ['nef', 'NEF'],
        }],
        'NSHumanReadableCopyright': 'Zf2Lumix contributors',
    },
)
