# -*- mode: python ; coding: utf-8 -*-
# RDC Stamper V2 — Single-File PyInstaller Spec
# Everything bundled: Python, Qt, PyMuPDF, Pillow, pytesseract, Tesseract OCR + language data

import os

# Absolute root of the project (relative to this spec file which lives in specs/)
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
SRC          = os.path.join(PROJECT_ROOT, 'src', 'rdc_stamper')

a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],          # so stamper_engine.py is importable as a plain module
    binaries=[],
    datas=[
        # App icon
        (os.path.join(SRC, 'app_icon.ico'),  '.'),
        # Entire bundled Tesseract installation (exe + all DLLs + tessdata)
        (os.path.join(SRC, 'tesseract'),      'tesseract'),
    ],
    hiddenimports=[
        # Pillow
        'PIL',
        'PIL._imaging',
        'PIL.Image',
        # PyMuPDF
        'fitz',
        'fitz.utils',
        # Data
        'pandas',
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.timedeltas',
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        # OCR
        'pytesseract',
        # PySide6 extras that may be missed
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # stdlib helpers used at runtime
        'concurrent.futures',
        'datetime',
        're',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused heavy packages
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy.distutils',
        'IPython',
        'notebook',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RDC_STAMPER_V2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                   # compress where possible — reduces final size
    upx_exclude=[
        # Don't compress Qt DLLs (they load dynamically and UPX can break them)
        'Qt6*.dll',
        'PySide6*.dll',
        # Don't compress Tesseract DLLs either
        'libtesseract*.dll',
        'libleptonica*.dll',
    ],
    runtime_tmpdir=None,        # None = use system temp — fastest startup for onefile
    console=False,              # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SRC, 'app_icon.ico'),
)
