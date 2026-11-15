from pathlib import Path
import subprocess
p=Path(SPECPATH)
raw_package=p/'raw_developer'
raw_runner=p/'build/raw-developer-runner'
raw_runner.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['xcrun','swiftc',str(raw_package/'runner.swift'),'-O','-o',str(raw_runner)],check=True)
raw_data=[(str(path),'raw_developer') for pattern in ('*.metal','*.json') for path in raw_package.glob(pattern)]
a=Analysis([str(p/'app.py')],pathex=[str(p)],
 binaries=[(str(p/'encode_pana8'),'.'),(str(raw_runner),'raw_developer')],
 datas=[(str(p/'assets'),'assets'),(str(p/'vendor'),'vendor'),(str(p/'licenses'),'licenses'),(str(p/'使用说明.html'),'.'),(str(p/'THIRD_PARTY_NOTICES.md'),'.')]+raw_data,
 hiddenimports=['raw_developer','jpeg_export','PIL.ImageCms'],hookspath=[str(p)],hooksconfig={},runtime_hooks=[],
 excludes=['matplotlib','scipy','skimage','pandas','IPython','pytest'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Zf2Lumix',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,target_arch='arm64',codesign_identity=None,entitlements_file=None)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='Zf2Lumix')
app=BUNDLE(coll,name='Zf2Lumix.app',icon=str(p/'assets/icon.icns'),bundle_identifier='local.jay.zf2lumix',
 info_plist={'CFBundleShortVersionString':'1.0.1','CFBundleVersion':'2','NSHighResolutionCapable':True,'LSMinimumSystemVersion':'13.0','ATSApplicationFontsPath':'assets/fonts',
 'CFBundleDocumentTypes':[{'CFBundleTypeName':'Nikon NEF','CFBundleTypeRole':'Viewer','LSHandlerRank':'Alternate','CFBundleTypeExtensions':['nef','NEF']}],
 'NSHumanReadableCopyright':'Zf2Lumix — local conversion utility'})
