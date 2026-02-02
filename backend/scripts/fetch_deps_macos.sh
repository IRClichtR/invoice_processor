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

# --- Helper: recursively collect all dylib dependencies ---
collect_dylibs_recursive() {
    local file_path="$1"
    local dest_dir="$2"
    local visited_file="$3"

    # Get all dylib dependencies
    otool -L "$file_path" 2>/dev/null | tail -n +2 | while read -r line; do
        dylib_path=$(echo "$line" | awk '{print $1}')

        # Skip system libraries
        case "$dylib_path" in
            /usr/lib/*|/System/*|@*) continue ;;
        esac

        local dylib_name
        dylib_name=$(basename "$dylib_path")

        # Skip if already visited (prevent infinite loops)
        if grep -qx "$dylib_name" "$visited_file" 2>/dev/null; then
            continue
        fi

        if [ -f "$dylib_path" ]; then
            # Mark as visited
            echo "$dylib_name" >> "$visited_file"

            # Copy if not already present
            if [ ! -f "$dest_dir/$dylib_name" ]; then
                cp "$dylib_path" "$dest_dir/"
                chmod u+w "$dest_dir/$dylib_name"
                echo "    Lib: $dylib_name"
            fi

            # Recursively collect this dylib's dependencies
            collect_dylibs_recursive "$dylib_path" "$dest_dir" "$visited_file"
        fi
    done
}

# --- Helper: copy a binary and rewrite its dylib paths ---
copy_binary_with_libs() {
    local binary_path="$1"
    local dest_dir="$2"
    local binary_name
    binary_name=$(basename "$binary_path")

    cp "$binary_path" "$dest_dir/"
    chmod u+w "$dest_dir/$binary_name"
    echo "    Copied $binary_name"

    # Create temp file to track visited dylibs (prevents infinite loops)
    local visited_file
    visited_file=$(mktemp)
    trap "rm -f '$visited_file'" RETURN

    # Recursively collect all dylib dependencies
    collect_dylibs_recursive "$binary_path" "$dest_dir" "$visited_file"

    # Now rewrite all library paths
    rewrite_dylib_paths "$dest_dir"
}

# --- Helper: rewrite all dylib paths in a directory ---
rewrite_dylib_paths() {
    local dest_dir="$1"

    # Process all binaries and dylibs in the directory
    for file in "$dest_dir"/*; do
        [ -f "$file" ] || continue
        chmod u+w "$file"

        local file_name
        file_name=$(basename "$file")

        # For dylibs, update their install name
        if [[ "$file_name" == *.dylib ]]; then
            install_name_tool -id "@loader_path/$file_name" "$file" 2>/dev/null || true
        fi

        # Rewrite all references to other dylibs in this directory
        for dylib in "$dest_dir"/*.dylib; do
            [ -f "$dylib" ] || continue
            local dylib_name
            dylib_name=$(basename "$dylib")

            # Find all references to this dylib and rewrite them
            otool -L "$file" 2>/dev/null | grep "$dylib_name" | awk '{print $1}' | while read -r orig_path; do
                if [ -n "$orig_path" ] && [ "$orig_path" != "@loader_path/$dylib_name" ]; then
                    install_name_tool -change "$orig_path" "@loader_path/$dylib_name" "$file" 2>/dev/null || true
                fi
            done
        done
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

# --- Final pass: ensure all cross-references are rewritten ---
echo "==> Finalizing dylib paths"
rewrite_dylib_paths "$VENDOR_DIR/tesseract"
rewrite_dylib_paths "$VENDOR_DIR/poppler"

# --- Verify all dependencies are self-contained ---
echo "==> Verifying bundle is self-contained"
MISSING_DEPS=0

verify_bundle() {
    local dir="$1"
    local name="$2"

    for file in "$dir"/*; do
        [ -f "$file" ] || continue
        local file_name
        file_name=$(basename "$file")

        # Check each dependency
        otool -L "$file" 2>/dev/null | tail -n +2 | while read -r line; do
            local dep_path
            dep_path=$(echo "$line" | awk '{print $1}')

            case "$dep_path" in
                /usr/lib/*|/System/*|@loader_path/*|@executable_path/*|@rpath/*)
                    # System libs and rewritten paths are OK
                    continue
                    ;;
                *)
                    # Non-system, non-rewritten path = potential problem
                    local dep_name
                    dep_name=$(basename "$dep_path")
                    if [ ! -f "$dir/$dep_name" ]; then
                        echo "    WARNING: $file_name references $dep_path (not bundled)"
                        MISSING_DEPS=1
                    fi
                    ;;
            esac
        done
    done
}

verify_bundle "$VENDOR_DIR/tesseract" "tesseract"
verify_bundle "$VENDOR_DIR/poppler" "poppler"

if [ "$MISSING_DEPS" = "1" ]; then
    echo ""
    echo "WARNING: Some dependencies may be missing. The bundle might not work on a clean macOS."
    echo "         Check the warnings above and ensure all required dylibs are collected."
fi

# --- Summary ---
echo ""
echo "==> Done! Vendor files collected in $VENDOR_DIR"
echo "    Tesseract files: $(find "$VENDOR_DIR/tesseract" -type f | wc -l | tr -d ' ')"
echo "    Poppler files:   $(find "$VENDOR_DIR/poppler" -type f | wc -l | tr -d ' ')"
echo ""
echo "Next step: cd backend && pyinstaller invoice_processor.spec"
