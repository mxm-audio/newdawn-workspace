# newDAWn workspace

The folder every newDAWn and MXM repository lives in: the DAW, the shared kit, MXM Player, one
repository per instrument and effect, and the tools. Each subfolder under `newdawn/`, `kit/`,
`player/`, `instruments/`, `effects/` and `tools/` is a repository of its own. This workspace tracks
only its own files: the rules above them (`AGENTS.md`), the Linux build environments (`wsl/`) and the
collection-wide tests (`collection-tests/`).

You don't need this to work on one plugin: clone that plugin's repository and it builds and tests
on its own. This is for working across many at once.

## On a new machine

```
git clone https://github.com/mxm-audio/newdawn-workspace newDAWn
cd newDAWn
python ws.py clone      # every repository in repos.txt, into its folder
python ws.py status     # one row per repository
```

`ws.py` does one step in every repository at once (check, commit, push, pull, link the local kit,
bump a tag); `AGENTS.md` has the list. On macOS and Linux the command is `python3`; on Windows,
`.\ws` runs it too.

The toolchain is Rust 1.98.0, the version CI uses: `rustup toolchain install 1.98.0 -c clippy -c
rustfmt`, then `rustup override set 1.98.0` in this folder, so it applies to every repository inside
without changing your default.

MIT licensed (`LICENSE`). The repositories inside carry their own licences.

The public repositories are at [github.com/mxm-audio](https://github.com/mxm-audio). Official,
signed builds of newDAWn and the MXM instruments are sold at [mxm.dk](https://mxm.dk).
