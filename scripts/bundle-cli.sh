#!/usr/bin/env bash
set -euo pipefail

# Build a portable CLI bundle for embedding in the Mac App.
#
# Inputs (env vars):
#   PYTHON_VERSION  — pinned Python version (e.g. "3.12")
#   BUNDLE_OUTPUT   — output directory (e.g. "/tmp/cli-bundle")
#
# Output:
#   $BUNDLE_OUTPUT/venv/   — fully self-contained Python venv with CLI installed
#   $BUNDLE_OUTPUT/bin/    — native tool binaries (ffmpeg, ffprobe, fpcalc)
#
# The venv is made relocatable by:
#   - Copying (not symlinking) the Python binary via --copies
#   - Ensuring venv/bin/python3 is the real interpreter (not a launcher stub)
#   - Bundling the Python stdlib (venv only has site-packages by default)
#   - Bundling the Python shared library and fixing load paths
#   - Rewriting shebangs to #!/usr/bin/env python3
#   - Fixing pyvenv.cfg to point at the venv itself

: "${PYTHON_VERSION:?PYTHON_VERSION is required (e.g. 3.12)}"
: "${BUNDLE_OUTPUT:?BUNDLE_OUTPUT is required (output directory path)}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== bundle-cli: Building CLI bundle ==="
echo "  Python version: $PYTHON_VERSION"
echo "  Output:         $BUNDLE_OUTPUT"
echo "  Repo root:      $REPO_ROOT"

# 1. Resolve Python
PYTHON_BIN="python${PYTHON_VERSION}"
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    echo "Error: $PYTHON_BIN not found on PATH" >&2
    echo "Install it via pyenv or python.org framework installer." >&2
    exit 1
fi
PYTHON_PATH="$(command -v "$PYTHON_BIN")"
echo "  Python binary:  $PYTHON_PATH"

# 2. Create venv with --copies (real binary, not symlink)
echo "--- Creating venv ---"
rm -rf "$BUNDLE_OUTPUT"
"$PYTHON_BIN" -m venv --copies "$BUNDLE_OUTPUT/venv"

# 3. Install CLI with all extras
echo "--- Installing CLI ---"
"$BUNDLE_OUTPUT/venv/bin/pip" install --no-cache-dir "$REPO_ROOT[trash,ssim,audio,watch]"

# 4. Make the venv self-contained
#    venv --copies gives us site-packages + a copied binary, but the binary
#    still depends on the builder's Python for stdlib and shared library.
echo "--- Making venv self-contained ---"

# Query paths from the venv's own Python (still works at build time since the
# builder's base Python is present).
PYTHON_VER="$("$BUNDLE_OUTPUT/venv/bin/python3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
STDLIB_SRC="$("$BUNDLE_OUTPUT/venv/bin/python3" -c "import sysconfig; print(sysconfig.get_path('stdlib'))")"
VENV_LIB="$BUNDLE_OUTPUT/venv/lib/python${PYTHON_VER}"

# 4a. Bundle Python stdlib
echo "  stdlib source: $STDLIB_SRC"
rsync -a --exclude='site-packages' --exclude='__pycache__' --exclude='*.pyc' "$STDLIB_SRC/" "$VENV_LIB/"
echo "  Copied stdlib into venv"

# 4b. Ensure python3 is the real interpreter, not a launcher stub.
#     Some Python builds (e.g. Homebrew framework) install a launcher stub as
#     python3 that spawns Resources/Python.app. The versioned binary
#     (python3.XX) is always the real interpreter. Overwrite if different.
VERSIONED_BIN="$BUNDLE_OUTPUT/venv/bin/python${PYTHON_VER}"
if [ -f "$VERSIONED_BIN" ]; then
    HASH_GENERIC="$(md5 -q "$BUNDLE_OUTPUT/venv/bin/python3")"
    HASH_VERSIONED="$(md5 -q "$VERSIONED_BIN")"
    if [ "$HASH_GENERIC" != "$HASH_VERSIONED" ]; then
        echo "  python3 is a launcher stub — replacing with real interpreter"
        cp "$VERSIONED_BIN" "$BUNDLE_OUTPUT/venv/bin/python3"
    fi
fi

# 4c. Bundle Python shared library, framework resources, and fix load paths
#     Query base_prefix now (before modifying the binary — it still needs the builder's Python)
BASE_PREFIX="$("$BUNDLE_OUTPUT/venv/bin/python3" -c "import sys; print(sys.base_prefix)")"
DYLIB_REF="$(otool -L "$BUNDLE_OUTPUT/venv/bin/python3" | awk 'NR>1 && /[Pp]ython/ {print $1; exit}')"
if [ -n "$DYLIB_REF" ] && [[ "$DYLIB_REF" != @* ]]; then
    # Resolve symlinks to the actual file
    DYLIB_REAL="$(python3 -c "import os; print(os.path.realpath('$DYLIB_REF'))")"
    if [ -f "$DYLIB_REAL" ]; then
        DYLIB_NAME="$(basename "$DYLIB_REF")"
        DYLIB_DEST="$BUNDLE_OUTPUT/venv/lib/$DYLIB_NAME"
        cp "$DYLIB_REAL" "$DYLIB_DEST"
        chmod 644 "$DYLIB_DEST"
        # Fix the binary to load from its own lib/ directory
        install_name_tool -change "$DYLIB_REF" "@executable_path/../lib/$DYLIB_NAME" \
            "$BUNDLE_OUTPUT/venv/bin/python3"
        install_name_tool -id "@loader_path/$DYLIB_NAME" "$DYLIB_DEST"
        # Also fix the versioned binary if it exists
        if [ -f "$VERSIONED_BIN" ]; then
            install_name_tool -change "$DYLIB_REF" "@executable_path/../lib/$DYLIB_NAME" \
                "$VERSIONED_BIN" 2>/dev/null || true
        fi
        # Re-sign after modifying (Apple Silicon kills invalidly-signed binaries)
        codesign --force --sign - "$BUNDLE_OUTPUT/venv/bin/python3"
        codesign --force --sign - "$DYLIB_DEST"
        [ -f "$VERSIONED_BIN" ] && codesign --force --sign - "$VERSIONED_BIN" 2>/dev/null || true
        echo "  Bundled dylib: $DYLIB_REF → @executable_path/../lib/$DYLIB_NAME"

        # 4c-ii. Bundle Resources/Python.app if present (framework builds).
        #        Some Python builds (Homebrew, python.org) include a Python.app launcher
        #        that the interpreter spawns at startup. Without it the binary segfaults
        #        or errors with "posix_spawn: ... Python.app: Undefined error: 0".
        #        Python.app lives at <base_prefix>/Resources/Python.app and the interpreter
        #        expects it at <dylib_dir>/Resources/Python.app.
        PYTHON_APP_SRC="${BASE_PREFIX}/Resources/Python.app"
        if [ -d "$PYTHON_APP_SRC" ]; then
            mkdir -p "$BUNDLE_OUTPUT/venv/lib/Resources"
            cp -R "$PYTHON_APP_SRC" "$BUNDLE_OUTPUT/venv/lib/Resources/Python.app"
            # Fix the Python.app binary's dylib reference
            # Python.app is at venv/lib/Resources/Python.app/Contents/MacOS/Python
            # Dylib is at venv/lib/<DYLIB_NAME>  — 4 levels up from MacOS/
            PYTHON_APP_BIN="$BUNDLE_OUTPUT/venv/lib/Resources/Python.app/Contents/MacOS/Python"
            if [ -f "$PYTHON_APP_BIN" ]; then
                APP_DYLIB_REF="$(otool -L "$PYTHON_APP_BIN" | awk 'NR>1 && /[Pp]ython/ && !/CoreFoundation/ {print $1; exit}')"
                if [ -n "$APP_DYLIB_REF" ] && [[ "$APP_DYLIB_REF" != @* ]]; then
                    install_name_tool -change "$APP_DYLIB_REF" \
                        "@loader_path/../../../../$DYLIB_NAME" "$PYTHON_APP_BIN"
                    codesign --force --sign - "$PYTHON_APP_BIN"
                fi
            fi
            echo "  Bundled Resources/Python.app"
        fi
    fi
else
    echo "  No external Python dylib (statically linked or already relocatable)"
fi

# 4d. Fix pyvenv.cfg to point at the venv itself
sed -i '' "s|^home = .*|home = $(cd "$BUNDLE_OUTPUT/venv/bin" && pwd)|" "$BUNDLE_OUTPUT/venv/pyvenv.cfg"
echo "  Fixed pyvenv.cfg home"

# 5. Copy native binaries
echo "--- Copying native binaries ---"
mkdir -p "$BUNDLE_OUTPUT/bin"
for tool in ffmpeg ffprobe fpcalc; do
    TOOL_PATH="$(command -v "$tool" 2>/dev/null || true)"
    if [ -z "$TOOL_PATH" ]; then
        echo "Error: $tool not found on PATH" >&2
        exit 1
    fi
    cp "$TOOL_PATH" "$BUNDLE_OUTPUT/bin/$tool"
    echo "  Copied $tool from $TOOL_PATH"
done

# 6. Rewrite shebangs in venv/bin/* scripts
echo "--- Rewriting shebangs ---"
for script in "$BUNDLE_OUTPUT/venv/bin/"*; do
    [ -f "$script" ] || continue
    if head -1 "$script" 2>/dev/null | grep -q '^#!.*python'; then
        sed -i '' '1s|^#!.*python[0-9.]*|#!/usr/bin/env python3|' "$script"
    fi
done

# 7. Create a standalone wrapper that always uses the bundled Python
#    (Homebrew cask symlinks this to /opt/homebrew/bin/duplicates-detector)
echo "--- Creating standalone wrapper ---"
cat > "$BUNDLE_OUTPUT/duplicates-detector" <<'WRAPPER'
#!/bin/bash
# Resolve symlinks so this works when called via Homebrew symlink
SOURCE="$0"
while [ -L "$SOURCE" ]; do
  DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
exec "$SCRIPT_DIR/venv/bin/python3" -m duplicates_detector "$@"
WRAPPER
chmod +x "$BUNDLE_OUTPUT/duplicates-detector"

# 8. Strip unnecessary files
echo "--- Stripping unnecessary files ---"

find "$BUNDLE_OUTPUT/venv" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUNDLE_OUTPUT/venv" -name "*.pyc" -delete 2>/dev/null || true
# Remove Python config dirs — they contain symlinks that violate Apple's bundle
# signing rules and are only needed for building C extensions (not at runtime).
find "$BUNDLE_OUTPUT/venv" -type d -name "config-*-darwin" -exec rm -rf {} + 2>/dev/null || true
# Remove pip and setuptools (bundled venv is immutable)
PATH="$BUNDLE_OUTPUT/venv/bin:$PATH" "$BUNDLE_OUTPUT/venv/bin/python3" -m pip uninstall -y pip setuptools 2>/dev/null || true
rm -f "$BUNDLE_OUTPUT/venv/bin/pip"* "$BUNDLE_OUTPUT/venv/bin/easy_install"* 2>/dev/null || true

# 9. Verify — the bundle must work with ONLY its own PATH (no system Python)
echo "--- Verifying CLI bundle ---"
CLI_VERSION="$(PATH="$BUNDLE_OUTPUT/venv/bin:$BUNDLE_OUTPUT/bin:/usr/bin:/bin" \
    "$BUNDLE_OUTPUT/venv/bin/duplicates-detector" --version 2>&1)" || {
    echo "Error: CLI verification failed" >&2
    echo "The bundle is not self-contained — it may still depend on the builder's Python." >&2
    exit 1
}
echo "  CLI version: $CLI_VERSION"

# Also verify Python can import the stdlib without the builder's Python on PATH
PATH="$BUNDLE_OUTPUT/venv/bin:/usr/bin:/bin" \
    "$BUNDLE_OUTPUT/venv/bin/python3" -c "import os, json, pathlib; print('  stdlib: OK')" || {
    echo "Error: stdlib verification failed — bundle is missing Python standard library" >&2
    exit 1
}

# Report bundle size
BUNDLE_SIZE="$(du -sh "$BUNDLE_OUTPUT" | cut -f1)"
echo ""
echo "=== bundle-cli: Done ($BUNDLE_SIZE) ==="
