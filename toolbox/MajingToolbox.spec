# -*- mode: python ; coding: utf-8 -*-
# 两层打包：exe = 运行时（Python + 第三方库 + 引导程序 boot.py）+ 内置的负载包（我们自己的 py 源码和界面）。
# 先跑 tools/build_payload.py 生成 stage/（负载包、运行时 id、负载包用到的模块清单），再打包。release.ps1 会按顺序做。
import json
import os

from PyInstaller.utils.hooks import collect_all

HERE = os.path.abspath(SPECPATH)
STAGE = os.path.join(HERE, 'stage')
for need in ('payload.zip', 'runtime.txt', 'hiddenimports.json'):
    if not os.path.exists(os.path.join(STAGE, need)):
        raise SystemExit('缺少 stage/%s：先运行 python tools/build_payload.py' % need)

datas = [(os.path.join(STAGE, 'payload.zip'), '.'), (os.path.join(STAGE, 'runtime.txt'), '.')]
binaries = []
# 我们自己的代码不再被冻进 exe，PyInstaller 看不到它们的 import：把负载包用到的模块全列在这里
hiddenimports = ['win32com.client', 'pythoncom'] + json.load(open(os.path.join(STAGE, 'hiddenimports.json'), encoding='utf-8'))
for pkg in ('webview', 'pythonnet', 'clr_loader', 'winpty'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['py/boot.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'setuptools', 'pkg_resources', 'distutils', 'pydoc_data', 'PyInstaller', 'pefile'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MajingToolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['py/res/app.ico'],
)
