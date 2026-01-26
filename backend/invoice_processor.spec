# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Invoice Processor backend.

Build:
    cd backend
    # First fetch vendor dependencies for your platform:
    #   bash scripts/fetch_deps_linux.sh       (Linux)
    #   bash scripts/fetch_deps_macos.sh       (macOS)
    #   powershell scripts/fetch_deps_windows.ps1  (Windows)
    pyinstaller invoice_processor.spec

Output: dist/invoice_processor/ (directory bundle)

Note: The Florence-2 model is NOT bundled. It auto-downloads on first startup.
System dependencies (tesseract, poppler) are bundled from vendor/<platform>/.
"""

import os
import sys
import warnings
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# --- Vendor binary collection ---
platform_map = {"linux": "linux", "darwin": "macos", "win32": "windows"}
vendor_platform = platform_map.get(sys.platform)
vendor_dir = os.path.join("vendor", vendor_platform) if vendor_platform else None

bundled_binaries = []

if vendor_dir and os.path.isdir(vendor_dir):
    for subdir in ("tesseract", "poppler"):
        src_dir = os.path.join(vendor_dir, subdir)
        if not os.path.isdir(src_dir):
            continue
        for root, dirs, files in os.walk(src_dir):
            for fname in files:
                src_path = os.path.join(root, fname)
                # Destination preserves structure under _vendor/
                rel_path = os.path.relpath(root, vendor_dir)
                dest_dir = os.path.join("_vendor", rel_path)
                bundled_binaries.append((src_path, dest_dir))
    print(f"[spec] Collected {len(bundled_binaries)} vendor files from {vendor_dir}/")
else:
    warnings.warn(
        f"Vendor directory '{vendor_dir}' not found. "
        f"Run the appropriate fetch_deps script first. "
        f"Building without bundled system dependencies."
    )

# Collect all submodules for packages that use dynamic imports
hidden_imports = (
    # Uvicorn internals
    collect_submodules("uvicorn")
    + collect_submodules("uvicorn.lifespan")
    + collect_submodules("uvicorn.loops")
    + collect_submodules("uvicorn.protocols")
    # SQLAlchemy dialect
    + ["sqlalchemy.dialects.sqlite"]
    # ML / AI
    + collect_submodules("torch")
    + collect_submodules("transformers")
    + collect_submodules("timm")
    + ["einops", "einops.layers", "einops.layers.torch"]
    # Image processing
    + collect_submodules("PIL")
    # Logging
    + ["structlog"]
    # Encryption
    + collect_submodules("cryptography")
    # Claude API
    + ["anthropic"]
    # App modules
    + collect_submodules("app")
)

# Collect data files needed at runtime (e.g. tokenizer configs)
datas = collect_data_files("transformers", include_py_files=False)

# Packages to exclude (not needed, saves space)
excludes = [
    "matplotlib",
    "scipy",
    "pandas",
    "jupyter",
    "notebook",
    "IPython",
    "tkinter",
    "_tkinter",
    "test",
    "tests",
    "xmlrpc",
]

a = Analysis(
    ["run_server.py"],
    pathex=[],
    binaries=bundled_binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="invoice_processor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="invoice_processor",
)
