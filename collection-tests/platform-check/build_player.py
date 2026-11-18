"""Builds MXM Player's archive from any checkout, the way `ws.py release` builds it (AGENTS.md).

    python3 build_player.py <player checkout> --out <folder> [--windows]

For a player not released yet, a worktree's included: Linux's linked against glibc 2.31 with zig
(`ws.linux_zig_env`), `--windows` cross-compiled with cargo-xwin (`ws.windows_cross_env`), each in
a build folder of its own below `MXM_BUILD_ROOT`. macOS's is built on the Mac: run the checkout's
`packaging/package.py` there.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))
import ws  # noqa: E402  (the workspace tool: its build environments)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--windows", action="store_true")
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    target = ws.build_dir(checkout / ("target-check-windows" if args.windows else "target-check-linux"))
    cross = ws.windows_cross_env() if args.windows else ws.linux_zig_env(target)
    code = subprocess.run([sys.executable, "packaging/package.py", "--out", str(args.out.resolve())]
                          + (["--windows"] if args.windows else []), cwd=checkout,
                          env={**os.environ, **ws.cargo_env(), **cross, "CARGO_TARGET_DIR": str(target)}).returncode
    if code:
        raise SystemExit(code)
    if not args.windows:
        too_new = ws.too_new_for_linux([target / "release" / p for p in ("mxm-player", "mxm-cli")])
        if too_new:
            raise SystemExit(f"refused: the player {too_new}")


if __name__ == "__main__":
    main()
