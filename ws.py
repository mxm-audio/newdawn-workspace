"""ws: work across every newDAWn and MXM repository from the workspace root.

The owner, 2026-10-06: "I want to work in this overarching folder. doing stuff repo by repo gets
tired real soon." Each repository stays standalone (a contributor clones one and needs none of
this); `ws` is how the workspace does the same step everywhere at once.

    python ws.py clone                       clone every repository in repos.txt that isn't here yet
    python ws.py status                      one row per repository: changes, unpushed, tag, pins
    python ws.py reach                       what each changed repository's change reaches: the
                                             packages to test, or "docs only" / "comments only"
    python ws.py check                       fmt, clippy and the tests the change reaches, Windows
                                             only (other platforms are a later batch)
    python ws.py commit -m "message"         commit every changed repository with one message
    python ws.py push                        push every repository that is ahead (refused while linked)
    python ws.py tag                         refused: no tags (the owner, 2026-10-07)
    python ws.py pull                        fast-forward every repository
    python ws.py each <command ...>          run a command in every repository
    python ws.py link kit [player] [nice-plug] [egui-baseview] [baseview]
                                             build against the local copies instead of their tags,
                                             for a change across repositories (a fork's version must
                                             match what each repository requires)
    python ws.py unlink                      back to the tags; restores the lockfiles `link` touched
    python ws.py update                      move each repository's mxm-audio dependencies to their
                                             current main and relock (no tags: the owner, 2026-10-07)

Every command takes --only <name,...>: repository names, or the groups newdawn, kit (= mxm-kit),
forks (nice-plug, egui-baseview, baseview), player, instruments, effects, plugins (= instruments +
effects), tools, ops, all (the default).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORG = "https://github.com/mxm-audio"
REPO_LIST = ROOT / "repos.txt"
CONFIG = ROOT / ".cargo" / "config.toml"
LINK_STATE = ROOT / ".cargo" / "ws-link.json"
GROUPS = ["newdawn", "kit", "player", "instruments", "effects", "tools", "ops"]
# `link` owns only this block of the root config; anything else there (sccache, say) is kept.
BEGIN, END = "# >>> ws link", "# <<< ws link"


def without_link():
    if not CONFIG.exists():
        return ""
    return re.sub(rf"(?s){re.escape(BEGIN)}.*?{re.escape(END)}\n?", "", CONFIG.read_text(encoding="utf-8"))


def write(path, text):
    """Text with LF line endings. `Path.write_text(newline=)` needs Python 3.10; macOS ships 3.9."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def linked():
    return CONFIG.exists() and BEGIN in CONFIG.read_text(encoding="utf-8")


# --- repositories -------------------------------------------------------------------------------

def repositories():
    """name -> (group, path) for every repository in the workspace, in a stable order."""
    out = {}
    if (ROOT / "newdawn" / ".git").exists():
        out["newdawn"] = ("newdawn", ROOT / "newdawn")
    for group in GROUPS[1:-1]:
        folder = ROOT / group
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if (path / ".git").exists():
                    # The kit/ folder holds mxm-kit and the forks; they are separate groups, so
                    # `kit` means mxm-kit here as in `link` and `bump` (2026-10-06: `tag --only kit`
                    # used to tag the forks too).
                    label = "forks" if group == "kit" and path.name in FORKS else group
                    out[path.name] = (label, path)
    if (ROOT / "ops" / ".git").exists():
        out["ops"] = ("ops", ROOT / "ops")
    return out


def listed():
    """folder -> (clone URL, status), from repos.txt. A repository without `public` counts as
    private: `ws tag` refuses it, so a forgotten status can only hold a tag back."""
    out = {}
    for line in REPO_LIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            folder, url, *rest = line.split()
            out[folder] = (url, rest[0] if rest else "private")
    return out


def status_of(path):
    return listed().get(path.relative_to(ROOT).as_posix(), (None, "unlisted"))[1]


def cmd_clone(args):
    missing = []
    for folder, (url, _) in listed().items():
        dest = ROOT / folder
        if (dest / ".git").exists():
            continue
        # No login prompt: a private repository without access is skipped, not waited on.
        r = subprocess.run(["git", "clone", "-q", url, str(dest)], capture_output=True, text=True,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        print(f"{folder}: {'cloned' if r.returncode == 0 else 'not cloned (private, or no access)'}")
        if r.returncode:
            missing.append(folder)
    print(f"not here: {', '.join(missing)} (log in to GitHub, then run clone again)" if missing
          else "every repository in repos.txt is here")


def selected(args):
    repos = repositories()
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1].split(",")
    if not only or "all" in only:
        return repos
    pick = {}
    for name, (group, path) in repos.items():
        if name in only or group in only or ("plugins" in only and group in ("instruments", "effects")):
            pick[name] = (group, path)
    unknown = [o for o in only if o not in repos and o not in GROUPS + ["forks", "plugins", "all"]]
    if unknown:
        raise SystemExit(f"unknown repository or group: {', '.join(unknown)}")
    return pick


def git(path, *args):
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip() if r.returncode == 0 else ""


def state(path):
    dirty = [l for l in git(path, "status", "--porcelain").splitlines() if l.strip()]
    ahead = git(path, "rev-list", "--count", "@{u}..HEAD")
    behind = git(path, "rev-list", "--count", "HEAD..@{u}")
    head = git(path, "log", "-1", "--format=%h %cs")
    lock = path / "Cargo.lock"
    text = lock.read_text(encoding="utf-8") if lock.exists() else ""
    # Dependencies follow main (the owner, 2026-10-07): the lock's commit is the pin.
    kit = re.search(r'mxm-audio/mxm-kit\?[^#"]*#([0-9a-f]{7})', text)
    player = re.search(r'mxm-audio/mxm-player\?[^#"]*#([0-9a-f]{7})', text)
    return {"dirty": len(dirty), "ahead": int(ahead or 0), "behind": int(behind or 0), "head": head or "-",
            "kit": kit.group(1) if kit else "-", "player": player.group(1) if player else "-",
            "upstream": bool(git(path, "rev-parse", "--abbrev-ref", "@{u}"))}


FORKS = ("nice-plug", "egui-baseview", "baseview")
# Forks that their dependents take by git rather than through [patch.crates-io]: baseview, which only
# the egui-baseview fork depends on (2026-10-07). `link` patches their git source instead.
GIT_FORKS = ("baseview",)


def unused_forks(path):
    """The MXM forks a repository's Cargo.lock lists under `[[patch.unused]]`: Cargo resolved a
    newer upstream release instead, so the fork's patches are not in the build (2026-10-06:
    egui-baseview 0.7.2 on crates.io silently replaced the 0.7.1 fork this way)."""
    lock = path / "Cargo.lock"
    if not lock.exists():
        return []
    text = lock.read_text(encoding="utf-8")
    blocks = re.findall(r'\[\[patch\.unused\]\]\s*\nname = "([^"]+)"', text)
    return [name for name in blocks if name in FORKS]


def changed(repos):
    with ThreadPoolExecutor(8) as pool:
        states = dict(zip(repos, pool.map(lambda r: state(r[1]), repos.values())))
    return {n: v for n, v in repos.items() if states[n]["dirty"] or states[n]["ahead"]}


# --- commands -----------------------------------------------------------------------------------

def cmd_status(args):
    repos = selected(args)
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda item: (item[0], item[1][0], state(item[1][1])), repos.items()))
    print(f"{'repository':24} {'group':12} {'status':11} {'changed':>7} {'ahead':>5} {'behind':>6}  "
          f"{'last commit':19} {'kit':8} player")
    for name, group, s in rows:
        flag = "" if s["upstream"] else "  (no remote)"
        print(f"{name:24} {group:12} {status_of(repos[name][1]):11} {s['dirty'] or '':>7} "
              f"{s['ahead'] or '':>5} {s['behind'] or '':>6}  {s['head']:19} {s['kit']:8} {s['player']}{flag}")
    shadowed = {name: unused_forks(path) for name, (group, path) in repos.items() if unused_forks(path)}
    for name, forks in shadowed.items():
        print(f"\nWARNING {name}: Cargo.lock does not use the {', '.join(forks)} fork (a newer upstream "
              f"release won): refresh the fork onto it, then relock. See the fork's PATCHES.md.")
    here = {p.relative_to(ROOT).as_posix() for _, p in repositories().values()}
    unlisted = sorted(here - set(listed()))
    if unlisted:
        print(f"\nnot in repos.txt (add them, so `ws clone` brings them to another machine): {', '.join(unlisted)}")
    if linked():
        print(f"\nLINKED: {CONFIG} builds against local repositories (`python ws.py unlink` to go back).")


def run_in(path, command, log=None):
    print(f"$ {' '.join(command)}", flush=True)
    r = subprocess.run(command, cwd=path, stdout=log, stderr=subprocess.STDOUT if log else None)
    return r.returncode


# --- what a change reaches ----------------------------------------------------------------------
#
# The owner, 2026-10-06: "make a gate so you test a minimum, and smartly. Development time is far
# more important than 0 bugs on all platforms at this point." `reach` decides the least that tests a
# change; `ws check` runs exactly that, and the PreToolUse gate in ~/.claude/hooks refuses more.

DOC_SUFFIXES = {".md", ".txt", ".html", ".png", ".svg", ".jpg", ".pdf"}
DOC_NAMES = {"LICENSE", "NOTICE", "TRADEMARKS", "CONTRIBUTING", "README"}
EVERYTHING = {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml"}


def cargo_program():
    local = ROOT / "rust" / "cargo" / "bin" / "cargo.exe"
    return str(local) if local.exists() else "cargo"


def cargo_env():
    env = dict(os.environ)
    if (ROOT / "rust" / "rustup").exists():
        env.setdefault("RUSTUP_HOME", str(ROOT / "rust" / "rustup"))
        env.setdefault("CARGO_HOME", str(ROOT / "rust" / "cargo"))
    return env


def changed_files(path):
    """Files that differ from the upstream branch (committed but unpushed, or not committed), plus
    untracked ones; against HEAD when there is no upstream."""
    base = "@{u}" if git(path, "rev-parse", "--abbrev-ref", "@{u}") else "HEAD"
    files = set(git(path, "diff", "--name-only", base).splitlines())
    files |= set(git(path, "ls-files", "--others", "--exclude-standard").splitlines())
    return base, sorted(f for f in files if f)


def is_doc(f):
    p = Path(f)
    return (p.suffix.lower() in DOC_SUFFIXES or p.stem.upper() in DOC_NAMES or f.startswith(".github/")
            or p.name in {".gitignore", ".gitattributes"})


def comment_only(path, base, f):
    """True when every changed line of a tracked .rs file is a comment or blank."""
    if not f.endswith(".rs") or not git(path, "ls-files", f):
        return False
    lines = [l[1:].strip() for l in git(path, "diff", "-U0", base, "--", f).splitlines()
             if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    return all(l == "" or l.startswith("//") for l in lines)


def members(path):
    """package name -> (folder relative to the repository, the names of the path packages it uses)."""
    r = subprocess.run([cargo_program(), "metadata", "--no-deps", "--format-version", "1", "--offline"],
                       cwd=path, capture_output=True, text=True, env=cargo_env())
    if r.returncode:
        return {}
    meta = json.loads(r.stdout)
    root = Path(meta["workspace_root"])
    out = {}
    for pkg in meta["packages"]:
        folder = Path(pkg["manifest_path"]).parent.relative_to(root).as_posix()
        uses = {d["name"] for d in pkg["dependencies"] if d.get("path")}
        out[pkg["name"]] = (folder, uses)
    return out


def reach(path):
    """What a repository's change reaches: kind (nothing, docs, comments, code), the packages to
    test (the changed ones, everything in the workspace that uses them, and a plugin's
    `<plugin>-host-tests`), and whether that is every package."""
    base, files = changed_files(path)
    result = {"files": files, "kind": "nothing", "reached": set(), "all": False, "members": {}}
    if not files:
        return result
    code = [f for f in files if not is_doc(f)]
    if not code:
        result["kind"] = "docs"
        return result
    code = [f for f in code if not comment_only(path, base, f)]
    if not code:
        result["kind"] = "comments"
        result["rust"] = [f for f in files if f.endswith(".rs")]
        return result
    result["kind"] = "code"
    pkgs = members(path)
    result["members"] = pkgs
    if not pkgs:
        result["all"] = True
        return result
    changed = set()
    for f in code:
        if f in EVERYTHING or f.endswith("Cargo.lock"):
            changed = set(pkgs)
            break
        owners = [(len(folder), name) for name, (folder, _) in pkgs.items()
                  if folder in ("", ".") or f == folder or f.startswith(folder + "/")]
        owners = [o for o in owners if o[0] > 0] or owners
        if f == "bundler.toml":
            owners = [(1, name) for name in pkgs if (path / "bundler.toml").exists()
                      and f"[{name}]" in (path / "bundler.toml").read_text(encoding="utf-8")]
        if owners:
            changed.add(max(owners)[1])
    reached, grew = set(changed), True
    while grew:
        grew = False
        for name, (_, uses) in pkgs.items():
            if name not in reached and uses & reached:
                reached.add(name)
                grew = True
    reached |= {f"{name}-host-tests" for name in reached if f"{name}-host-tests" in pkgs}
    result["reached"] = reached
    result["all"] = reached >= set(pkgs)
    return result


def least_commands(r):
    """The least a change needs, as commands."""
    if r["kind"] == "nothing":
        return []
    if r["kind"] == "docs":
        return []
    if r["kind"] == "comments":
        return [["rustfmt", "--edition", "2024", "--check", *r["rust"]]]
    # The fast tier only: `<plugin>-host-tests` (through MXM Player, with a bundle) is the slow tier,
    # run on purpose for an audible change, not by default. Without -p, cargo takes the
    # workspace's default members, which are the fast tier.
    fast = sorted(p for p in r["reached"] if not p.endswith("-host-tests"))
    pkgs = [] if r["all"] else [a for p in fast for a in ("-p", p)]
    return [["cargo", "fmt", "--all", "--", "--check"],
            ["cargo", "clippy", *pkgs, "--all-targets", "--", "-D", "warnings"],
            ["cargo", "test", *pkgs]]


def cmd_reach(args):
    for name, (group, path) in selected(args).items():
        if not (path / "Cargo.toml").exists():
            continue
        r = reach(path)
        if r["kind"] == "nothing":
            continue
        what = {"docs": "docs only: nothing to build or test",
                "comments": "comments only: rustfmt --check",
                "code": "every package" if r["all"] else ", ".join(sorted(r["reached"]))}[r["kind"]]
        print(f"{name}: {len(r['files'])} file(s) changed; reaches {what}")
        for command in least_commands(r):
            print("    " + " ".join(command))


def cmd_check(args):
    """fmt, clippy and the tests the change reaches, on this machine, in every changed repository.
    Windows only during the work (the owner, 2026-10-06); other platforms are a later batch."""
    if "--linux" in args:
        raise SystemExit("refused: Linux and macOS are checked later, together, when the owner asks "
                         "(2026-10-06: \"Just work on windows and then test the rest later\")")
    repos = selected(args)
    targets = repos if "--only" in args else changed(repos)
    results = []
    for name, (group, path) in targets.items():
        if not (path / "Cargo.toml").exists():
            continue
        r = reach(path)
        commands = least_commands(r)
        if not commands:
            print(f"{name}: {r['kind']}: nothing to build or test")
            continue
        print(f"\n=== {name}", flush=True)
        codes = []
        for command in commands:
            if command[0] == "cargo":
                command = [cargo_program(), *command[1:]]
            print(f"$ {' '.join(command)}", flush=True)
            codes.append(subprocess.run(command, cwd=path, env=cargo_env()).returncode)
        results.append((name, codes))
    if not results:
        print("nothing to check")
        return 0
    print("\n" + "\n".join(f"{n:24} {'ok' if not any(c) else 'FAILED ' + str(c)}" for n, c in results))
    return 1 if any(any(c) for _, c in results) else 0


def cmd_commit(args):
    if "-m" not in args:
        raise SystemExit('usage: python ws.py commit -m "message" [--only ...]')
    message = args[args.index("-m") + 1]
    for name, (group, path) in selected(args).items():
        if git(path, "status", "--porcelain"):
            subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", message], check=True)
            print(f"{name}: committed {git(path, 'rev-parse', '--short', 'HEAD')}")


def cmd_push(args):
    if linked():
        raise SystemExit("refused: the workspace is linked to local repositories (`python ws.py unlink` first), "
                         "so a Cargo.lock may name local paths")
    tags = "--tags" in args
    for name, (group, path) in selected(args).items():
        s = state(path)
        if s["upstream"] and s["ahead"]:
            r = subprocess.run(["git", "-C", str(path), "push", "-q"], capture_output=True, text=True)
            print(f"{name}: {'pushed ' + str(s['ahead']) + ' commit(s)' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}")
        if tags and s["upstream"]:
            # Only annotated tags reachable from the pushed branch: the ones `ws tag` makes.
            r = subprocess.run(["git", "-C", str(path), "push", "-q", "--follow-tags"],
                               capture_output=True, text=True)
            if r.returncode:
                print(f"{name}: tags FAILED {r.stderr.strip()}")


def cmd_tag(args):
    raise SystemExit("refused: no tags (the owner, 2026-10-07: \"Stop with all the tagging. It makes the "
                     "CI run... We are in pre-alpha and development speed is more important than "
                     "correctness.\"). Repositories follow each other's main; Cargo.lock pins the commit.")

def cmd_pull(args):
    def pull(item):
        name, (group, path) = item
        r = subprocess.run(["git", "-C", str(path), "pull", "-q", "--ff-only"], capture_output=True, text=True)
        return f"{name}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip().splitlines()[-1]}"
    with ThreadPoolExecutor(8) as pool:
        print("\n".join(pool.map(pull, [i for i in selected(args).items() if state(i[1][1])["upstream"]])))


def cmd_each(args):
    command = [a for a in args if a != "--only"]
    if "--only" in args:
        i = args.index("--only")
        command = args[:i] + args[i + 2:]
    failed = []
    for name, (group, path) in selected(args).items():
        print(f"\n=== {name}", flush=True)
        if subprocess.run(command, cwd=path, shell=os.name == "nt").returncode:
            failed.append(name)
    print(f"\nfailed in: {', '.join(failed)}" if failed else "\nok everywhere")


def crates_of(repo_path):
    """package name -> folder for every library a repository publishes (its `crates/` and `apps/`).
    Cargo warns once per build about a patched crate the repository doesn't use: that is expected."""
    out = {}
    for manifest in [*repo_path.glob("crates/*/Cargo.toml"), *repo_path.glob("apps/*/Cargo.toml")]:
        m = re.search(r'(?m)^\[package\][^\[]*?^name\s*=\s*"([^"]+)"', manifest.read_text(encoding="utf-8"))
        if m:
            out[m.group(1)] = manifest.parent
    return out


def cmd_link(args):
    names = [a for a in args if not a.startswith("--")] or ["kit"]
    repos = repositories()
    sources = {"kit": "mxm-kit", "player": "mxm-player"}
    if linked():
        raise SystemExit("already linked: `python ws.py unlink` first")
    lines = ["# Written by `python ws.py link`: every repository below builds against these local",
             "# repositories instead of their tags. `python ws.py unlink` removes this block; never push",
             "# while it is here (`ws push` refuses).", ""]
    forks = []
    for n in names:
        repo = sources.get(n, n)
        if repo not in repos:
            raise SystemExit(f"unknown repository: {n}")
        root = repos[repo][1]
        package = re.search(r'(?m)^\[package\][^\[]*?^name\s*=\s*"([^"]+)"',
                            (root / "Cargo.toml").read_text(encoding="utf-8"))
        if package and repo in GIT_FORKS:
            lines.append(f'[patch."{ORG}/{repo}"]')
            lines.append(f'{package.group(1)} = {{ path = "{root.as_posix()}" }}')
            lines.append("")
            continue
        if package:
            # A fork (nice-plug, egui-baseview) is one crate that replaces a crates.io release; every
            # repository's own [patch.crates-io] points at its tag, and this one takes precedence.
            forks.append(f'{package.group(1)} = {{ path = "{root.as_posix()}" }}')
            continue
        lines.append(f'[patch."{ORG}/{repo}"]')
        for crate, folder in sorted(crates_of(root).items()):
            lines.append(f'{crate} = {{ path = "{folder.as_posix()}" }}')
        lines.append("")
    if forks:
        lines += ["[patch.crates-io]", *forks, ""]
    # Remember which lockfiles were clean, so unlink can restore exactly those.
    clean = [name for name, (g, p) in repos.items()
             if (p / "Cargo.lock").exists() and not git(p, "status", "--porcelain", "Cargo.lock")]
    CONFIG.parent.mkdir(exist_ok=True)
    write(CONFIG, without_link() + BEGIN + "\n" + "\n".join(lines) + END + "\n")
    LINK_STATE.write_text(json.dumps({"linked": names, "clean_locks": clean}), encoding="utf-8")
    print(f"linked {', '.join(names)}: {CONFIG}")


def cmd_unlink(args):
    if not linked():
        print("not linked")
        return
    state_ = json.loads(LINK_STATE.read_text(encoding="utf-8")) if LINK_STATE.exists() else {"clean_locks": []}
    rest = without_link()
    if rest.strip():
        write(CONFIG, rest)
    else:
        CONFIG.unlink()
    LINK_STATE.unlink(missing_ok=True)
    repos = repositories()
    for name in state_["clean_locks"]:
        path = repos.get(name, (None, None))[1]
        if path and git(path, "status", "--porcelain", "Cargo.lock"):
            subprocess.run(["git", "-C", str(path), "checkout", "--", "Cargo.lock"], check=True)
            print(f"{name}: Cargo.lock restored")
    print("unlinked: every repository builds against its tags again")


def cmd_update(args):
    """Moves each selected repository's mxm-audio dependencies (kit, player, other products' crates,
    the forks) to their current main: removes only those packages from Cargo.lock and lets Cargo
    resolve them again, every crates.io package staying pinned. Runs from outside the workspace, so
    a `ws link` cannot put local paths into a lock. Update upstream first: forks, kit, player, the
    products whose crates others use, tools, then the rest."""
    neutral = Path(os.environ.get("TEMP", "/tmp"))
    for name, (group, path) in selected(args).items():
        lock = path / "Cargo.lock"
        if not lock.exists():
            continue
        blocks = re.split(r"(?m)^(?=\[\[)", lock.read_text(encoding="utf-8"))
        kept = [b for b in blocks
                if not (b.startswith("[[package]]") and f'source = "git+{ORG}/' in b)
                and not b.startswith("[[patch.unused]]")]
        write(lock, "".join(kept))
        r = subprocess.run([cargo_program(), "metadata", "--format-version", "1", "--quiet",
                            "--manifest-path", str(path / "Cargo.toml")],
                           cwd=neutral, env=cargo_env(), capture_output=True, text=True)
        print(f"{name}: {'relocked on main' if r.returncode == 0 else 'DOES NOT RESOLVE: ' + r.stderr.strip()[-200:]}")
        if unused_forks(path):
            print(f"  WARNING {name}: the {', '.join(unused_forks(path))} fork is unused in Cargo.lock "
                  f"(a newer upstream release won); refresh the fork first")

COMMANDS = {"clone": cmd_clone, "status": cmd_status, "tag": cmd_tag, "reach": cmd_reach, "check": cmd_check, "commit": cmd_commit, "push": cmd_push,
            "pull": cmd_pull, "each": cmd_each, "link": cmd_link, "unlink": cmd_unlink, "update": cmd_update}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]) or 0)
