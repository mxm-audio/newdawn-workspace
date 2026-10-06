#!/bin/bash
# Reports what the archlinux WSL distro offers a build: user, toolchain, system libraries, Vulkan, space.
echo "user: $(whoami), home: $HOME"
rustc --version
cargo --version
for p in alsa jack x11 xcursor xkbcommon wayland-client vulkan; do
  printf '%-15s %s\n' "$p" "$(pkg-config --modversion "$p" 2>&1)"
done
echo "vulkan drivers: $(ls /usr/share/vulkan/icd.d/ | tr '\n' ' ')"
df -h / | tail -1
