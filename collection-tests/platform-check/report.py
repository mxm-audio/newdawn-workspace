"""The platform check's report (`check.py report`, AGENTS.md): every target's results, each render
and picture checked on its own and against the same case on the reference target, a summary, and
sheets to look at before anything is reported.

Writes `<out>/report/`: `summary.txt` (printed too), `windows-N.png` (each case's window on every
target, a problem framed red) and the sound sheets of mxm-tools' `sheets.py`, one set per other
target (`sounds-<target>/`: each case's render beside the reference target's, a plugin a row and its
presets the columns, on the `level` and `hz-difference` views). The pictures end the output as `LOOK: <path>` lines.

On its own, a render fails when it isn't finite or is silent (its peak under `SILENT_DB`), and is
flagged when it clips or carries DC; an effect's is flagged when it is the dry source's within
`UNCHANGED_DB` (the difference, sample by sample, that far under the source: a pass-through). A picture fails when it is blank or black. Against the reference: a render's level
more than `LEVEL_DB` away, or its band levels on average more than `BANDS_DB`; a picture more than
`PICTURE_DIFF` apart (mean grey difference out of 255, the candidate scaled to the reference's
pixels). **Two pictures are compared only when both editors opened at one size in points**, within
`SIZE`: an editor opens at a size its screen allows and on a smaller one lays itself out otherwise,
so a size that differs is said, and left to the eye on the window sheets.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SHEETS = HERE.parent.parent / "tools" / "mxm-tools" / "sheets" / "sheets.py"
sys.path.insert(0, str(SHEETS.parent))
from sheets import read_wav  # noqa: E402

SILENT_DB = -60.0
CLIP_DB = -0.01
DC = 0.05
UNCHANGED_DB = -60.0
LEVEL_DB = 3.0
BANDS_DB = 6.0
PICTURE_DIFF = 20.0
SIZE = 0.02
SHEET = (1560, 736)
SOURCE_CASE = "effect-source"


def db(x):
    return 20 * np.log10(max(float(x), 1e-12))


def bands(samples, rate):
    """Band levels (dB) in third-octave bands from 40 Hz, over 50 ms frames: how a render sounds,
    coarse enough to hold across platforms and sample rates."""
    frame = int(rate * 0.05)
    count = len(samples) // frame
    if count == 0:
        return np.zeros((0, 0))
    frames = samples[:count * frame].reshape(count, frame) * np.hanning(frame)
    spectrum = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(frame, 1 / rate)
    edges = 40 * 2 ** (np.arange(0, 28) / 3)
    edges = edges[edges < min(rate / 2, 20000)]
    out = [spectrum[:, (freqs >= lo) & (freqs < hi)].sum(axis=1) for lo, hi in zip(edges[:-1], edges[1:])]
    return 10 * np.log10(np.array(out).T + 1e-20)


def check_audio(path):
    samples, rate = read_wav(str(path))
    samples = np.asarray(samples, dtype=float)
    facts = {"rate": rate, "seconds": round(len(samples) / rate, 2)}
    problems, flags = [], []
    if not np.isfinite(samples).all():
        return facts, ["the render isn't finite"], flags, None
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    facts["peak_db"] = round(db(peak), 1)
    facts["rms_db"] = round(10 * np.log10(float(np.mean(samples ** 2)) + 1e-20), 1)
    if facts["peak_db"] < SILENT_DB:
        problems.append(f"silent (peak {facts['peak_db']} dBFS)")
    if facts["peak_db"] >= CLIP_DB:
        flags.append("it reaches full scale")
    if abs(float(np.mean(samples))) > DC:
        flags.append(f"DC {np.mean(samples):+.3f}")
    return facts, problems, flags, (samples, rate)


def compare_audio(a, b):
    """How far `b` is from `a`: the level difference and the mean band difference where either sounds."""
    (x, xr), (y, yr) = a, b
    level = 10 * np.log10((np.mean(y ** 2) + 1e-20) / (np.mean(x ** 2) + 1e-20))
    bx, by = bands(x, xr), bands(y, yr)
    n = min(len(bx), len(by))
    m = min(bx.shape[1] if n else 0, by.shape[1] if n else 0)
    if n == 0 or m == 0:
        return float(level), float("inf")
    bx, by = bx[:n, :m], by[:n, :m]
    floor = max(bx.max(), by.max()) - 60
    sounding = (bx > floor) | (by > floor)
    diff = np.abs(np.maximum(bx, floor) - np.maximum(by, floor))[sounding]
    return float(level), float(diff.mean()) if diff.size else 0.0


def editor_shot(case, shots_dir):
    """The case's plugin's window among those captured: titled with its name, else the largest that
    isn't the player's or the effect source's."""
    if "editor" in case:
        shot = next((s for s in case.get("shots") or [] if s["file"] == case["editor"]), None)
        path = shots_dir / case["editor"] if case["editor"] else None
        return (path, shot) if path and path.exists() else (None, None)
    shots = case.get("shots") or []
    named = [s for s in shots if case["plugin"] in s.get("title", "")]
    if not named:
        def other(shot):
            title = shot.get("title", "")
            return "MXM Player" not in title
        named = sorted(filter(other, shots), key=lambda s: -s["width"] * s["height"])
    if not named:
        return None, None
    path = shots_dir / named[0]["file"]
    return (path, named[0]) if path.exists() else (None, None)


def check_picture(path):
    image = Image.open(path).convert("L")
    grey = np.asarray(image, dtype=float)
    problems = []
    if grey.std() < 3:
        problems.append("the window is blank")
    if (grey < 10).mean() > 0.9:
        problems.append("the window is black")
    return problems


def compare_pictures(reference, candidate):
    """The mean grey difference (out of 255), the candidate scaled to the reference's pixels: a
    Retina screen's picture has twice a point's pixels."""
    a, b = Image.open(reference).convert("L"), Image.open(candidate).convert("L")
    b = b.resize(a.size, Image.LANCZOS)
    return float(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)).mean())


def font(size):
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def window_sheets(rows, targets, out):
    """Each case's window on every target, side by side; a failed or flagged one framed red."""
    per_row = max(1, 4 // len(targets))
    cell_w = SHEET[0] // (per_row * len(targets))
    label_h, cell_h = 22, (SHEET[1] - 2 * 22) // 2
    pages, page, made = [], [], []
    for row in rows:
        page.append(row)
        if len(page) == per_row * 2:
            pages.append(page)
            page = []
    if page:
        pages.append(page)
    small = font(14)
    for number, page in enumerate(pages, 1):
        sheet = Image.new("RGB", SHEET, "white")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(page):
            top = (index // per_row) * (label_h + cell_h)
            left0 = (index % per_row) * cell_w * len(targets)
            for t, target in enumerate(targets):
                left = left0 + t * cell_w
                entry = row["targets"].get(target, {})
                draw.text((left + 4, top + 3), f"{row['case']} · {target}", fill="black", font=small)
                path = entry.get("picture")
                if path:
                    image = Image.open(path).convert("RGB")
                    image.thumbnail((cell_w - 8, cell_h - 8))
                    sheet.paste(image, (left + 4, top + label_h + 2))
                else:
                    draw.text((left + 8, top + label_h + 20), entry.get("failed") or "no picture",
                              fill="red", font=small)
                if entry.get("picture_problems") or entry.get("failed"):
                    draw.rectangle([left + 1, top + 1, left + cell_w - 2, top + label_h + cell_h - 2],
                                   outline="red", width=3)
        path = out / f"windows-{number}.png"
        sheet.save(path)
        made.append(path)
    return made


def main(args):
    out = Path(args.out)
    targets = sorted(p.name for p in out.iterdir() if (p / "results.json").exists())
    if not targets:
        raise SystemExit(f"no results under {out}")
    reference = args.reference if args.reference in targets else targets[0]
    targets = [reference] + [t for t in targets if t != reference]
    results = {t: json.loads((out / t / "results.json").read_text()) for t in targets}
    # The cases `cases.json` has now, in its order: a result left from a case since removed is not
    # reported.
    import check
    _, current = check.load_cases(None)
    kept = {c["case"] for t in targets for c in results[t]["cases"]}
    names = [c["name"] for c in current if c["name"] in kept]
    numbers = {}
    for c in current:
        numbers[c["name"]] = sum(1 for o in current if o["plugin"] == c["plugin"]
                                 and o["name"] != "effect-source" and current.index(o) <= current.index(c))

    report = out / "report"
    report.mkdir(exist_ok=True)
    rows, lines, audio = [], [], {}
    for name in names:
        row = {"case": name, "targets": {}}
        for t in targets:
            case = next((c for c in results[t]["cases"] if c["case"] == name), None)
            if case is None:
                continue
            entry = {"commit": (case.get("commit") or "")[:7], "ran": case.get("ran")}
            if "skipped" in case or "failed" in case:
                entry["failed"] = case.get("failed") or case.get("skipped")
                row["targets"][t] = entry
                continue
            facts, problems, flags, sound = check_audio(out / t / case["wav"])
            entry.update(facts=facts, problems=problems, flags=flags, wav=str(out / t / case["wav"]))
            audio[(name, t)] = sound
            picture, shot = editor_shot(case, out / t / "shots")
            entry["picture"] = str(picture) if picture else None
            entry["points"] = [shot["width"], shot["height"]] if shot else None
            entry["picture_problems"] = (check_picture(picture) if picture
                                         else [case.get("shot_error") or "no window was captured"])
            row["targets"][t] = entry
        rows.append(row)

    # Against the dry source, and against the reference target.
    for row in rows:
        for t, entry in row["targets"].items():
            if "failed" in entry:
                continue
            source = audio.get((SOURCE_CASE, t))
            mine = audio.get((row["case"], t))
            kind = next((c.get("kind") for c in results[t]["cases"] if c["case"] == row["case"]), None)
            if kind == "effect" and source is not None and mine is not None:
                (x, xr), (y, yr) = source, mine
                n = min(len(x), len(y))
                if xr == yr and n:
                    residual = 10 * np.log10((np.mean((y[:n] - x[:n]) ** 2) + 1e-30) / (np.mean(x[:n] ** 2) + 1e-30))
                    entry["facts"]["residual_db"] = round(float(residual), 1)
                    if residual < UNCHANGED_DB:
                        entry["flags"].append("the effect left the source as it was")
            if t == reference:
                continue
            ref = row["targets"].get(reference)
            if not ref or "failed" in ref or mine is None:
                continue
            level, spread = compare_audio(audio[(row["case"], reference)], mine)
            entry["against_reference"] = {"level_db": round(level, 1), "bands_db": round(spread, 1)}
            if abs(level) > LEVEL_DB:
                entry["problems"].append(f"{level:+.1f} dB from {reference}")
            if spread > BANDS_DB:
                entry["problems"].append(f"bands {spread:.1f} dB from {reference}'s")
            if entry.get("picture") and ref.get("picture"):
                (w, h), (rw, rh) = entry["points"], ref["points"]
                if abs(w - rw) > SIZE * rw or abs(h - rh) > SIZE * rh:
                    entry["flags"].append(f"its editor opened at {w}x{h}, {reference}'s at {rw}x{rh}: "
                                          "the screens differ, so the pictures are compared by eye")
                else:
                    diff = compare_pictures(ref["picture"], entry["picture"])
                    entry["against_reference"]["picture_diff"] = round(diff, 1)
                    if diff > PICTURE_DIFF:
                        entry["picture_problems"].append(f"it looks {diff:.0f}/255 unlike {reference}'s")

    failed = 0
    for row in rows:
        for t, entry in row["targets"].items():
            bad = ([entry["failed"]] if "failed" in entry else []) + entry.get("problems", []) \
                + entry.get("picture_problems", [])
            facts = entry.get("facts", {})
            compared = entry.get("against_reference")
            line = (f"{'FAIL' if bad else 'ok  '} {row['case']:<52} {t:<11} "
                    + (f"peak {facts.get('peak_db')} rms {facts.get('rms_db')} " if facts else "")
                    + (f"vs {reference}: {compared} " if compared else "")
                    + ("; ".join(bad + entry.get("flags", []))))
            lines.append(line.rstrip())
            failed += bool(bad)
    summary = "\n".join([f"The platform check: {len(rows)} cases on {', '.join(targets)} "
                         f"(reference {reference}); {failed} failing.", ""] + lines)
    (report / "summary.txt").write_text(summary + "\n")
    (report / "report.json").write_text(json.dumps(rows, indent=1, default=str))
    print(summary)

    for old in report.glob("windows-*.png"):
        old.unlink()
    for old in report.glob("sounds*"):
        if old.is_dir():
            for f in old.iterdir():
                f.unlink()
            old.rmdir()
        else:
            old.unlink()
    looks = window_sheets(rows, targets, report)

    # The sounds: per other target, each case's render beside the reference target's, a plugin a
    # row and its presets the columns, on the two views that compare a set across platforms.
    sound_looks = []
    others = targets[1:] or [None]
    for other in others:
        manifest = ["row\tcol\treference\tcandidate"]
        for row in rows:
            ref = row["targets"].get(reference, {})
            cand = row["targets"].get(other, {}) if other else {}
            if "wav" not in ref or (other and "wav" not in cand):
                continue
            # A plugin a row, its presets numbered in `cases.json`'s order the columns: every
            # plugin has two, so the set fits a few pages. The dry source is a row of its own.
            plugin = row["case"].partition("--")[0].removeprefix("mxm-")
            column = "dry" if row["case"] == "effect-source" else f"preset {numbers[row['case']]}"
            manifest.append(f"{plugin}\t{column}\t{ref['wav']}\t{cand.get('wav', '')}")
        if len(manifest) == 1:
            continue
        folder = report / f"sounds-{other or reference}"
        (report / f"sounds-{other or reference}.tsv").write_text("\n".join(manifest) + "\n")
        views = "level,hz-difference" if other else "level,hz-reference"
        drawn = subprocess.run([sys.executable, str(SHEETS), "set", str(report / f"sounds-{other or reference}.tsv"),
                                str(folder), "--title", f"The platform check: {other or reference}",
                                "--names", f"{reference},{other or reference}", "--views", views],
                               capture_output=True, text=True)
        if drawn.returncode:
            print(drawn.stderr[-2000:])
        sound_looks += [line for line in drawn.stdout.splitlines() if line.startswith("LOOK: ")]
    for path in looks:
        print(f"LOOK: {path}")
    for line in sound_looks:
        print(line)
