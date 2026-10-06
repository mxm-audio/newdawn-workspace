#!/bin/bash
# Sets up the Ubuntu-24.04 WSL distro as a copy of GitHub's ubuntu-latest runner for the MXM CI:
# the same system libraries the CI installs, Rust 1.98.0, Xvfb, and gdb for backtraces.
# Run as root: wsl -d Ubuntu-24.04 -u root -- bash /mnt/e/newDAWn/wsl/setup-ubuntu.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential git curl pkg-config gdb xvfb xauth \
  libasound2-dev libjack-jackd2-dev libx11-dev libx11-xcb-dev libxcursor-dev libxkbcommon-dev \
  libwayland-dev libgl1-mesa-dev mesa-vulkan-drivers >/dev/null
id maxm >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo maxm
echo 'maxm ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/10-maxm && chmod 440 /etc/sudoers.d/10-maxm
printf '[user]\ndefault = maxm\n' > /etc/wsl.conf
sudo -u maxm -H bash -lc 'curl -sSf https://sh.rustup.rs | sh -s -- -y -q --default-toolchain 1.98.0 --profile minimal -c clippy -c rustfmt && . ~/.cargo/env && rustc --version'
echo "setup done: $(ldd --version | head -1)"
