"""ws: work across every newDAWn and MXM repository from the workspace root.

The owner, 2026-10-06: "I want to work in this overarching folder. doing stuff repo by repo gets
tired real soon." Each repository stays standalone (a contributor clones one and needs none of
this); `ws` is how the workspace does the same step everywhere at once.

    python ws.py clone                       clone every repository in repos.txt that isn't here yet
    python ws.py status                      one row per repository: changes, unpushed, tag, pins
    python ws.py check [--linux]             fmt, clippy -D warnings and the fast tests, only where
                                             something changed (uncommitted or unpushed); --linux
                                             also runs them in WSL
    python ws.py commit -m "message"         commit every changed repository with one message
    python ws.py push [--tags]               push every repository that is ahead (refused while linked);
                                             --tags also publishes the tags `ws tag` made
    python ws.py tag <version>               tag HEAD where repos.txt says `released`; refuses the rest
    python ws.py pull                        fast-forward every repository
    python ws.py each <command ...>          run a command in every repository
    python ws.py link kit [player] [nice-plug] [egui-baseview]
                                             build against the local copies instead of their tags,
                                             for a change across repositories (a fork's version must
                                             match what each repository requires)
    python ws.py unlink                      back to the tags; restores the lockfiles `link` touched
    python ws.py bump kit|player <tag>       move every dependent repository to a new tag and relock

Every command takes --only <name,...>: repository names, or the groups newdawn, kit, player,
instruments, effects, plugins (= instruments + effects), tools, ops, all (the default).
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
                    out[path.name] = (group, path)
    if (ROOT / "ops" / ".git").exists():
        out["ops"] = ("ops", ROOT / "ops")
    return out


def listed():
    """folder -> (clone URL, status), from repos.txt. A repository without `released` is
    unreleased: `ws tag` refuses it, so a forgotten status can only hold a release back."""
    out = {}
    for line in REPO_LIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            folder, url, *rest = line.split()
            out[folder] = (url, rest[0] if rest else "unreleased")
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
    unknown = [o for o in only if o not in repos and o not in GROUPS + ["plugins", "all"]]
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
    tag = git(path, "describe", "--tags", "--abbrev=0")
    manifest = path / "Cargo.toml"
    text = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
    kit = re.search(r'mxm-kit", tag = "([^"]+)"', text)
    player = re.search(r'mxm-player", tag = "([^"]+)"', text)
    return {"dirty": len(dirty), "ahead": int(ahead or 0), "behind": int(behind or 0), "tag": tag or "-",
            "kit": kit.group(1) if kit else "-", "player": player.group(1) if player else "-",
            "upstream": bool(git(path, "rev-parse", "--abbrev-ref", "@{u}"))}


FORKS = ("nice-plug", "egui-baseview")


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
          f"{'tag':12} {'kit':8} player")
    for name, group, s in rows:
        flag = "" if s["upstream"] else "  (no remote)"
        print(f"{name:24} {group:12} {status_of(repos[name][1]):11} {s['dirty'] or '':>7} "
              f"{s['ahead'] or '':>5} {s['behind'] or '':>6}  {s['tag']:12} {s['kit']:8} {s['player']}{flag}")
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


def cmd_check(args):
    repos = selected(args)
    targets = repos if "--only" in args else changed(repos)
    if not targets:
        print("nothing changed: no repository has uncommitted or unpushed work")
        return 0
    linux = "--linux" in args
    results = []
    for name, (group, path) in targets.items():
        if not (path / "Cargo.toml").exists():
            continue
        print(f"\n=== {name}", flush=True)
        steps = [["cargo", "fmt", "--all", "--", "--check"],
                 ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"],
                 ["cargo", "test"]]
        codes = [run_in(path, step) for step in steps]
        if linux:
            script = f"/mnt/{ROOT.drive[0].lower()}{ROOT.as_posix()[2:]}/wsl/linux-check.sh"
            repo = f"/mnt/{path.drive[0].lower()}{path.as_posix()[2:]}"
            codes += [run_in(path, ["wsl", "-d", "archlinux", "--", "bash", script, repo, what])
                      for what in ("clippy", "test")]
        results.append((name, codes))
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
    """Tag HEAD in every selected repository that repos.txt marks `released`. Refuses the rest,
    and any repository with uncommitted work. `ws push --tags` publishes them."""
    words = [a for a in args if not a.startswith("--")]
    if "--only" in args:
        words.remove(args[args.index("--only") + 1])
    if len(words) != 1 or not re.fullmatch(r"v?\d+\.\d+\.\d+(-[\w.]+)?", words[0]):
        raise SystemExit("usage: python ws.py tag <version, e.g. v0.1.1> --only <names>")
    tag = words[0]
    for name, (group, path) in selected(args).items():
        status = status_of(path)
        if status != "released":
            print(f"{name}: refused, {status} in repos.txt")
            continue
        if git(path, "status", "--porcelain"):
            print(f"{name}: refused, uncommitted work")
            continue
        r = subprocess.run(["git", "-C", str(path), "tag", "-a", tag, "-m", tag], capture_output=True, text=True)
        print(f"{name}: {'tagged ' + tag if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}")


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


def cmd_bump(args):
    if len(args) < 2:
        raise SystemExit("usage: python ws.py bump kit|player <tag> [--only ...]")
    source = {"kit": "mxm-kit", "player": "mxm-player"}.get(args[0], args[0])
    tag = args[1]
    pattern = re.compile(rf'({re.escape(ORG)}/{re.escape(source)}", tag = )"[^"]+"')
    for name, (group, path) in selected(args[2:]).items():
        manifest = path / "Cargo.toml"
        if not manifest.exists() or name == source:
            continue
        text = manifest.read_text(encoding="utf-8")
        new = pattern.sub(rf'\1"{tag}"', text)
        if new == text:
            continue
        write(manifest, new)
        r = subprocess.run(["cargo", "metadata", "--format-version", "1", "--quiet"], cwd=path,
                           capture_output=True, text=True)
        print(f"{name}: {source} -> {tag}, {'relocked' if r.returncode == 0 else 'DOES NOT RESOLVE: ' + r.stderr.strip()[-200:]}")
        if unused_forks(path):
            print(f"  WARNING {name}: the {', '.join(unused_forks(path))} fork is unused in Cargo.lock "
                  f"(a newer upstream release won); refresh the fork before releasing")


COMMANDS = {"clone": cmd_clone, "status": cmd_status, "tag": cmd_tag, "check": cmd_check, "commit": cmd_commit, "push": cmd_push,
            "pull": cmd_pull, "each": cmd_each, "link": cmd_link, "unlink": cmd_unlink, "bump": cmd_bump}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]) or 0)
