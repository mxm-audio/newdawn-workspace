"""Tests of ws.py's install and release of a plugin, on temporary folders only: never a plugin
folder a host reads, never C:. Standard library only; from the workspace root:

    python -I ws_test.py
"""
import importlib.util
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# `-I` leaves the script's folder off the path, so ws.py is loaded from beside this file.
_spec = importlib.util.spec_from_file_location("ws", HERE / "ws.py")
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)

# In the workspace's shared build folder, which git ignores, and not the system's temporary folder,
# which is on C:.
SCRATCH = HERE / "target-shared" / "ws-test"
BUNDLE = "MXM Test"
CLAP, MAP, PRESETS, VST3 = (f"{BUNDLE}.clap", f"{BUNDLE}.control-map.json", f"{BUNDLE}.presets",
                            f"{BUNDLE}.vst3")
MODULE = f"{VST3}/Contents/x86_64-win/{VST3}"


def write_files(folder, files):
    """`files`, {relative path: text}, written under `folder` byte for byte."""
    for relative, text in files.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def contents(folder):
    """{relative path: text} of every file under `folder`."""
    return {p.relative_to(folder).as_posix(): p.read_bytes().decode("utf-8")
            for p in sorted(folder.rglob("*")) if p.is_file()}


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def archived(archive):
    """{path: text} of every file in a release archive, a zip or a tarball."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zipped:
            return {n: zipped.read(n).decode("utf-8") for n in zipped.namelist() if not n.endswith("/")}
    with tarfile.open(archive) as tarball:
        return {m.name: tarball.extractfile(m).read().decode("utf-8")
                for m in tarball.getmembers() if m.isfile()}


def tearDownModule():
    try:
        SCRATCH.rmdir()
    except OSError:
        pass


class Scratch(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=SCRATCH))
        self.addCleanup(shutil.rmtree, self.root, True)
        # Where the plugin builds (the shared target) and where its xtask stages beside it.
        self.bundled = self.root / "target-shared" / "bundled"
        self.staged = self.root / "repository" / "target" / "bundled"
        self.destinations = {"CLAP": self.root / "CLAP", "VST3": self.root / "VST3"}
        self.clap = self.destinations["CLAP"]

    def build(self, presets=None):
        """A build as `cargo xtask bundle` leaves one, after `install` took the last one's output
        away: CLAP, VST3, control map, and `presets` ({file: text}) when it has any."""
        for stale in ws.outputs(BUNDLE, self.bundled, self.staged):
            ws.remove(stale)
        write_files(self.bundled, {CLAP: "clap", MODULE: "vst3"})
        write_files(self.staged, {MAP: "{}"})
        if presets is not None:
            write_files(self.staged / PRESETS, presets)

    def install(self):
        return ws.install_built(BUNDLE, self.bundled, self.staged, self.destinations)


class Install(Scratch):
    def test_places_the_presets_beside_the_clap(self):
        self.build({"a.json": "A", "order.txt": "a.json\n"})
        what, installed = self.install()
        self.assertEqual(what, "installed, CLAP and VST3")
        self.assertEqual(installed, [("CLAP", self.clap / CLAP), ("VST3", self.destinations["VST3"] / VST3)])
        self.assertEqual(names(self.clap), [CLAP, MAP, PRESETS])
        self.assertEqual(contents(self.clap / PRESETS), {"a.json": "A", "order.txt": "a.json\n"})
        # Nothing goes beside the VST3, which carries its presets inside.
        self.assertEqual(names(self.destinations["VST3"]), [VST3])

    def test_over_an_older_set_leaves_exactly_the_new_one(self):
        self.build({"a.json": "old A", "dropped.json": "D", "order.txt": "a.json\ndropped.json\n"})
        self.install()
        self.build({"a.json": "new A", "b.json": "B", "order.txt": "a.json\nb.json\n"})
        what, _ = self.install()
        self.assertEqual(what, "installed, CLAP and VST3")
        self.assertEqual(contents(self.clap / PRESETS),
                         {"a.json": "new A", "b.json": "B", "order.txt": "a.json\nb.json\n"})
        # Nor is a copy left beside it: the one put in (`.new`) or the one taken out (`.old`).
        self.assertEqual(names(self.clap), [CLAP, MAP, PRESETS])

    def test_a_build_with_no_presets_takes_the_installed_ones_out(self):
        self.build({"a.json": "A"})
        self.install()
        self.build()
        what, _ = self.install()
        self.assertEqual(what, "installed, CLAP and VST3")
        self.assertEqual(names(self.clap), [CLAP, MAP])


class Retire(Scratch):
    def test_takes_the_presets_out_of_the_older_folder(self):
        older = self.root / "older CLAP"
        write_files(older, {CLAP: "clap", MAP: "{}", f"{PRESETS}/a.json": "A",
                            "Other.presets/a.json": "another plugin's"})
        self.assertEqual(ws.retire(BUNDLE, older), [])
        self.assertEqual(contents(older), {"Other.presets/a.json": "another plugin's"})


class Release(Scratch):
    def test_the_archive_holds_the_presets_beside_the_clap(self):
        self.build({"a.json": "A", "order.txt": "a.json\n"})
        out = self.root / "release"
        out.mkdir()
        stem = f"{BUNDLE}-1.0.0-test"
        signed_with = []

        def sign(clap, vst3):
            signed_with.append((clap.name, vst3.name))
            return "test"

        archive, signed = ws.pack_plugin(BUNDLE, self.bundled, self.staged, out, stem, sign=sign)
        self.assertEqual((signed, signed_with), ("test", [(CLAP, VST3)]))
        self.assertEqual(archived(archive), {f"{stem}/{CLAP}": "clap", f"{stem}/{MAP}": "{}",
                                             f"{stem}/{PRESETS}/a.json": "A",
                                             f"{stem}/{PRESETS}/order.txt": "a.json\n",
                                             f"{stem}/{MODULE}": "vst3"})
        # The staging folder goes; the archive is all that is left.
        self.assertEqual(names(out), [archive.name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
