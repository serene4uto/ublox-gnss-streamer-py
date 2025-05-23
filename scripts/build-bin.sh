#!/bin/bash

CURRENT_DIR=$(readlink -f "$(dirname "$0")")
WORKSPACE_ROOT=$(readlink -f "$CURRENT_DIR/..")


install_pkg() {
    sudo apt update
    sudo apt-get install -y \
        patchelf
}
build_bin()