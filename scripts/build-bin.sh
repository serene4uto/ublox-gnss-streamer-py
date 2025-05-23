#!/bin/bash

CURRENT_DIR=$(readlink -f "$(dirname "$0")")
WORKSPACE_ROOT=$(readlink -f "$CURRENT_DIR/..")


install_pkg() {
    sudo apt update
    sudo apt-get install -y \
        patchelf \
        python3 \
        python3-pip

    pip install -r ${WORKSPACE_ROOT}/requirements.txt
}

build_bin() {
    python3 -m nuitka \
        --standalone \
        --onefile \
        --output-dir="$WORKSPACE_ROOT/bin" \
        ${WORKSPACE_ROOT}/ublox_gnss_streamer/main.py
}


# main entry
install_pkg
build_bin
echo "Build completed. The binary is located in the bin directory."





