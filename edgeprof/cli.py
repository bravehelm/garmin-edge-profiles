"""edgeprof: read, diff and edit Garmin Edge activity-profile files over USB.

    python -m edgeprof show  Cycling.fit            # data screens and recurring alerts
    python -m edgeprof dump  Cycling.fit            # every message and field, raw
    python -m edgeprof diff  before.fit after.fit   # what changed between two copies
    python -m edgeprof set-screen Cycling.fit --screen 1 --fields "Speed,Cadence,Timer" --out new.fit

Writing never touches the source file: `set-screen` writes a copy. Put that copy in the Edge's
`Garmin/NewFiles/` folder and the device imports it at the next start-up.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import fit, names

SCREEN, ALERT = 14, 16


def _load(path: str) -> fit.FitFile:
    data = Path(path).read_bytes()
    f = fit.parse(data)
    if not fit.check_crc(data):
        print(f"warning: {path}: file CRC does not match", file=sys.stderr)
    return f


def _fields(ids) -> str:
    ids = ids if isinstance(ids, list) else [ids]
    return ", ".join(names.field_name(i) for i in ids if i != 65535) or "(none)"


def show(args) -> int:
    f = _load(args.file)
    print("Data screens (message 14):")
    print(f"  {'slot':>4}  {'on':>2}  {'order':>5}  {'hidden':>6}  {'type':<10}  fields")
    for m in f.of(SCREEN):
        ids = m.get(7, [])
        count = m.get(3)
        shown = ids[:count] if isinstance(ids, list) and isinstance(count, int) and count < 255 else ids
        on = "y" if m.get(1) == 1 else "-"
        stype = names.SCREEN_TYPES.get(m.get(10), str(m.get(10, "")))
        print(f"  {m.get(254, '?'):>4}  {on:>2}  {str(m.get(9, '')):>5}  {str(m.get(12, '')):>6}  {stype:<10}  {_fields(shown)}")
    alerts = f.of(ALERT)
    if alerts:
        print("Recurring alerts (message 16):")
        for m in alerts:
            kind = {0: "time"}.get(m.get(1), f"type {m.get(1)}")
            val = m.get(2)
            if kind == "time" and isinstance(val, int):
                val = f"{val / 60000:g} min"
            print(f"  {kind:<8} every {val}  {'on' if m.get(3) == 1 else 'off'}")
    return 0


def dump(args) -> int:
    f = _load(args.file)
    for m in f.messages:
        label = names.MESSAGES.get(m.global_num, "")
        vals = "  ".join(f"{n}={fl.value}" for n, fl in sorted(m.fields.items()))
        print(f"#{m.index:<4} msg {m.global_num:<5} {label:<16} {vals}")
    return 0


def _keyed(f: fit.FitFile):
    """Key messages by (message number, occurrence) so two copies of a profile line up."""
    seen: dict[int, int] = {}
    out = {}
    for m in f.messages:
        k = seen.get(m.global_num, 0)
        seen[m.global_num] = k + 1
        out[(m.global_num, k)] = m
    return out


def diff(args) -> int:
    a, b = _keyed(_load(args.before)), _keyed(_load(args.after))
    changes = 0
    for key in sorted(set(a) | set(b)):
        ma, mb = a.get(key), b.get(key)
        label = f"msg {key[0]} #{key[1]}"
        if ma is None or mb is None:
            print(f"{label}: only in {'after' if ma is None else 'before'}")
            changes += 1
            continue
        for n in sorted(set(ma.fields) | set(mb.fields)):
            va, vb = ma.get(n), mb.get(n)
            if va != vb:
                print(f"{label} field {n}: {va} -> {vb}")
                changes += 1
    print(f"{changes} difference(s)" if changes else "no differences")
    return 0


def set_screen(args) -> int:
    f = _load(args.file)
    target = [m for m in f.of(SCREEN) if m.get(254) == args.screen]
    if not target:
        print(f"no data screen with slot {args.screen}", file=sys.stderr)
        return 2
    m = target[0]
    ids = [names.field_id(t) for t in args.fields.split(",") if t.strip()]
    slots = m.fields[7].size // 2
    if len(ids) > slots:
        print(f"a screen holds at most {slots} fields", file=sys.stderr)
        return 2
    edits = [(m.fields[7], ids + [65535] * (slots - len(ids)))]
    if 3 in m.fields:
        edits.append((m.fields[3], len(ids)))
    out = Path(args.out)
    if out.resolve() == Path(args.file).resolve():
        print("--out must be a new file; the source is never overwritten", file=sys.stderr)
        return 2
    out.write_bytes(fit.patch(f, edits))
    print(f"wrote {out}: screen {args.screen} = {_fields(ids)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="edgeprof", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("file"); s.set_defaults(fn=show)
    s = sub.add_parser("dump"); s.add_argument("file"); s.set_defaults(fn=dump)
    s = sub.add_parser("diff"); s.add_argument("before"); s.add_argument("after"); s.set_defaults(fn=diff)
    s = sub.add_parser("set-screen")
    s.add_argument("file"); s.add_argument("--screen", type=int, required=True)
    s.add_argument("--fields", required=True, help="comma-separated names or numeric IDs")
    s.add_argument("--out", required=True); s.set_defaults(fn=set_screen)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (fit.FitError, KeyError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
