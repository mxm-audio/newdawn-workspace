"""ws: work across every newDAWn and MXM repository from the workspace root.

The owner, 2026-10-06: "I want to work in this overarching folder. doing stuff repo by repo gets
tired real soon." Each repository stays standalone (a contributor clones one and needs none of
this); `ws` is how the workspace does the same step everywhere at once.

    python ws.py clone                       clone every repository in repos.txt that isn't here yet
    python ws.py status                      one row per repository: changes, unpushed, last commit, pins
    python ws.py reach                       what each changed repository's change reaches: the
                                             packages to test, or "docs only" / "comments only"
    python ws.py check                       fmt, clippy and the tests the change reaches, Windows
                                             only (other platforms are a later batch)
    python ws.py commit -m "message"         commit every changed repository with one message
    python ws.py push                        push every repository that is ahead (refused while linked)
    python ws.py tag                         refused: no tags (the owner, 2026-10-07)
    python ws.py pull                        fast-forward every repository
    python ws.py each <command ...>          run a command in every repository
    python ws.py link kit [player] [format] [nice-plug] [nice-plug-egui] [egui-baseview] [baseview]
                                             build against the local copies instead of their mains,
                                             for a change across repositories (a fork's version must
                                             match what each repository requires)
    python ws.py unlink                      back to the locked mains; restores the lockfiles `link` touched
    python ws.py update                      move each repository's mxm-audio dependencies to their
                                             current main and relock (no tags: the owner, 2026-10-07)
    python ws.py copy                        take each copy one repository keeps of another's folder
                                             again (COPIES), with its manifest: the web tracker's of
                                             newDAWn's tracker cases and songs, newDAWn's of its songs
    python ws.py install                     bundle every plugin (release) as checked out and install
                                             it, CLAP and VST3, in the standard plugin folders (or
                                             MXM_CLAP_DIR, MXM_VST3_DIR); --only narrows it to some
                                             plugins. A machine catches up with `pull`, then `install`

`update` and `install` fetch first and refuse a repository whose checkout is behind its upstream.

Every command takes --only <name,...>: repository names, or the groups newdawn, kit (= mxm-kit),
forks (nice-plug, nice-plug-egui, egui-baseview, baseview), player, format (= tutti), instruments,
effects, plugins (= instruments + effects), tools, apps (the web tracker), ops, all (the default).
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORG = "https://github.com/mxm-audio"
REPO_LIST = ROOT / "repos.txt"
CONFIG = ROOT / ".cargo" / "config.toml"
LINK_STATE = ROOT / ".cargo" / "ws-link.json"
GROUPS = ["newdawn", "kit", "player", "format", "instruments", "effects", "tools", "apps", "ops"]
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
    tutti = re.search(r'mxm-audio/tutti\?[^#"]*#([0-9a-f]{7})', text)
    return {"dirty": len(dirty), "ahead": int(ahead or 0), "behind": int(behind or 0), "head": head or "-",
            "kit": kit.group(1) if kit else "-", "player": player.group(1) if player else "-",
            "tutti": tutti.group(1) if tutti else "-",
            "upstream": bool(git(path, "rev-parse", "--abbrev-ref", "@{u}"))}


FORKS = ("nice-plug", "nice-plug-egui", "egui-baseview", "baseview")
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


# Folders one repository keeps a copy of from another, the copy beside a `MANIFEST.json` naming
# the commit it came from and the hash of what it copied: `status` warns when the source has moved
# on, and `copy` takes them again. The web tracker's copy of newDAWn's tracker cases (the owner,
# 2026-10-21: the two trackers kept in sync, interface and features), and the round trip's songs
# (newDAWn's `plans/plan-web-tracker.md`, W7): the web tracker's to newDAWn, newDAWn's back.
COPIES = [
    ("newdawn/tests/tracker-cases", "apps/mxm-tracker/tests/tracker-cases"),
    ("apps/mxm-tracker/fixtures/to-newdawn", "newdawn/tests/web-tracker-songs/to-newdawn"),
    ("newdawn/tests/web-tracker-songs/from-newdawn", "apps/mxm-tracker/fixtures/from-newdawn"),
]


def folder_hash(folder):
    """A folder's hash as `COPIES` compares it: SHA-256 over its files but `MANIFEST.json`, in the
    order of their paths from the folder (with /), each as its path, a NUL, its bytes with CRLF as
    LF and a NUL, so a checkout's line ends never count. The copying side computes the same."""
    digest = hashlib.sha256()
    files = [p for p in folder.rglob("*") if p.is_file() and p.name != "MANIFEST.json"]
    for path in sorted(files, key=lambda p: p.relative_to(folder).as_posix()):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def stale_copies():
    """The (source, copy) pairs of `COPIES` whose copy's manifest names another hash than the
    source has now; none where either side isn't here."""
    for source, copy in COPIES:
        manifest = ROOT / copy / "MANIFEST.json"
        if not (ROOT / source).is_dir() or not manifest.exists():
            continue
        if json.loads(manifest.read_text(encoding="utf-8")).get("hash") != folder_hash(ROOT / source):
            yield source, copy


def cmd_copy(args):
    """Takes each copy of `COPIES` again whose source is here: the copy emptied, the source's files
    copied whole, and a manifest naming the commit that last changed the source (and whether it
    had uncommitted changes there) and its hash."""
    paths = [p for _, p in repositories().values() if p.is_dir()]
    for source, copy in COPIES:
        repo = next((p for p in paths if (ROOT / source).is_relative_to(p)), None)
        if not (ROOT / source).is_dir() or repo is None or not any((ROOT / copy).is_relative_to(p) for p in paths):
            continue
        # The commit that last changed the source, so a commit elsewhere in its repository leaves
        # the manifest as it is.
        where = (ROOT / source).relative_to(repo).as_posix()
        commit = git(repo, "log", "-1", "--format=%H", "--", where) or git(repo, "rev-parse", "HEAD")
        dirty = bool(git(repo, "status", "--porcelain", "--", where))
        shutil.rmtree(ROOT / copy, ignore_errors=True)
        shutil.copytree(ROOT / source, ROOT / copy, ignore=shutil.ignore_patterns("MANIFEST.json"))
        manifest = {"from": commit, "hash": folder_hash(ROOT / source)}
        if dirty:
            manifest["uncommitted"] = True
        text = json.dumps(manifest, indent=2) + chr(10)
        (ROOT / copy / "MANIFEST.json").write_bytes(text.encode("utf-8"))
        print(f"{copy}: from {source} at {commit[:7]}{' (with uncommitted changes)' if dirty else ''}")


def changed(repos):
    with ThreadPoolExecutor(8) as pool:
        states = dict(zip(repos, pool.map(lambda r: state(r[1]), repos.values())))
    return {n: v for n, v in repos.items() if states[n]["dirty"] or states[n]["ahead"]}


def behind(item):
    """(refuse, why) for one repository, fetched: refuse when its checkout is behind its upstream,
    because another clone pushed and this one hasn't pulled. Relocking or building it would pair
    its old code with the new mains (2026-10-15: the audit session pushed from another clone, a
    relock of the old checkouts stopped chorus-06 and folded-spring building, and `install` had
    installed the old plugins). One that can't be fetched is refused if its last fetch shows it
    behind, and otherwise only warned about."""
    name, (group, path) = item
    # The branch's configured remote, not `@{u}`: that doesn't resolve before a first fetch.
    branch = git(path, "symbolic-ref", "-q", "--short", "HEAD")
    if not branch or not git(path, "config", f"branch.{branch}.remote"):
        return name, (False, "")
    # Offline, the last fetch still says whether it is behind: refused then too.
    fetched = subprocess.run(["git", "-C", str(path), "fetch", "-q"], capture_output=True).returncode == 0
    unknown = "" if fetched else "it can't be fetched, so it may be behind its upstream"
    if not git(path, "rev-parse", "--abbrev-ref", "@{u}"):
        return name, (False, unknown or "its upstream branch isn't on its remote")
    later = int(git(path, "rev-list", "--count", "HEAD..@{u}") or 0)
    own = int(git(path, "rev-list", "--count", "@{u}..HEAD") or 0)
    when = "" if fetched else " as of its last fetch"
    if not later:
        return name, (False, unknown)
    if own:
        return name, (True, f"it has diverged from its upstream{when} ({own} ahead, {later} behind): merge it first")
    return name, (True, f"it is {later} behind its upstream{when}: `python ws.py pull --only {name}` first")


def refuse_behind(repos):
    """Fetches the repositories, says which are behind or couldn't be fetched, and returns the names
    of those refused."""
    with ThreadPoolExecutor(8) as pool:
        found = dict(pool.map(behind, repos.items()))
    for name, (refuse, why) in found.items():
        if why:
            print(f"{name}: {'REFUSED' if refuse else 'WARNING'}: {why}", flush=True)
    return {name for name, (refuse, why) in found.items() if refuse}


# --- commands -----------------------------------------------------------------------------------

def cmd_status(args):
    repos = selected(args)
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda item: (item[0], item[1][0], state(item[1][1])), repos.items()))
    print(f"{'repository':24} {'group':12} {'status':11} {'changed':>7} {'ahead':>5} {'behind':>6}  "
          f"{'last commit':19} {'kit':8} {'player':8} tutti")
    for name, group, s in rows:
        flag = "" if s["upstream"] else "  (no remote)"
        print(f"{name:24} {group:12} {status_of(repos[name][1]):11} {s['dirty'] or '':>7} "
              f"{s['ahead'] or '':>5} {s['behind'] or '':>6}  {s['head']:19} {s['kit']:8} {s['player']:8} "
              f"{s['tutti']}{flag}")
    shadowed = {name: unused_forks(path) for name, (group, path) in repos.items() if unused_forks(path)}
    for name, forks in shadowed.items():
        print(f"\nWARNING {name}: Cargo.lock does not use the {', '.join(forks)} fork (a newer upstream "
              f"release won): refresh the fork onto it, then relock. See the fork's PATCHES.md.")
    for source, copy in stale_copies():
        print(f"\nWARNING {copy} differs from {source}, which it copies: copy it again (its "
              f"repository's AGENTS.md says how), and bring what changed into it.")
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
    sources = {"kit": "mxm-kit", "player": "mxm-player", "format": "tutti"}
    if linked():
        raise SystemExit("already linked: `python ws.py unlink` first")
    lines = ["# Written by `python ws.py link`: every repository below builds against these local",
             "# repositories instead of their mains. `python ws.py unlink` removes this block; never push",
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
    crates = sorted(re.findall(r'(?m)^([\w-]+) = \{ path = ', "\n".join(lines + forks)))
    LINK_STATE.write_text(json.dumps({"linked": names, "clean_locks": clean, "crates": crates}),
                          encoding="utf-8")
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
    # A lockfile already changed when linked isn't restored, so its other change survives; say so
    # if the link is still in it (the kit's, 2026-10-16, found by the session whose change it was).
    linked_crates = set(state_.get("crates", []))
    for name, (_, path) in repos.items():
        lock = path / "Cargo.lock"
        if name in state_["clean_locks"] or not linked_crates or not lock.exists():
            continue
        own = set(crates_of(path))
        manifest = path / "Cargo.toml"
        root = manifest.exists() and re.search(r'(?m)^\[package\][^\[]*?^name\s*=\s*"([^"]+)"',
                                               manifest.read_text(encoding="utf-8"))
        if root:
            own.add(root.group(1))
        left = link_residue(lock.read_text(encoding="utf-8"), linked_crates - own)
        if left:
            print(f"{name}: Cargo.lock was already changed when linked and still carries the link "
                  f"({', '.join(left)} without a source): drop those hunks (`git diff Cargo.lock`)")
    print("unlinked: every repository builds against its locked mains again")


def link_residue(lock_text, crates):
    """The `crates` a Cargo.lock lists without a `source`: there only while a `ws link` patches them
    in by path, since every one of them belongs to another repository."""
    left = set()
    for block in lock_text.split("[[package]]")[1:]:
        name = re.search(r'(?m)^name = "([^"]+)"', block)
        if name and name.group(1) in crates and not re.search(r"(?m)^source = ", block):
            left.add(name.group(1))
    return sorted(left)


def cmd_update(args):
    """Moves each selected repository's mxm-audio dependencies (kit, player, other products' crates,
    the forks) to their current main: removes only those packages from Cargo.lock and lets Cargo
    resolve them again, every crates.io package staying pinned. Runs from outside the workspace, so
    a `ws link` cannot put local paths into a lock. Update upstream first: forks, kit, player,
    format, the products whose crates others use, tools, then the rest. A repository behind its upstream is
    refused, and the exit is nonzero if any is refused or doesn't resolve."""
    neutral = Path(os.environ.get("TEMP", "/tmp"))
    repos = selected(args)
    refused = refuse_behind(repos)
    failed = bool(refused)
    for name, (group, path) in repos.items():
        lock = path / "Cargo.lock"
        if name in refused or not lock.exists():
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
        failed = failed or r.returncode != 0
        if unused_forks(path):
            print(f"  WARNING {name}: the {', '.join(unused_forks(path))} fork is unused in Cargo.lock "
                  f"(a newer upstream release won); refresh the fork first")
    return 1 if failed else 0


# --- installing the plugins -------------------------------------------------------------------
#
# The owner, 2026-10-12: "The idea is to have a unified key language in the daw and in the
# plugins." A plugin carries the language it was built with, so a machine that pulled the
# repositories still runs old plugins until they are built and installed again: `install` is that
# step, for every plugin at once. Since 2026-10-13 every `cargo xtask bundle` installs its plugin
# too, in a plugin locked on a kit that has it; `install` still builds the ones nobody bundled.

def plugin_folder(fmt):
    """Where `fmt`, "CLAP" or "VST3", installs: the folder MXM_CLAP_DIR or MXM_VST3_DIR names, else
    the one everyone uses, as mxm-kit's `mxm_xtask::install::folder` (the owner, 2026-10-16: "Lets
    keep it as standard as possible"): on Windows the system's, which every host reads unconfigured
    and which this user is given write access to once; on macOS and Linux this user's."""
    named = os.environ.get(f"MXM_{fmt}_DIR")
    if named:
        return Path(named)
    if os.name == "nt":
        return Path(os.environ["COMMONPROGRAMFILES"]) / fmt
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Audio" / "Plug-Ins" / fmt
    return Path.home() / f".{fmt.lower()}"


def retired_clap_folder():
    """This user's CLAP folder on Windows, where installs went before the system folder: an MXM
    plugin's copy there goes once its install elsewhere has worked, or hosts list it twice."""
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Common" / "CLAP"
    return None


def scan_order(fmt):
    """The folders newDAWn scans for `fmt`, in its order (its `catalog::standard_folders` and
    `mxm_vst3_host::standard_folders`): a plugin found twice keeps its first bundle."""
    folders = [Path(p) for p in os.environ.get(f"{fmt}_PATH", "").split(os.pathsep) if p]
    if os.name == "nt":
        folders += [Path(os.environ["COMMONPROGRAMFILES"]) / fmt,
                    Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Common" / fmt]
    elif sys.platform == "darwin":
        user = Path.home() / "Library" / "Audio" / "Plug-Ins" / fmt
        system = Path("/Library/Audio/Plug-Ins") / fmt
        folders += ([system, user] if fmt == "CLAP"
                    else [user, system, Path("/Network/Library/Audio/Plug-Ins/VST3")])
    else:
        folders.append(Path.home() / f".{fmt.lower()}")
        folders += ([Path("/usr/lib/clap")] if fmt == "CLAP"
                    else [Path("/usr/lib/vst3"), Path("/usr/local/lib/vst3")])
    return folders


def resolved(path):
    """`path` as the file system resolves it (`..`, case, junctions), or as written."""
    try:
        return path.resolve(strict=True)
    except OSError:
        return path


def scanning_root(folder, order):
    """Which of newDAWn's scan roots holds `folder`: the first that is it or one of its parents."""
    folder = resolved(folder)
    for at, root in enumerate(order):
        root = resolved(root)
        if folder == root or root in folder.parents:
            return at
    return None


def found_first(fmt, installed):
    """Every other bundle of `installed`'s name newDAWn finds before it, as mxm-kit's
    `mxm_xtask::install::found_first`: in the folders it scans before the one holding `installed`,
    and in that one, whose bundles it takes in sorted order."""
    order = scan_order(fmt)
    at = scanning_root(installed.parent, order)
    if at is None:
        return []
    found = [copy for root in order[:at] for copy in copies_in(root, installed.name)]
    found += [copy for copy in copies_in(order[at], installed.name)
              if resolved(copy) < resolved(installed)]
    # Never the installed bundle itself, which an earlier root can reach through a junction.
    return [copy for copy in found if resolved(copy) != resolved(installed)]


def same_folder(a, b):
    """Whether `a` and `b` may be one folder: told apart only when both exist and differ on disk,
    so an install is never taken back out through another spelling of its own folder."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return True


def copies_in(folder, name):
    """Every `name` in `folder` and its subfolders, which newDAWn's scan goes into as well, but not
    into a `.vst3` bundle, whose module carries the bundle's name."""
    found = []
    try:
        for entry in folder.iterdir():
            if entry.name == name:
                found.append(entry)
            elif entry.is_dir() and entry.suffix != ".vst3":
                found += copies_in(entry, name)
    except OSError:
        pass
    return found


def bundles_of(path):
    """(package, bundle name) for each section of a repository's `bundler.toml`."""
    out = []
    for line in (path / "bundler.toml").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        section = re.fullmatch(r'\[\s*"?([^\]"]+)"?\s*\]', line)
        if section:
            out.append([section.group(1), section.group(1)])
            continue
        name = re.fullmatch(r'name\s*=\s*"([^"]+)"', line)
        if name and out:
            out[-1][1] = name.group(1)
    return [tuple(pair) for pair in out]


def remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def set_aside(path):
    """Renames what is at `path`, if anything, to `<name>.<stamp>.old` beside it, which Windows
    allows for a plugin a host holds where replacing or removing it doesn't. Returns where it went."""
    if not os.path.lexists(path):
        return None
    aside = path.with_name(f"{path.name}.{time.time_ns()}.old")
    path.rename(aside)
    return aside


def disarm(folder):
    """Renames every `.vst3` or `.clap` inside a bundle set aside, at any depth, to `….old`, as
    mxm-kit's `mxm_xtask::install` does: a host looks for plugins at any depth, and the module inside
    a `.vst3` bundle is itself named `<name>.vst3` (Ableton Live 11 loaded one from a set-aside
    bundle, 2026-10-16). A loaded module may be renamed, though not replaced or removed."""
    if not folder.is_dir():
        return
    for entry in list(folder.iterdir()):
        if entry.is_dir():
            disarm(entry)
        if entry.suffix in (".vst3", ".clap"):
            try:
                entry.rename(entry.with_name(entry.name + ".old"))
            except OSError:
                pass


def clear_leftovers(destination):
    """What installs of `destination` left beside it: a cut-off copy, and every copy set aside that
    nothing holds any more. One a host still holds stays for a later install."""
    for left in [destination.with_name(destination.name + ".tmp"),
                 destination.with_name(destination.name + ".new"),
                 *destination.parent.glob(glob.escape(destination.name) + ".*.old")]:
        try:
            remove(left)
        except OSError:
            pass


def place(source, destination):
    """Copies a file or a bundle folder over `destination` whole: beside it first, then renamed in,
    so a host never finds half of one and an old bundle is never merged into. A copy a host holds
    is renamed aside first, as mxm-kit's `mxm_xtask::install` does, and goes at a later install."""
    clear_leftovers(destination)
    fresh = destination.with_name(destination.name + (".new" if source.is_dir() else ".tmp"))
    try:
        if source.is_dir():
            shutil.copytree(source, fresh, symlinks=True)
        else:
            shutil.copyfile(source, fresh)
        try:
            os.replace(fresh, destination)
        except OSError:
            aside = set_aside(destination)
            try:
                os.replace(fresh, destination)
            except OSError:
                # What was installed goes back: a failed install leaves it.
                if aside:
                    aside.rename(destination)
                raise
            if aside:
                try:
                    remove(aside)
                except OSError:
                    disarm(aside)  # a host holds it: it goes at a later install
    finally:
        try:
            remove(fresh)
        except OSError:
            pass


def retire(bundle, folder):
    """Takes `bundle`'s own CLAP and control map out of `folder`, by exact name, once it is
    installed elsewhere; one a host holds is set aside as `.old`, which no host lists. Returns what
    is still there."""
    left = []
    for name in (f"{bundle}.clap", f"{bundle}.control-map.json"):
        path = folder / name
        clear_leftovers(path)
        try:
            remove(path)
        except OSError:
            try:
                set_aside(path)
            except OSError:
                left.append(path)
    return left


def cmd_install(args):
    """Bundles each plugin repository's plugins (release, from what is checked out) into one shared
    target folder, so what they share compiles once, and installs each one that built, CLAP and
    VST3, in the plugin folders (`plugin_folder`). Goes on past a failure and says, per plugin,
    installed or why not. A repository behind its upstream is refused before anything builds."""
    plugins = {n: v for n, v in repositories().items() if v[0] in ("instruments", "effects")}
    if "--only" in args:
        only = args[args.index("--only") + 1].split(",")
        others = [o for o in only if o not in plugins and o not in ("instruments", "effects", "plugins")]
        if others:
            raise SystemExit(f"refused: install builds the plugins only, not {', '.join(others)}")
        plugins = {n: v for n, v in selected(args).items() if n in plugins}
    if linked():
        print(f"LINKED: the builds use the local repositories named in {CONFIG}")
    target = ROOT / "target-shared"
    # It installs each plugin itself, below, whichever kit the plugin is locked on: the kit's xtask
    # installing a bundle too (mxm-kit's `mxm-xtask`, 2026-10-13) would copy it twice.
    env = {**cargo_env(), "CARGO_TARGET_DIR": str(target), "MXM_INSTALL_CLAP": "0"}
    destinations = {fmt: plugin_folder(fmt) for fmt in ("CLAP", "VST3")}
    retired = retired_clap_folder()
    results, hidden, left_behind = [], [], []
    refused = refuse_behind(plugins)
    for name, (group, path) in plugins.items():
        if name in refused:
            results.append((name, "NOT INSTALLED: behind its upstream, pull it first"))
            continue
        if not (path / "bundler.toml").exists():
            continue
        for package, bundle in bundles_of(path):
            built = target / "bundled" / f"{bundle}.clap"
            built_vst3 = target / "bundled" / f"{bundle}.vst3"
            control_map = path / "target" / "bundled" / f"{bundle}.control-map.json"
            print(f"\n=== {bundle} ({name})", flush=True)
            # Only a fresh build is installed: what an earlier one left goes first.
            try:
                remove(built)
                remove(built_vst3)
                remove(control_map)
            except OSError as error:
                results.append((bundle, f"NOT INSTALLED: the last build's output can't be removed: "
                                        f"{error}"))
                continue
            # `cargo xtask` with the alias every repository defines, but its own target folder:
            # each repository's xtask is a binary named `xtask` that compiles its own root in, and
            # in one shared folder one repository's would run for another's (2026-10-12, staging
            # mono-01's control map for poly-06). The plugin itself builds in the shared folder.
            command = [cargo_program(), "run", "--package", "xtask", "--release",
                       "--target-dir", str(path / "target"), "--", "bundle", package, "--release"]
            print(f"$ {' '.join(command)}", flush=True)
            code = subprocess.run(command, cwd=path, env=env).returncode
            if code or not built.exists():
                results.append((bundle, "NOT INSTALLED: the build failed"))
                continue
            destination = destinations["CLAP"]
            try:
                destination.mkdir(parents=True, exist_ok=True)
                place(built, destination / built.name)
            except OSError as error:
                results.append((bundle, f"NOT INSTALLED: {error}. Close the hosts using it, or give "
                                        "this user write access to that folder, and run install "
                                        "again"))
                continue
            hidden += found_first("CLAP", destination / built.name)
            if retired and not same_folder(retired, destination):
                left_behind += retire(bundle, retired)
            problems = []
            # Its control map beside it, or none rather than an older one; said if even that fails.
            installed_map = destination / control_map.name
            try:
                if control_map.exists():
                    place(control_map, installed_map)
                else:
                    remove(installed_map)
            except OSError as error:
                try:
                    remove(installed_map)
                except OSError:
                    pass
                left = "an older one is still beside it" if installed_map.exists() else "it has none"
                problems.append(f"NOT ITS CONTROL MAP ({left}): {error}")
            formats = "CLAP"
            if built_vst3.exists():
                try:
                    destinations["VST3"].mkdir(parents=True, exist_ok=True)
                    place(built_vst3, destinations["VST3"] / built_vst3.name)
                    formats = "CLAP and VST3"
                    hidden += found_first("VST3", destinations["VST3"] / built_vst3.name)
                except OSError as error:
                    problems.append(f"NOT ITS VST3: {error}")
            results.append((bundle, f"installed, {formats}" if not problems else
                            f"INSTALLED, BUT {'; '.join(problems)}. Run install again"))
    if not results:
        print("nothing to install")
        return 0
    print("\n" + "\n".join(f"{bundle:24} {what}" for bundle, what in results))
    if any(what.startswith(("installed", "INSTALLED")) for _, what in results):
        print(f"\nInstalled in {destinations['CLAP']} and {destinations['VST3']}. Restart newDAWn "
              "to load them; other hosts find them at their next scan.")
    for copy in hidden:
        print(f"WARNING: {copy} is found before the one installed, so newDAWn loads it instead: "
              "remove it (that folder may need an administrator)")
    for left in left_behind:
        print(f"WARNING: the older copy {left} couldn't be removed, so hosts reading that folder "
              "list the plugin twice: remove it once nothing holds it")
    return 1 if any(not what.startswith("installed") for _, what in results) else 0


COMMANDS = {"clone": cmd_clone, "status": cmd_status, "tag": cmd_tag, "reach": cmd_reach, "check": cmd_check, "commit": cmd_commit, "push": cmd_push,
            "pull": cmd_pull, "each": cmd_each, "link": cmd_link, "unlink": cmd_unlink, "update": cmd_update,
            "install": cmd_install, "copy": cmd_copy}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]) or 0)
