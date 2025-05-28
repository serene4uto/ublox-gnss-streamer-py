#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

CURRENT_DIR=$(readlink -f "$(dirname "$0")")
WORKSPACE_ROOT=$(readlink -f "$CURRENT_DIR/..")
OUTPUT_DIR="$WORKSPACE_ROOT/bin"

install_pkg() {
    echo "Installing dependencies..."
    sudo apt update
    sudo apt-get install -y patchelf python3 python3-pip

    pip install --upgrade pip
    pip install -r "${WORKSPACE_ROOT}/requirements.txt"
}

build_bin() {
    local TARGET_ARCH="$1"
    local VERSION="$2"
    local OUTPUT_FILENAME="ublox_gnss_streamer_${TARGET_ARCH}"

    echo "Building for architecture: $TARGET_ARCH"

    python3 -m nuitka \
        --standalone \
        --onefile \
        --output-dir="$OUTPUT_DIR" \
        --output-filename="$OUTPUT_FILENAME" \
        "${WORKSPACE_ROOT}/ublox_gnss_streamer/main.py"

    # Create an archive
    echo "Creating archive..."
    tar -czvf "${OUTPUT_DIR}/${OUTPUT_FILENAME}-${VERSION}.tar.gz" -C "$OUTPUT_DIR" "$OUTPUT_FILENAME"
    echo "Archive created: ${OUTPUT_DIR}/${OUTPUT_FILENAME}-${VERSION}.tar.gz"
}

# Main script
main() {
    local TARGET_ARCH="$1"
    local VERSION="$2"

    echo "Starting build process..."

    install_pkg

    # Perform build
    build_bin "$TARGET_ARCH" "$VERSION"

    echo "Build completed. The binary is located in the bin directory."
}

# Entry point:  Pass TARGET_ARCH and VERSION as arguments
main "$1" "$2"
