# Copyright 2026 Floriane TUERNAL SABOTINOV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Bundled Dependencies - Locate vendor binaries when running from PyInstaller bundle.

When the application is built with PyInstaller, system dependencies (tesseract,
poppler) are bundled under _vendor/ relative to the executable. This module
provides paths to those bundled binaries.

In development (not frozen), all functions return None and the system PATH
is used as usual.
"""

import os
import sys
import platform
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


def _get_bundle_dir() -> Optional[Path]:
    """Return the bundle directory if running from a PyInstaller build, else None."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return None


def get_tesseract_cmd() -> Optional[str]:
    """
    Return the path to the bundled tesseract binary, or None in development.

    The binary is expected at:
        <bundle_dir>/_vendor/tesseract/tesseract(.exe)
    """
    bundle_dir = _get_bundle_dir()
    if bundle_dir is None:
        return None

    suffix = ".exe" if platform.system() == "Windows" else ""
    tesseract_path = bundle_dir / "_vendor" / "tesseract" / f"tesseract{suffix}"

    if tesseract_path.exists():
        logger.info("Using bundled tesseract", path=str(tesseract_path))
        return str(tesseract_path)

    logger.warning("Bundled tesseract not found", expected=str(tesseract_path))
    return None


def get_tessdata_prefix() -> Optional[str]:
    """
    Return the path to the bundled tessdata directory, or None in development.

    Expected at:
        <bundle_dir>/_vendor/tesseract/tessdata/
    """
    bundle_dir = _get_bundle_dir()
    if bundle_dir is None:
        return None

    tessdata_dir = bundle_dir / "_vendor" / "tesseract" / "tessdata"

    if tessdata_dir.is_dir():
        logger.info("Using bundled tessdata", path=str(tessdata_dir))
        return str(tessdata_dir)

    logger.warning("Bundled tessdata not found", expected=str(tessdata_dir))
    return None


def get_poppler_path() -> Optional[str]:
    """
    Return the path to the bundled poppler directory, or None in development.

    Expected at:
        <bundle_dir>/_vendor/poppler/
    Contains pdftoppm, pdfinfo, and shared libraries.
    """
    bundle_dir = _get_bundle_dir()
    if bundle_dir is None:
        return None

    poppler_dir = bundle_dir / "_vendor" / "poppler"

    if poppler_dir.is_dir():
        logger.info("Using bundled poppler", path=str(poppler_dir))
        return str(poppler_dir)

    logger.warning("Bundled poppler not found", expected=str(poppler_dir))
    return None


def configure_library_paths() -> None:
    """
    Prepend _vendor/ library directories to the platform library search path.

    This ensures bundled shared libraries (.so / .dylib) are found by the
    bundled binaries at runtime.

    - Linux:  prepends to LD_LIBRARY_PATH
    - macOS:  prepends to DYLD_LIBRARY_PATH
    - Windows: no-op (DLLs are found in the same directory as the exe)
    - Development (not frozen): no-op
    """
    bundle_dir = _get_bundle_dir()
    if bundle_dir is None:
        return

    system = platform.system()
    if system == "Windows":
        return

    vendor_dirs = [
        str(bundle_dir / "_vendor" / "tesseract"),
        str(bundle_dir / "_vendor" / "poppler"),
    ]

    if system == "Linux":
        env_var = "LD_LIBRARY_PATH"
    elif system == "Darwin":
        env_var = "DYLD_LIBRARY_PATH"
    else:
        return

    existing = os.environ.get(env_var, "")
    new_paths = os.pathsep.join(vendor_dirs)

    if existing:
        os.environ[env_var] = f"{new_paths}{os.pathsep}{existing}"
    else:
        os.environ[env_var] = new_paths

    logger.info(
        "Configured library search paths",
        env_var=env_var,
        added_paths=vendor_dirs,
    )
