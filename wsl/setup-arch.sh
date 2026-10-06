#!/bin/bash
# Sets up the archlinux WSL distro for building and testing newDAWn and the MXM repositories on Linux.
# Run as root: wsl -d archlinux -u root -- bash /mnt/e/newDAWn/wsl/setup-arch.sh
# Safe to run again.
set -euo pipefail

# The keyring, then the system, then what the MXM CI installs on Ubuntu, in Arch's names.
pacman-key --init >/dev/null
pacman-key --populate archlinux >/dev/null
pacman -Syu --noconfirm --needed \
  base-devel git pkgconf python sudo which rustup \
  alsa-lib jack2 \
  libx11 libxcursor libxrandr libxi libxcb libxkbcommon libxkbcommon-x11 wayland \
  mesa vulkan-swrast vulkan-icd-loader xorg-server-xvfb

# The working user, logged in by default, with passwordless sudo inside this distro only.
id maxm >/dev/null 2>&1 || useradd -m -G wheel -s /bin/bash maxm
echo '%wheel ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/10-wheel
chmod 440 /etc/sudoers.d/10-wheel
cat > /etc/wsl.conf <<'EOF'
[user]
default = maxm

[boot]
systemd = true
EOF

# Rust at the toolchain every MXM repository's CI pins.
sudo -u maxm -H bash -lc 'rustup toolchain install 1.98.0 --profile minimal -c clippy -c rustfmt && rustup default 1.98.0 && rustc --version && cargo --version'
echo "setup done"
