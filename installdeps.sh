#!/usr/bin/env bash

# Target folder for Kodi addon libs
TARGET_DIR="/home/boc/Documents/Github/kodi-xtream-vod-addon/resources/lib"

# Create target dir if missing
mkdir -p "$TARGET_DIR"

# Top-level modules you actually import in your addon
BASE_MODULES=(
    "requests"
    "schedule"
    "aiohttp"
    "aiofiles"
    "requests_cache"
    "unidecode"
    "rapidfuzz"
)

echo "Downloading and extracting Python modules (with deps) into $TARGET_DIR..."

# Temp download location
WORKDIR=$(mktemp -d)
UNPACKDIR="$WORKDIR/unpack"
mkdir -p "$UNPACKDIR"

# Download all base modules + their dependencies as wheels if possible
pip download --only-binary=:all: -d "$WORKDIR" "${BASE_MODULES[@]}"

# Extract all archives into UNPACKDIR
for file in "$WORKDIR"/*; do
    [[ -f "$file" ]] || continue
    echo "Extracting $file..."
    case $file in
        *.whl)
            unzip -q -o "$file" -d "$UNPACKDIR"
            ;;
        *.tar.gz|*.zip)
            tmpdir=$(mktemp -d)
            tar -xf "$file" -C "$tmpdir" 2>/dev/null || unzip -q "$file" -d "$tmpdir"
            pkgdir=$(find "$tmpdir" -mindepth 1 -maxdepth 1 -type d | head -n 1)
            if [ -d "$pkgdir" ]; then
                cp -r "$pkgdir"/* "$UNPACKDIR"/
            fi
            rm -rf "$tmpdir"
            ;;
    esac
done

# Copy only useful modules into TARGET_DIR (flattened)
for item in "$UNPACKDIR"/*; do
    name=$(basename "$item")
    if [ -d "$item" ] && [ -f "$item/__init__.py" ]; then
        echo "Copying package $name..."
        rm -rf "$TARGET_DIR/$name"
        cp -r "$item" "$TARGET_DIR/"
    elif [[ "$item" == *.py || "$item" == *.so ]]; then
        echo "Copying module $name..."
        cp -f "$item" "$TARGET_DIR/"
    fi
done

# Optional: strip out junk
find "$TARGET_DIR" -type d \( -name "__pycache__" -o -name "*.dist-info" -o -name "*.egg-info" \) -exec rm -rf {} +

echo "Cleaning up..."
rm -rf "$WORKDIR"

echo "✅ All modules (with dependencies) flattened into $TARGET_DIR"
