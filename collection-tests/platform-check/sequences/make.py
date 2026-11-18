"""Writes the platform check's sequences, the `.mid` files beside this script (AGENTS.md).

    python3 make.py

Each is written the way MXM Player's own writer writes one, so it loads with nothing lost
(mxm-player's `src/sequencer/smf.rs`): one track on channel 1, 96 ticks to the quarter (a
sixteenth step is 24), every note at velocity 100, and a note either half a step long (a plain
step) or a whole number of steps, two or more (a tied run). 4/4 at the tempo of `cases.json`.
A file ends at its last note; the render's length is the case's `bars`, which leaves the tail.
"""

import json
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
TICKS = 96
STEP = TICKS // 4
VELOCITY = 100


def note_runs(*notes):
    """`(step, key, steps)` from one-based steps; `steps` 0 is the half-step gate."""
    return [(step - 1, key, steps) for step, key, steps in notes]


# A bass line in C minor over two bars: plain steps and tied runs, never two notes at once.
MONO = note_runs(
    (1, 36, 2), (3, 36, 0), (4, 48, 0), (5, 39, 2), (7, 41, 0), (8, 43, 4), (12, 46, 0),
    (13, 43, 0), (14, 41, 2), (16, 39, 0),
    (17, 36, 4), (21, 48, 0), (22, 46, 0), (23, 43, 2), (25, 41, 0), (26, 39, 0), (27, 36, 6),
)

# Four chords of two beats each: Cm7, Abmaj7, Fm7, G7.
CHORDS = note_runs(*[
    (start, key, 8)
    for start, chord in [(1, [60, 63, 67, 70]), (9, [56, 60, 63, 67]),
                         (17, [53, 56, 60, 63]), (25, [55, 59, 62, 65])]
    for key in chord
])

# A bar of groove (kick 36, snare 38, closed hat 42), then every drum note 36-51 once, a step each.
DRUMS = note_runs(
    *[(step, 42, 0) for step in range(1, 17, 2)],
    *[(step, 36, 0) for step in (1, 7, 9, 11)],
    *[(step, 38, 0) for step in (5, 13)],
    *[(17 + index, 36 + index, 0) for index in range(16)],
)

# What an effect is played: four short stabs, then a chord held two beats, then nothing.
SOURCE = note_runs(
    *[(step, key, 0) for step in (1, 4, 7, 11) for key in (48, 55, 58, 63)],
    *[(17, key, 8) for key in (44, 51, 55, 60)],
)


def vlq(value):
    """SMF's variable-length quantity."""
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def smf(runs, tempo):
    events = []
    for step, key, steps in runs:
        start = step * STEP
        length = STEP // 2 if steps == 0 else steps * STEP
        events.append((start + length, 0, bytes([0x80, key, 0])))
        events.append((start, 1, bytes([0x90, key, VELOCITY])))
    events.sort(key=lambda e: (e[0], e[1]))
    microseconds = round(60_000_000 / tempo)
    track = bytearray()
    track += vlq(0) + b"\xff\x51\x03" + microseconds.to_bytes(3, "big")
    track += vlq(0) + b"\xff\x58\x04" + bytes([4, 2, 24, 8])
    now = 0
    for tick, _, message in events:
        track += vlq(tick - now) + message
        now = tick
    track += vlq(0) + b"\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS) + b"MTrk" + struct.pack(">I", len(track)) + track


def main():
    tempo = json.loads((HERE.parent / "cases.json").read_text())["tempo"]
    for name, runs in [("mono", MONO), ("chords", CHORDS), ("drums", DRUMS), ("source", SOURCE)]:
        path = HERE / f"{name}.mid"
        path.write_bytes(smf(runs, tempo))
        print(path)


if __name__ == "__main__":
    main()
