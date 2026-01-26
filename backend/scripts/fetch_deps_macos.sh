#!/usr/bin/env bash
# fetch_deps_macos.sh - Collect tesseract + poppler binaries and dylibs
# for bundling into a PyInstaller build on macOS.
#
# Prerequisites:
#   brew install tesseract poppler
#
# Usage:
#   cd backend
#   bash scripts/fetch_deps_macos.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
VENDOR_DIR="$BACKEND_DIR/vendor/macos"

echo "==> Collecting macOS vendor dependencies into $VENDOR_DIR"

# Clean previous output
rm -rf "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR/tesseract/tessdata"
mkdir -p "$VENDOR_DIR/poppler"

# Homebrew prefix (works for both Intel and Apple Silicon)
BREW_PREFIX=$(brew --prefix 2>/dev/null || echo "/usr/local")

# --- Helper: copy a binary and rewrite its dylib paths ---
copy_binary_with_libs() {
    local binary_path="$1"
    local dest_dir="$2"
    local binary_name
    binary_name=$(basename "$binary_path")

    cp "$binary_path" "$dest_dir/"
    echo "    Copied $binary_name"

    # Collect dylibs via otool
    otool -L "$binary_path" 2>/dev/null | tail -n +2 | while read -r line; do
        dylib_path=$(echo "$line" | awk '{print $1}')

        # Only copy Homebrew / non-system dylibs
        case "$dylib_path" in
            /usr/lib/*|/System/*) continue ;;
        esac

        if [ -f "$dylib_path" ] && [ ! -f "$dest_dir/$(basename "$dylib_path")" ]; then
            cp "$dylib_path" "$dest_dir/"
            echo "    Lib: $(basename "$dylib_path")"
        fi
    done

    # Rewrite library paths to use @loader_path/
    chmod u+w "$dest_dir/$binary_name"
    for dylib in "$dest_dir"/*.dylib; do
        [ -f "$dylib" ] || continue
        dylib_name=$(basename "$dylib")
        chmod u+w "$dylib"

        # Update the binary to look for this dylib via @loader_path
        install_name_tool -change \
            "$(otool -L "$dest_dir/$binary_name" 2>/dev/null | grep "$dylib_name" | awk '{print $1}')" \
            "@loader_path/$dylib_name" \
            "$dest_dir/$binary_name" 2>/dev/null || true

        # Update the dylib's own install name
        install_name_tool -id "@loader_path/$dylib_name" "$dylib" 2>/dev/null || true
    done
}

# --- Tesseract ---
TESSERACT_BIN=$(command -v tesseract 2>/dev/null || true)
if [ -z "$TESSERACT_BIN" ]; then
    echo "ERROR: tesseract not found. Install with: brew install tesseract"
    exit 1
fi

echo "==> Collecting tesseract from $TESSERACT_BIN"
copy_binary_with_libs "$TESSERACT_BIN" "$VENDOR_DIR/tesseract"

# Copy tessdata
TESSDATA_DIR="$BREW_PREFIX/share/tessdata"
if [ ! -d "$TESSDATA_DIR" ]; then
    # Fallback: look relative to the binary
    TESSDATA_DIR="$(dirname "$(dirname "$TESSERACT_BIN")")/share/tessdata"
fi

if [ ! -d "$TESSDATA_DIR" ]; then
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

if [ -f "$TESSDATA_DIR/osd.traineddata" ]; then
    cp "$TESSDATA_DIR/osd.traineddata" "$VENDOR_DIR/tesseract/tessdata/"
fi

# --- Poppler ---
PDFTOPPM_BIN=$(command -v pdftoppm 2>/dev/null || true)
PDFINFO_BIN=$(command -v pdfinfo 2>/dev/null || true)

if [ -z "$PDFTOPPM_BIN" ] || [ -z "$PDFINFO_BIN" ]; then
    echo "ERROR: poppler-utils not found. Install with: brew install poppler"
    exit 1
fi

echo "==> Collecting poppler binaries"
copy_binary_with_libs "$PDFTOPPM_BIN" "$VENDOR_DIR/poppler"
copy_binary_with_libs "$PDFINFO_BIN" "$VENDOR_DIR/poppler"

# --- Rewrite dylib cross-references within each vendor dir ---
for dir in "$VENDOR_DIR/tesseract" "$VENDOR_DIR/poppler"; do
    for dylib in "$dir"/*.dylib; do
        [ -f "$dylib" ] || continue
        dylib_name=$(basename "$dylib")
        chmod u+w "$dylib"

        # Rewrite references to other dylibs in the same directory
        for other_dylib in "$dir"/*.dylib; do
            [ -f "$other_dylib" ] || continue
            other_name=$(basename "$other_dylib")
            [ "$dylib_name" = "$other_name" ] && continue

            # Find the original path in the dylib's load commands
            orig_path=$(otool -L "$dylib" 2>/dev/null | grep "$other_name" | awk '{print $1}' || true)
            if [ -n "$orig_path" ] && [ "$orig_path" != "@loader_path/$other_name" ]; then
                install_name_tool -change "$orig_path" "@loader_path/$other_name" "$dylib" 2>/dev/null || true
            fi
        done
    done
done

# --- Summary ---
echo ""
echo "==> Done! Vendor files collected in $VENDOR_DIR"
echo "    Tesseract files: $(find "$VENDOR_DIR/tesseract" -type f | wc -l)"
echo "    Poppler files:   $(find "$VENDOR_DIR/poppler" -type f | wc -l)"
echo ""
echo "Next step: cd backend && pyinstaller invoice_processor.spec"
