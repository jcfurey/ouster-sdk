#!/bin/bash
#
# Claude Code SessionStart hook: install Ouster SDK build/test dependencies
# so that subsequent sessions can build the C++ libraries, run ctest, and
# exercise the Python bindings + pytest suite.
#
# Designed to be idempotent and non-interactive. Only runs in remote
# (Claude Code on the web) environments.

set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

echo "[ouster-sdk hook] installing apt build dependencies..."
# Some sandbox images carry third-party PPAs (deadsnakes, ondrej) whose keys
# may have rotated; the packages we need come from main/universe so we don't
# need those sources. Disable the failing ones rather than abort the hook.
if [ -d /etc/apt/sources.list.d ]; then
    sudo find /etc/apt/sources.list.d \
        \( -name '*deadsnakes*' -o -name '*ondrej*' \) \
        -exec sudo rm -f {} +
fi
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    git \
    pkg-config \
    libeigen3-dev \
    libcurl4-openssl-dev \
    libtins-dev \
    libpcap-dev \
    libglfw3-dev \
    libpng-dev \
    libflatbuffers-dev \
    flatbuffers-compiler \
    libceres-dev \
    libtbb-dev \
    libssl-dev \
    libzip-dev \
    libzstd-dev \
    robin-map-dev \
    zlib1g-dev \
    libgtest-dev \
    clang-format \
    python3 \
    python3-pip \
    python3-venv \
    >/dev/null

echo "[ouster-sdk hook] installing python lint/test packages..."
python3 -m pip install --quiet --break-system-packages --force-reinstall \
    "flake8==7.1.2" \
    "mypy==1.14.1" \
    "clang-format==14.0.0"
python3 -m pip install --quiet --break-system-packages \
    "pytest>=7,<8" \
    pytest-xdist \
    pytest-asyncio \
    "iniconfig<=2.1.0" \
    types-psutil \
    types-waitress

echo "[ouster-sdk hook] installing the python package in editable mode..."
(
    cd python
    python3 -m pip install --quiet --break-system-packages -e ".[test]"
)

echo "[ouster-sdk hook] configuring cmake (build deferred)..."
cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTING=ON \
    -DBUILD_EXAMPLES=ON \
    >/dev/null

echo "[ouster-sdk hook] done. Build with:  cmake --build build -j\$(nproc)"
