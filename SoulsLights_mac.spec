# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('assets/app_icon.png', 'assets'),
    ('assets/SoulsLights.icns', 'assets'),
    ('mobile', 'mobile'),
    ('core/_token_hashes.json', 'core'),
]
binaries = []
hiddenimports = [
    'PIL._tkinter_finder',
    'objc',
    'Foundation',
    'AppKit',
    'Quartz',
    'core.mac_utils',
    'core.platform_utils',
]

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['winrt', 'pystray._win32'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SoulsLights',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SoulsLights',
)

app = BUNDLE(
    coll,
    name='SoulsLights.app',
    icon='assets/SoulsLights.icns',
    bundle_identifier='com.soulslights.app',
    version='2.2.0',
    info_plist={
        'CFBundleName': 'SoulsLights',
        'CFBundleDisplayName': 'SoulsLights',
        'CFBundleExecutable': 'SoulsLights',
        'CFBundlePackageType': 'APPL',
        'CFBundleIdentifier': 'com.soulslights.app',
        'CFBundleVersion': '2.2.0',
        'CFBundleShortVersionString': '2.2.0',
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'LSMinimumSystemVersion': '12.0',
        'LSUIElement': False,
        'NSAppleEventsUsageDescription': 'SoulsLights reads currently playing track metadata and album art from Spotify and Apple Music for synced lyrics and edge lighting.',
    },
)
