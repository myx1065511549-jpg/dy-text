# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置:抖音直播实时看板(onedir,内置 chromium)
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

SRC = os.path.join(os.getcwd(), "src")
LOCALAPPDATA = os.environ["LOCALAPPDATA"]
CHROMIUM = os.path.join(LOCALAPPDATA, "ms-playwright", "chromium-1228")

# 应用自带的资源
datas = [
    (os.path.join(SRC, "web"), "web"),
    (os.path.join(SRC, "vendor"), "vendor"),
    (os.path.join(SRC, "proto"), "proto"),
    (CHROMIUM, "ms-playwright/chromium-1228"),   # 内置浏览器内核
]
binaries = []
hiddenimports = ["douyin_pb2"] + collect_submodules("uvicorn")

# 把这些包的数据/动态库/子模块全收进来
for pkg in ("playwright", "jieba", "py_mini_racer", "fastapi", "uvicorn",
            "starlette", "anyio", "websockets", "wsproto", "h11", "httptools"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [os.path.join(SRC, "server.py")],
    pathex=[SRC, os.path.join(SRC, "proto")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 这些包我们的服务用不到,排除掉大幅瘦身
        "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "numpy", "scipy", "pandas", "sympy", "numpy.f2py",
        "sphinx", "docutils", "alabaster", "babel", "jedi", "parso",
        "IPython", "ipykernel", "notebook", "jupyter", "nbconvert", "nbformat",
        "tkinter", "_tkinter", "turtle", "turtledemo",
        "PIL", "Pillow", "pytest", "setuptools._vendor",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="douyin-dashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="douyin-dashboard",
)
