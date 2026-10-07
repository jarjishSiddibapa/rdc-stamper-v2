# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build consumed by the Inno Setup installer."""

import os


PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(PROJECT_ROOT, "src", "rdc_stamper")

a = Analysis(
    [os.path.join(SRC, "app.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, "app_icon.ico"), "."),
        # Portable OCR runtime, DLLs, and English language data.
        (os.path.join(SRC, "tesseract"), "tesseract"),
    ],
    hiddenimports=[
        "PIL",
        "PIL._imaging",
        "PIL.Image",
        "fitz",
        "fitz.utils",
        "pandas",
        "pandas._libs.tslibs.np_datetime",
        "pandas._libs.tslibs.nattype",
        "pandas._libs.tslibs.timedeltas",
        "openpyxl",
        "openpyxl.styles",
        "openpyxl.utils",
        "pytesseract",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "concurrent.futures",
        "datetime",
        "re",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "numpy.distutils",
        "IPython",
        "notebook",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RDC_STAMPER_V2",
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
    icon=os.path.join(SRC, "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RDC_STAMPER_V2",
)
