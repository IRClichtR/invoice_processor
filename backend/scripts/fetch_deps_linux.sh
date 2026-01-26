#!/usr/bin/env bash
# fetch_deps_linux.sh - Collect tesseract + poppler binaries and shared libs
# for bundling into a PyInstaller build on Linux (Debian/Ubuntu).
#
# Prerequisites:
#   sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra poppler-utils
#
# Usage:
#   cd backend
#   bash scripts/fetch_deps_linux.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
VENDOR_DIR="$BACKEND_DIR/vendor/linux"

# Libs to skip (core system libs that will always exist on target)
SKIP_LIBS="linux-vdso|libc\.so|libm\.so|libdl\.so|libpthread\.so|librt\.so|ld-linux"

echo "==> Collecting Linux vendor dependencies into $VENDOR_DIR"

# Clean previous output
rm -rf "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR/tesseract/tessdata"
mkdir -p "$VENDOR_DIR/poppler"

# --- Helper: copy a binary and its shared libs ---
copy_binary_with_libs() {
    local binary_path="$1"
    local dest_dir="$2"

    cp "$binary_path" "$dest_dir/"
    echo "    Copied $(basename "$binary_path")"

    # Collect shared libraries via ldd
    ldd "$binary_path" 2>/dev/null | while read -r line; do
        # Parse lines like: libfoo.so.1 => /usr/lib/x86_64-linux-gnu/libfoo.so.1 (0x...)
        lib_path=$(echo "$line" | grep -oP '=> \K/[^ ]+' || true)
        if [ -z "$lib_path" ]; then
            continue
        fi
        # Skip core system libs
        if echo "$lib_path" | grep -qE "$SKIP_LIBS"; then
            continue
        fi
        if [ -f "$lib_path" ] && [ ! -f "$dest_dir/$(basename "$lib_path")" ]; then
            cp "$lib_path" "$dest_dir/"
            echo "    Lib: $(basename "$lib_path")"
        fi
    done
}

# --- Tesseract ---
TESSERACT_BIN=$(command -v tesseract 2>/dev/null || true)
if [ -z "$TESSERACT_BIN" ]; then
    echo "ERROR: tesseract not found. Install with: sudo apt install tesseract-ocr"
    exit 1
fi

echo "==> Collecting tesseract from $TESSERACT_BIN"
copy_binary_with_libs "$TESSERACT_BIN" "$VENDOR_DIR/tesseract"

# Copy tessdata (language files)
TESSDATA_DIR=""
if [ -d "/usr/share/tesseract-ocr/5/tessdata" ]; then
    TESSDATA_DIR="/usr/share/tesseract-ocr/5/tessdata"
elif [ -d "/usr/share/tesseract-ocr/4.00/tessdata" ]; then
    TESSDATA_DIR="/usr/share/tesseract-ocr/4.00/tessdata"
elif [ -d "/usr/share/tessdata" ]; then
    TESSDATA_DIR="/usr/share/tessdata"
elif [ -n "${TESSDATA_PREFIX:-}" ] && [ -d "$TESSDATA_PREFIX" ]; then
    TESSDATA_DIR="$TESSDATA_PREFIX"
fi

if [ -z "$TESSDATA_DIR" ]; then
    echo "ERROR: Could not locate tessdata directory."
    exit 1
fi

echo "==> Copying tessdata from $TESSDATA_DIR"
for lang in eng fra; do
    src="$TESSDATA_DIR/${lang}.traineddata"
    if [ -f "$src" ]; then
        cp "$src" "$VENDOR_DIR/tesseract/tessdata/"
        echo "    Language: $lang"
    else
        echo "    WARNING: $lang.traineddata not found at $src"
    fi
done

# Also copy osd if available (needed for script detection)
if [ -f "$TESSDATA_DIR/osd.traineddata" ]; then
    cp "$TESSDATA_DIR/osd.traineddata" "$VENDOR_DIR/tesseract/tessdata/"
fi

# --- Poppler ---
PDFTOPPM_BIN=$(command -v pdftoppm 2>/dev/null || true)
PDFINFO_BIN=$(command -v pdfinfo 2>/dev/null || true)

if [ -z "$PDFTOPPM_BIN" ] || [ -z "$PDFINFO_BIN" ]; then
    echo "ERROR: poppler-utils not found. Install with: sudo apt install poppler-utils"
    exit 1
fi

echo "==> Collecting poppler binaries"
copy_binary_with_libs "$PDFTOPPM_BIN" "$VENDOR_DIR/poppler"
copy_binary_with_libs "$PDFINFO_BIN" "$VENDOR_DIR/poppler"

# --- Summary ---
echo ""
echo "==> Done! Vendor files collected in $VENDOR_DIR"
echo "    Tesseract files: $(find "$VENDOR_DIR/tesseract" -type f | wc -l)"
echo "    Poppler files:   $(find "$VENDOR_DIR/poppler" -type f | wc -l)"
echo ""
echo "Next step: cd backend && pyinstaller invoice_processor.spec"
