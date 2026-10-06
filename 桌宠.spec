# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# sprites 目录要一起打进去，否则运行时会找不到立绘
datas = [('sprites', 'sprites')]
binaries = []
hiddenimports = []

# 这几个包有数据文件/扩展模块，用 collect_all 才能收全
for pkg in ('psutil', 'requests', 'pynvml'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# 本项目自己的模块。
# 桌宠.py 里是 `try: from weather_api import ...` 这种写法（缺模块也要能启动），
# PyInstaller 的静态分析对 try/except 里的导入不可靠，必须显式声明，
# 否则打出来的 exe 会提示「天气模块加载失败」。
hiddenimports += ['weather_api', 'usage_api', 'selftest']

a = Analysis(
    ['桌宠.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='肥鱼科研版',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
